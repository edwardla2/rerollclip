using System.Text.Json;
using System.Text.Json.Serialization;

namespace Reroll.Core;

/// <summary>What the app remembers between runs, kept in %APPDATA%\Reroll\settings.json.</summary>
public sealed class Settings
{
    /// <summary>The Medal capture folder Reroll watches (null until found or chosen).</summary>
    public string? MedalFolder { get; set; }

    /// <summary>Where finished videos go. Default: Videos\Reroll.</summary>
    public string? OutputFolder { get; set; }

    /// <summary>When the last video was made (Unix seconds); plays saved after it are "new".</summary>
    public double? LastVideoAt { get; set; }

    [JsonIgnore]
    public string ResolvedOutputFolder =>
        string.IsNullOrWhiteSpace(OutputFolder)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyVideos), "Reroll")
            : OutputFolder!;

    static readonly JsonSerializerOptions Json = new() { WriteIndented = true };

    public static string DefaultPath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Reroll", "settings.json");

    public static Settings Load(string? path = null)
    {
        path ??= DefaultPath;
        try
        {
            return File.Exists(path) ? JsonSerializer.Deserialize<Settings>(File.ReadAllText(path)) ?? new() : new();
        }
        catch (Exception e) when (e is JsonException or IOException or UnauthorizedAccessException)
        {
            return new();   // a broken settings file shouldn't stop the app; it's rewritten on save
        }
    }

    public void Save(string? path = null)
    {
        path ??= DefaultPath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var tmp = path + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(this, Json));
        File.Move(tmp, path, overwrite: true);
    }
}
