using System.Reflection;
using System.Text.Json;
using Reroll.Core;

var tests = typeof(Tests).GetMethods(BindingFlags.Public | BindingFlags.Static)
    .Where(m => m.Name.StartsWith("Test")).OrderBy(m => m.Name).ToList();
var only = args.FirstOrDefault();
int failed = 0, ran = 0;
foreach (var t in tests)
{
    if (only is not null && !t.Name.Contains(only, StringComparison.OrdinalIgnoreCase))
        continue;
    ran++;
    try
    {
        if (t.Invoke(null, null) is Task task) await task;
        Console.WriteLine($"ok   {t.Name}");
    }
    catch (Exception e)
    {
        failed++;
        var inner = e is TargetInvocationException { InnerException: { } i } ? i : e;
        Console.WriteLine($"FAIL {t.Name}: {inner.GetType().Name}: {inner.Message}");
    }
}
Console.WriteLine($"{ran - failed}/{ran} passed");
return failed == 0 ? 0 : 1;

static class Tests
{
    static void Eq<T>(T expected, T actual, string what = "")
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
            throw new Exception($"{what} expected {expected}, got {actual}");
    }

    static void True(bool cond, string what)
    {
        if (!cond) throw new Exception(what);
    }

    static string TempDir()
    {
        var d = Path.Combine(Path.GetTempPath(), "reroll-test-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(d);
        return d;
    }

    static string RepoRoot()
    {
        var d = new DirectoryInfo(AppContext.BaseDirectory);
        while (d is not null && !Directory.Exists(Path.Combine(d.FullName, "clipthat_editor")))
            d = d.Parent;
        return d?.FullName ?? throw new Exception("repo root not found");
    }

    static string Python => OperatingSystem.IsWindows() ? "python" : "python3";

    // ---- settings

    public static void TestSettingsRoundTrip()
    {
        var path = Path.Combine(TempDir(), "s", "settings.json");
        new Settings { MedalFolder = @"D:\Medal\Clips", LastVideoAt = 1793237295.5 }.Save(path);
        var s = Settings.Load(path);
        Eq(@"D:\Medal\Clips", s.MedalFolder);
        Eq(1793237295.5, s.LastVideoAt);
    }

    public static void TestBrokenSettingsFileGivesDefaults()
    {
        var path = Path.Combine(TempDir(), "settings.json");
        File.WriteAllText(path, "{ not json");
        var s = Settings.Load(path);
        Eq(null, s.MedalFolder);
        True(s.ResolvedOutputFolder.EndsWith("Reroll"), "default output folder is Videos\\Reroll");
    }

    // ---- finding the Medal folder

    public static void TestFindsDefaultMedalFolder()
    {
        var videos = TempDir();
        var clips = Path.Combine(videos, "Medal", "Clips");
        Directory.CreateDirectory(Path.Combine(clips, "Valorant"));
        Eq(clips, MedalLocator.Find(videos, TempDir()));
    }

    public static void TestFindsMovedFolderFromMedalSettings()
    {
        var appData = TempDir();
        var moved = Path.Combine(TempDir(), "My Clips");
        Directory.CreateDirectory(Path.Combine(moved, "Clips"));
        Directory.CreateDirectory(Path.Combine(appData, "Medal", "store"));
        File.WriteAllText(Path.Combine(appData, "Medal", "store", "settings.json"),
            JsonSerializer.Serialize(new Dictionary<string, object> { ["theme"] = "dark", ["clipFolderPath"] = moved }));
        Eq(Path.Combine(moved, "Clips"), MedalLocator.Find(TempDir(), appData));
    }

    public static void TestNoMedalFolderIsNull() => Eq(null, MedalLocator.Find(TempDir(), TempDir()));

    // ---- reading the engine

    public static void TestProgressMapsStagesOntoOneBar()
    {
        EngineProgress P(string json) => Engine.ParseProgress(JsonDocument.Parse(json).RootElement)!;
        Eq(0.05, P("""{"stage":"analysing","progress":0.5,"item":"a.mp4"}""").Overall);
        Eq(0.10, P("""{"stage":"cutting","progress":0}""").Overall);
        Eq(1.0, P("""{"stage":"finishing","progress":1}""").Overall);
        Eq("Looking for your plays in a.mp4", P("""{"stage":"analysing","progress":0.5,"item":"a.mp4"}""").Label);
        Eq(null, Engine.ParseProgress(JsonDocument.Parse("""{"ok":true}""").RootElement));
    }

    public static void TestEngineErrorIsReadFromStderr()
    {
        Eq("Required executable 'ffmpeg' is missing from PATH",
           Engine.ErrorFrom("Traceback...\n{\"ok\": false, \"error\": \"Required executable 'ffmpeg' is missing from PATH\"}\n"));
        Eq(null, Engine.ErrorFrom("plain text"));
    }

    static Engine FakeEngine(string script)
    {
        var path = Path.Combine(TempDir(), "fake_engine.py");
        File.WriteAllText(path, script);
        return new Engine([Python, path]);
    }

    public static async Task TestMakeReportsProgressThenResult()
    {
        var engine = FakeEngine("""
            import json, sys
            assert sys.argv[1:4] == ["library", "make", "F"], sys.argv
            assert "--since" in sys.argv and sys.argv[sys.argv.index("--since") + 1] == "12.500"
            for stage, p in (("analysing", 1.0), ("cutting", 0.5), ("finishing", 1.0)):
                print(json.dumps({"stage": stage, "progress": p, "item": ""}), flush=True)
            print("some log line")
            print(json.dumps({"ok": True, "output": "out.mp4", "seconds": 61.2, "plays": ["a", "b"], "notes": []}))
            """);
        var seen = new List<EngineProgress>();
        var result = await engine.MakeAsync("F", "out.mp4", 12.5, new SyncProgress<EngineProgress>(seen.Add));
        True(result.Ok, "ok");
        Eq("out.mp4", result.Output);
        Eq(3, seen.Count, "progress lines");
        Eq(0.325, seen[1].Overall, "cutting halfway");
    }

    public static async Task TestEngineFailureBecomesAReadableError()
    {
        var engine = FakeEngine("""
            import json, sys
            print(json.dumps({"ok": False, "error": "Can't read media x.mp4"}), file=sys.stderr)
            sys.exit(1)
            """);
        try
        {
            await engine.ScanAsync("F");
            throw new Exception("should have thrown");
        }
        catch (EngineException e) { Eq("Can't read media x.mp4", e.Message); }
    }

    public static async Task TestCancelStopsTheEngine()
    {
        var engine = FakeEngine("""
            import json, time
            for i in range(600):
                print(json.dumps({"stage": "cutting", "progress": i / 600}), flush=True)
                time.sleep(0.1)
            """);
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(1.5));
        var sw = System.Diagnostics.Stopwatch.StartNew();
        try
        {
            await engine.MakeAsync("F", "o.mp4", null, null, cts.Token);
            throw new Exception("should have been cancelled");
        }
        catch (OperationCanceledException) { }
        True(sw.Elapsed < TimeSpan.FromSeconds(10), "cancel is quick");
    }

    public static async Task TestMissingEngineIsReported()
    {
        try
        {
            await new Engine([Path.Combine(TempDir(), "nope.exe")]).ScanAsync("F");
            throw new Exception("should have thrown");
        }
        catch (EngineException e) { True(e.Message.StartsWith("Couldn't start the editing engine"), e.Message); }
    }

    /// <summary>The real engine (Python, from this repo) scanning a folder of clips with no kills.</summary>
    public static async Task TestRealEngineScansAFolder()
    {
        var folder = TempDir();
        var clip = Path.Combine(folder, "Valorant", "clip.mp4");
        Directory.CreateDirectory(Path.GetDirectoryName(clip)!);
        var ff = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("ffmpeg",
            ["-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3", "-f", "lavfi", "-i",
             "sine=frequency=330:duration=3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", clip]) { UseShellExecute = false })!;
        await ff.WaitForExitAsync();
        Environment.SetEnvironmentVariable("PYTHONPATH", RepoRoot());
        var seen = new List<EngineProgress>();
        var r = await new Engine([Python, "-m", "clipthat_editor"]).ScanAsync(folder, new SyncProgress<EngineProgress>(seen.Add));
        True(r.Ok, "ok");
        Eq(1, r.Clips, "clips");
        Eq(0, r.PlayCount, "plays");
        True(seen.Any(p => p.Stage == "analysing"), "reported analysing");
        True(File.Exists(Path.Combine(folder, ".reroll", "library.json")), "ledger written");
    }

    // ---- watching the folder

    public static async Task TestWatcherWaitsForTheClipToFinish()
    {
        var folder = TempDir();
        Directory.CreateDirectory(Path.Combine(folder, "Valorant"));
        var ready = new List<string>();
        using var w = new ClipWatcher(folder, settle: TimeSpan.FromSeconds(1), poll: TimeSpan.FromMilliseconds(200));
        w.ClipReady += p => { lock (ready) ready.Add(p); };
        var clip = Path.Combine(folder, "Valorant", "Valorant_2026-10-28.mp4");
        await using (var f = File.Create(clip))
        {
            for (int i = 0; i < 6; i++)
            {
                await f.WriteAsync(new byte[50_000]);
                await f.FlushAsync();
                await Task.Delay(300);
                lock (ready) Eq(0, ready.Count, "not ready while still being written");
            }
        }
        File.WriteAllText(Path.Combine(folder, "notes.txt"), "not a clip");
        File.WriteAllBytes(Path.Combine(folder, "Valorant", "x (Reroll).mp4"), new byte[10]);
        await Task.Delay(2500);
        lock (ready)
        {
            Eq(1, ready.Count, "one clip ready");
            Eq(clip, ready[0]);
        }
    }

    // ---- words

    public static void TestWords()
    {
        var now = DateTimeOffset.FromUnixTimeSeconds(1_800_000_000);
        Eq("5 min ago", Format.Ago(1_800_000_000 - 300, now));
        Eq("yesterday", Format.Ago(1_800_000_000 - 30 * 3600, now));
        Eq("Ace", Format.Kills(new Play("a", "a", 5, true, null, null, null)));
        Eq("1 kill", Format.Kills(new Play("a", "a", 1, false, null, null, null)));
        Eq("3 new plays.", Format.PlaysHeadline(3));
    }
}

/// <summary>IProgress that reports on the calling thread (Progress&lt;T&gt; posts to the thread pool).</summary>
sealed class SyncProgress<T>(Action<T> report) : IProgress<T>
{
    public void Report(T value) => report(value);
}
