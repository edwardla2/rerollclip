using System.Diagnostics;
using System.Runtime.InteropServices.WindowsRuntime;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media.Imaging;
using Reroll.Core;
using Windows.Graphics;
using Windows.Graphics.Imaging;
using Windows.Media.Core;
using Windows.Storage.Pickers;

namespace Reroll.App;

/// <summary>One row in "Your plays".</summary>
public sealed class PlayRow
{
    public int Face { get; init; }
    public string Title { get; init; } = "";
    public string Detail { get; init; } = "";
    public string Badge { get; init; } = "";
    public double Opacity { get; init; } = 1;
}

public sealed partial class MainWindow : Window
{
    readonly Options _options;
    readonly Settings _settings;
    readonly Engine _engine = Engine.Default();
    readonly SemaphoreSlim _engineLock = new(1, 1);     // one engine run at a time (they share the ledger)
    readonly DispatcherQueue _ui;
    ClipWatcher? _watcher;
    CancellationTokenSource? _making;
    IReadOnlyList<Play> _plays = [];
    string? _lastOutput;
    int _rescanQueued;

    public MainWindow(Options options)
    {
        _options = options;
        InitializeComponent();
        _ui = DispatcherQueue.GetForCurrentThread();
        _settings = options.Demo ? new Settings() : Settings.Load();

        Title = "Reroll";
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "reroll.ico"));
        AppWindow.Resize(new SizeInt32(1180, 760));
        if (AppWindow.Presenter is OverlappedPresenter p)
        {
            p.PreferredMinimumWidth = 900;
            p.PreferredMinimumHeight = 620;
        }
        Root.Loaded += async (_, _) => await StartAsync();
        Closed += (_, _) => { _watcher?.Dispose(); _making?.Cancel(); };
    }

    async Task StartAsync()
    {
        if (_options.Demo)
            ShowDemo();
        else
        {
            if (string.IsNullOrEmpty(_settings.MedalFolder) || !Directory.Exists(_settings.MedalFolder))
            {
                _settings.MedalFolder = MedalLocator.Find();
                if (_settings.MedalFolder is not null)
                    _settings.Save();
            }
            if (_settings.MedalFolder is null)
                Show(SetupPanel);
            else
                await WatchAsync(_settings.MedalFolder);
        }
        if (_options.Screenshot is { } shot)
            await ScreenshotAndExitAsync(shot);
    }

    // ------------------------------------------------------------ watching and listing plays

    async Task WatchAsync(string folder)
    {
        FolderText.Text = $"Medal folder   {folder}";
        _watcher?.Dispose();
        try
        {
            _watcher = new ClipWatcher(folder);
            _watcher.ClipReady += _ => _ui.TryEnqueue(async () => await RescanAsync());
        }
        catch (Exception e) when (e is ArgumentException or IOException or UnauthorizedAccessException)
        {
            ShowError($"Can't watch {folder}: {e.Message}");
        }
        Show(ReadyPanel);
        await RescanAsync();
    }

    async Task RescanAsync()
    {
        if (_settings.MedalFolder is not { } folder)
            return;
        // A burst of new clips needs one scan, not one each.
        if (Interlocked.Exchange(ref _rescanQueued, 1) == 1)
            return;
        await _engineLock.WaitAsync();
        Interlocked.Exchange(ref _rescanQueued, 0);
        try
        {
            if (_plays.Count == 0)
                Headline.Text = "Looking for your plays.";
            var progress = new Progress<EngineProgress>(p => MakeHint.Text = p.Item is { Length: > 0 } ? $"Checking {p.Item}" : "");
            var result = await Task.Run(() => _engine.ScanAsync(folder, progress));
            MakeHint.Text = "";
            ShowPlays(result.Plays);
            HideError();
        }
        catch (EngineException e)
        {
            ShowError(e.Message);
        }
        finally
        {
            _engineLock.Release();
        }
    }

    void ShowPlays(IReadOnlyList<Play> plays)
    {
        _plays = plays;
        var since = _settings.LastVideoAt;
        bool IsNew(Play p) => since is null || (p.SavedAt ?? 0) > since;
        var fresh = plays.Count(IsNew);
        PlayList.ItemsSource = plays.Select(p => new PlayRow
        {
            Face = Math.Clamp(p.Kills, 1, 6),
            Title = Format.Kills(p),
            Detail = $"{Path.GetFileNameWithoutExtension(p.Clip)} · {Format.Ago(p.SavedAt)}",
            Badge = IsNew(p) ? "NEW" : "",
            Opacity = IsNew(p) ? 1 : 0.45,
        }).ToList();
        CountText.Text = plays.Count == 1 ? "1 play" : $"{plays.Count} plays";
        EmptyPlays.Visibility = plays.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        Headline.Text = Format.PlaysHeadline(fresh);
        Subline.Text = fresh > 0
            ? "Reroll puts them into one vertical video, best play last. You add the song when you post."
            : plays.Count > 0
                ? "Everything here is already in a video. Make another anyway, or clip some more."
                : "Play with Medal running. Every clip with a kill in it shows up here.";
        MakeButton.IsEnabled = plays.Count > 0;
        MakeHint.Text = fresh > 0 ? $"About {EstimateMinutes(plays.Where(IsNew))} min on this PC" : "";
    }

    static int EstimateMinutes(IEnumerable<Play> plays)
    {
        // Measured: about 8 s of work per second of finished video on a 2-core machine; plays
        // come out at roughly a third of their clip length. Rounded up, never under 1.
        var seconds = plays.Take(5).Sum(p => (p.Duration ?? 30) / 3) * 8;
        return Math.Max(1, (int)Math.Ceiling(seconds / 60));
    }

    // ------------------------------------------------------------ making a video

    async void Make_Click(object sender, RoutedEventArgs e)
    {
        if (_settings.MedalFolder is not { } folder)
            return;
        HideError();
        var outDir = _settings.ResolvedOutputFolder;
        Directory.CreateDirectory(outDir);
        var output = Path.Combine(outDir, $"Reroll {DateTime.Now:yyyy-MM-dd HH-mm}.mp4");
        var hasNew = _plays.Any(p => _settings.LastVideoAt is null || (p.SavedAt ?? 0) > _settings.LastVideoAt);
        var since = hasNew ? _settings.LastVideoAt : null;

        _making = new CancellationTokenSource();
        SetProgress(new EngineProgress("analysing", 0, null));
        Show(WorkingPanel);
        await _engineLock.WaitAsync();
        try
        {
            var progress = new Progress<EngineProgress>(SetProgress);
            var token = _making.Token;
            var result = await Task.Run(() => _engine.MakeAsync(folder, output, since, progress, token));
            if (!result.Ok)
            {
                Show(ReadyPanel);
                ShowError(result.Message ?? "No plays to make a video from yet.");
                return;
            }
            _settings.LastVideoAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            _settings.Save();
            _lastOutput = result.Output;
            ShowDone(result.Output!, result.Plays?.Count ?? 0, result.Seconds ?? 0);
        }
        catch (OperationCanceledException)
        {
            Show(ReadyPanel);
        }
        catch (EngineException ex)
        {
            Show(ReadyPanel);
            ShowError(ex.Message);
        }
        finally
        {
            _engineLock.Release();
            _making = null;
        }
        ShowPlays(_plays);
    }

    void SetProgress(EngineProgress p)
    {
        StageText.Text = p.Label;
        PercentText.Text = $"{(int)(p.Overall * 100)}%";
        var track = (ProgressFill.Parent as FrameworkElement)?.ActualWidth ?? 0;
        ProgressFill.Width = Math.Max(0, track * p.Overall);
    }

    void ShowDone(string output, int plays, double seconds)
    {
        DoneDetail.Text = $"{plays} plays, {(int)seconds / 60}:{(int)seconds % 60:00} long, game audio only. " +
                          $"Saved to {Path.GetDirectoryName(output)}.";
        if (File.Exists(output))
            Player.Source = MediaSource.CreateFromUri(new Uri(output));
        Show(DonePanel);
    }

    void Cancel_Click(object sender, RoutedEventArgs e) => _making?.Cancel();

    void Back_Click(object sender, RoutedEventArgs e)
    {
        Player.MediaPlayer?.Pause();
        Show(ReadyPanel);
    }

    void ShowInFolder_Click(object sender, RoutedEventArgs e)
    {
        if (_lastOutput is { } f && File.Exists(f))
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{f}\"") { UseShellExecute = true });
    }

    async void ChangeFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.VideosLibrary };
        picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
            return;
        _settings.MedalFolder = folder.Path;
        _settings.Save();
        _plays = [];
        await WatchAsync(folder.Path);
    }

    // ------------------------------------------------------------ panels and errors

    void Show(FrameworkElement panel)
    {
        foreach (var p in new FrameworkElement[] { SetupPanel, ReadyPanel, WorkingPanel, DonePanel })
            p.Visibility = p == panel ? Visibility.Visible : Visibility.Collapsed;
        ChangeFolderButton.IsEnabled = panel != WorkingPanel;
    }

    void ShowError(string message)
    {
        ErrorText.Text = message;
        ErrorBox.Visibility = Visibility.Visible;
    }

    void HideError() => ErrorBox.Visibility = Visibility.Collapsed;

    // ------------------------------------------------------------ build checks

    /// <summary>Sample plays for --demo: the screens without the engine or a Medal folder.</summary>
    void ShowDemo()
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        _settings.LastVideoAt = now - 3 * 3600;
        FolderText.Text = @"Medal folder   C:\Users\Edward\Videos\Medal\Clips";
        Show(ReadyPanel);
        ShowPlays([
            new Play("VALORANT_2026-10-28_21-14-02.mp4", "", 5, true, now - 600, 41, "high"),
            new Play("VALORANT_2026-10-28_21-02-47.mp4", "", 4, false, now - 1300, 34, "high"),
            new Play("VALORANT_2026-10-28_20-41-10.mp4", "", 3, false, now - 2600, 96, "high"),
            new Play("VALORANT_2026-10-27_22-30-55.mp4", "", 2, false, now - 26 * 3600, 29, "high"),
            new Play("VALORANT_2026-10-26_19-12-31.mp4", "", 1, false, now - 50 * 3600, 22, "high"),
        ]);
        switch (_options.State)
        {
            case "setup":
                FolderText.Text = "";
                Show(SetupPanel);
                break;
            case "working":
                Show(WorkingPanel);
                Root.UpdateLayout();
                SetProgress(new EngineProgress("cutting", 0.42, null));
                break;
            case "done":
                _lastOutput = _options.Video;
                ShowDone(_options.Video ?? "", 3, 101);
                break;
            case "error":
                ShowError("Can't read media C:\\...\\VALORANT_2026-10-28.mp4: moov atom not found");
                break;
        }
    }

    async Task ScreenshotAndExitAsync(string path)
    {
        await Task.Delay(1500);                 // fonts and layout settle
        try
        {
            var rtb = new RenderTargetBitmap();
            // --scale 2 renders the window at twice its size (sharp enough for a 1080p video).
            var k = _options.Scale ?? 1.0;
            if (k > 1)
                await rtb.RenderAsync(Root, (int)(Root.ActualWidth * k), (int)(Root.ActualHeight * k));
            else
                await rtb.RenderAsync(Root);
            var pixels = await rtb.GetPixelsAsync();
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
            using var stream = new Windows.Storage.Streams.InMemoryRandomAccessStream();
            var encoder = await BitmapEncoder.CreateAsync(BitmapEncoder.PngEncoderId, stream);
            var dpi = (float)(96 * Root.XamlRoot.RasterizationScale);
            encoder.SetPixelData(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied,
                                 (uint)rtb.PixelWidth, (uint)rtb.PixelHeight, dpi, dpi, pixels.ToArray());
            await encoder.FlushAsync();
            stream.Seek(0);
            var bytes = new byte[stream.Size];
            using (var reader = new Windows.Storage.Streams.DataReader(stream.GetInputStreamAt(0)))
            {
                await reader.LoadAsync((uint)stream.Size);
                reader.ReadBytes(bytes);
            }
            await File.WriteAllBytesAsync(path, bytes);
        }
        catch (Exception e)
        {
            await File.WriteAllTextAsync(path + ".error.txt", e.ToString());
        }
        Application.Current.Exit();
    }
}
