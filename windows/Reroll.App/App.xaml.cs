using Microsoft.UI.Xaml;

namespace Reroll.App;

public partial class App : Application
{
    MainWindow? _window;

    public App()
    {
        // Anything that escapes gets written down: %LOCALAPPDATA%\Reroll\crash.txt (and next to the
        // screenshot during build checks), so a crash on a tester's PC can be read afterwards.
        UnhandledException += (_, e) => CrashLog.Write(e.Exception);
        AppDomain.CurrentDomain.UnhandledException += (_, e) => CrashLog.Write(e.ExceptionObject as Exception);
        try
        {
            InitializeComponent();
        }
        catch (Exception e)
        {
            CrashLog.Write(e);
            throw;
        }
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            _window = new MainWindow(Options.Parse(Environment.GetCommandLineArgs().Skip(1).ToArray()));
            _window.Activate();
        }
        catch (Exception e)
        {
            CrashLog.Write(e);
            throw;
        }
    }
}

/// <summary>Command-line options. Normal use has none; the build uses --screenshot to check the
/// screens on a Windows machine (--demo shows sample plays without running the engine).</summary>
public sealed record Options(string? Screenshot, string? State, bool Demo, string? Video, double? Scale = null)
{
    public static Options Parse(string[] args)
    {
        string? Value(string name)
        {
            var i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }
        double? scale = null;
        if (double.TryParse(Value("--scale"), System.Globalization.NumberStyles.Float,
                            System.Globalization.CultureInfo.InvariantCulture, out var k))
            scale = k;
        return new Options(Value("--screenshot"), Value("--state"), args.Contains("--demo"), Value("--video"), scale);
    }
}

static class CrashLog
{
    public static void Write(Exception? e)
    {
        var text = $"{DateTime.Now:O}\n{e}\n";
        var targets = new List<string>
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Reroll", "crash.txt"),
        };
        if (Options.Parse(Environment.GetCommandLineArgs().Skip(1).ToArray()).Screenshot is { } shot)
            targets.Add(shot + ".error.txt");
        foreach (var t in targets)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(t))!);
                File.AppendAllText(t, text);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
