using Microsoft.UI.Xaml;

namespace Reroll.App;

public partial class App : Application
{
    MainWindow? _window;

    public App() => InitializeComponent();

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window = new MainWindow(Options.Parse(Environment.GetCommandLineArgs().Skip(1).ToArray()));
        _window.Activate();
    }
}

/// <summary>Command-line options. Normal use has none; the build uses --screenshot to check the
/// screens on a Windows machine (--demo shows sample plays without running the engine).</summary>
public sealed record Options(string? Screenshot, string? State, bool Demo, string? Video)
{
    public static Options Parse(string[] args)
    {
        string? Value(string name)
        {
            var i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }
        return new Options(Value("--screenshot"), Value("--state"), args.Contains("--demo"), Value("--video"));
    }
}
