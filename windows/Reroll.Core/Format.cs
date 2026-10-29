namespace Reroll.Core;

/// <summary>Words for the screen.</summary>
public static class Format
{
    public static string Ago(double? unixSeconds, DateTimeOffset? now = null)
    {
        if (unixSeconds is not double s)
            return "";
        var span = (now ?? DateTimeOffset.UtcNow) - DateTimeOffset.FromUnixTimeMilliseconds((long)(s * 1000));
        if (span.TotalMinutes < 1) return "just now";
        if (span.TotalHours < 1) return $"{(int)span.TotalMinutes} min ago";
        if (span.TotalDays < 1) return $"{(int)span.TotalHours} h ago";
        if (span.TotalDays < 2) return "yesterday";
        return $"{(int)span.TotalDays} days ago";
    }

    public static string Kills(Play p) => p.Ace ? "Ace" : p.Kills == 1 ? "1 kill" : $"{p.Kills} kills";

    /// <summary>How many plays since the last video, as the headline.</summary>
    public static string PlaysHeadline(int n) => n switch
    {
        0 => "No new plays yet.",
        1 => "1 new play.",
        _ => $"{n} new plays.",
    };
}
