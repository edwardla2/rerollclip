using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Reroll.Core;

/// <summary>One play the engine found: a clip with your kills in it.</summary>
public sealed record Play(
    [property: JsonPropertyName("clip")] string Clip,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("kills")] int Kills,
    [property: JsonPropertyName("ace")] bool Ace,
    [property: JsonPropertyName("saved_at")] double? SavedAt,
    [property: JsonPropertyName("duration")] double? Duration,
    [property: JsonPropertyName("confidence")] string? Confidence);

public sealed record ScanResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("new")] int New,
    [property: JsonPropertyName("clips")] int Clips,
    [property: JsonPropertyName("plays")] int PlayCount,
    [property: JsonPropertyName("summary")] IReadOnlyList<Play> Plays);

public sealed record MakeResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("output")] string? Output,
    [property: JsonPropertyName("seconds")] double? Seconds,
    [property: JsonPropertyName("reason")] string? Reason,
    [property: JsonPropertyName("message")] string? Message,
    [property: JsonPropertyName("plays")] IReadOnlyList<string>? Plays,
    [property: JsonPropertyName("notes")] IReadOnlyList<string>? Notes);

/// <summary>Where the work is, for a progress bar: a stage and how far through the whole job.</summary>
public sealed record EngineProgress(string Stage, double Overall, string? Item)
{
    /// <summary>What to show the player for each engine stage.</summary>
    public string Label => Stage switch
    {
        "analysing" => Item is { Length: > 0 } ? $"Looking for your plays in {Item}" : "Looking for your plays",
        "cutting" => "Cutting your plays",
        "finishing" => "Finishing the video",
        _ => "Working",
    };
}

public sealed class EngineException(string message) : Exception(message);

/// <summary>Runs the bundled engine (reroll-engine.exe) and reads its JSON lines: progress lines
/// while it works ({"stage","progress","item"}), then one result object.</summary>
public sealed class Engine
{
    /// <summary>The program and the arguments that come before the command, e.g.
    /// ["C:\...\engine\reroll-engine.exe"] or ["python3", "-m", "clipthat_editor"].</summary>
    public IReadOnlyList<string> Command { get; }

    public Engine(IReadOnlyList<string> command) => Command = command;

    /// <summary>The engine next to the app (engine\reroll-engine.exe), or the REROLL_ENGINE
    /// environment variable (a command line, for development).</summary>
    public static Engine Default(string? appDir = null)
    {
        var overrideCmd = Environment.GetEnvironmentVariable("REROLL_ENGINE");
        if (!string.IsNullOrWhiteSpace(overrideCmd))
            return new Engine(overrideCmd.Split(' ', StringSplitOptions.RemoveEmptyEntries));
        appDir ??= AppContext.BaseDirectory;
        var exe = OperatingSystem.IsWindows() ? "reroll-engine.exe" : "reroll-engine";
        return new Engine([System.IO.Path.Combine(appDir, "engine", "reroll-engine", exe)]);
    }

    // Each stage's share of the whole job, so one bar moves steadily from start to end.
    static readonly Dictionary<string, (double Start, double Span)> Stages = new()
    {
        ["analysing"] = (0.00, 0.10),
        ["cutting"] = (0.10, 0.45),
        ["finishing"] = (0.55, 0.45),
    };

    internal static EngineProgress? ParseProgress(JsonElement e)
    {
        if (!e.TryGetProperty("stage", out var stage) || !e.TryGetProperty("progress", out var p))
            return null;
        var name = stage.GetString() ?? "";
        var frac = Math.Clamp(p.GetDouble(), 0, 1);
        var (start, span) = Stages.GetValueOrDefault(name, (0.0, 0.0));
        var item = e.TryGetProperty("item", out var i) ? i.GetString() : null;
        return new EngineProgress(name, Math.Round(start + span * frac, 4), item);
    }

    public Task<ScanResult> ScanAsync(string folder, IProgress<EngineProgress>? progress = null, CancellationToken ct = default) =>
        RunAsync<ScanResult>(["library", "scan", folder, "--progress"], progress, ct);

    public Task<MakeResult> MakeAsync(string folder, string output, double? since,
                                      IProgress<EngineProgress>? progress = null, CancellationToken ct = default)
    {
        var args = new List<string> { "library", "make", folder, "--output", output, "--progress" };
        if (since is double s)
            args.AddRange(["--since", s.ToString("F3", System.Globalization.CultureInfo.InvariantCulture)]);
        return RunAsync<MakeResult>(args, progress, ct);
    }

    async Task<T> RunAsync<T>(IReadOnlyList<string> args, IProgress<EngineProgress>? progress, CancellationToken ct)
    {
        var psi = new ProcessStartInfo(Command[0])
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,            // no console window flashing up behind the app
            StandardOutputEncoding = Encoding.UTF8,
        };
        foreach (var a in Command.Skip(1).Concat(args))
            psi.ArgumentList.Add(a);
        psi.Environment["PYTHONIOENCODING"] = "utf-8";

        using var proc = new Process { StartInfo = psi };
        try { proc.Start(); }
        catch (System.ComponentModel.Win32Exception e)
        {
            throw new EngineException($"Couldn't start the editing engine ({Command[0]}): {e.Message}");
        }
        var stderr = proc.StandardError.ReadToEndAsync(ct);
        using var reg = ct.Register(() => { try { proc.Kill(entireProcessTree: true); } catch (InvalidOperationException) { } });

        string? last = null;
        while (await proc.StandardOutput.ReadLineAsync(ct) is { } line)
        {
            line = line.Trim();
            if (!line.StartsWith('{'))
                continue;
            try
            {
                using var doc = JsonDocument.Parse(line);
                if (ParseProgress(doc.RootElement) is { } p)
                {
                    progress?.Report(p);
                    continue;
                }
            }
            catch (JsonException) { continue; }
            last = line;                       // the result is the last JSON line that isn't progress
        }
        await proc.WaitForExitAsync(ct);
        var err = await stderr;
        if (last is null)
            throw new EngineException(ErrorFrom(err) ?? (proc.ExitCode == 0
                ? "The editing engine finished without a result."
                : $"The editing engine stopped (code {proc.ExitCode}). {Tail(err)}"));
        var result = JsonSerializer.Deserialize<T>(last) ?? throw new EngineException("Couldn't read the engine's result.");
        using (var doc = JsonDocument.Parse(last))
            if (doc.RootElement.TryGetProperty("error", out var e) && e.GetString() is { } msg)
                throw new EngineException(msg);
        return result;
    }

    /// <summary>The engine reports failures as {"ok": false, "error": "..."} on stderr.</summary>
    internal static string? ErrorFrom(string stderr)
    {
        foreach (var line in stderr.Split('\n').Reverse())
        {
            var t = line.Trim();
            if (!t.StartsWith('{'))
                continue;
            try
            {
                using var doc = JsonDocument.Parse(t);
                if (doc.RootElement.TryGetProperty("error", out var e) && e.GetString() is { Length: > 0 } msg)
                    return msg;
            }
            catch (JsonException) { }
        }
        return null;
    }

    static string Tail(string s) => s.Length <= 600 ? s.Trim() : s[^600..].Trim();
}
