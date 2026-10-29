using System.Text.RegularExpressions;

namespace Reroll.Core;

/// <summary>Finds where Medal saves clips. Medal's default is a Medal folder under Videos with a
/// Clips folder inside, one subfolder per game; players can move it (Settings > PC Storage >
/// Capture Folder Location), so Medal's own settings files are searched for the path too.</summary>
public static class MedalLocator
{
    static readonly string[] VideoExtensions = [".mp4", ".mkv", ".mov"];

    public static string? Find(string? videosFolder = null, string? appData = null)
    {
        videosFolder ??= Environment.GetFolderPath(Environment.SpecialFolder.MyVideos);
        appData ??= Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);

        foreach (var candidate in FromMedalSettings(appData).Concat(Defaults(videosFolder)))
        {
            var clips = Directory.Exists(Path.Combine(candidate, "Clips")) ? Path.Combine(candidate, "Clips") : candidate;
            if (Directory.Exists(clips))
                return clips;
        }
        return null;
    }

    static IEnumerable<string> Defaults(string videos)
    {
        yield return Path.Combine(videos, "Medal", "Clips");
        yield return Path.Combine(videos, "Medal");
    }

    /// <summary>Paths that look like a Medal capture folder inside %APPDATA%\Medal's JSON files.</summary>
    internal static IEnumerable<string> FromMedalSettings(string appData)
    {
        var root = Path.Combine(appData, "Medal");
        if (!Directory.Exists(root))
            yield break;
        IEnumerable<string> files;
        try { files = Directory.EnumerateFiles(root, "*.json", SearchOption.AllDirectories).Take(200).ToList(); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { yield break; }
        var pattern = new Regex(@"""[^""]*(?:clip|capture|record)[^""]*(?:folder|dir|path|location)[^""]*""\s*:\s*""((?:[^""\\]|\\.)+)""",
                                RegexOptions.IgnoreCase);
        foreach (var file in files)
        {
            string text;
            try { text = File.ReadAllText(file); }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { continue; }
            foreach (Match m in pattern.Matches(text))
            {
                var value = Regex.Unescape(m.Groups[1].Value);
                if (Path.IsPathFullyQualified(value))
                    yield return value;
            }
        }
    }

    public static bool IsVideo(string path) =>
        VideoExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase);
}
