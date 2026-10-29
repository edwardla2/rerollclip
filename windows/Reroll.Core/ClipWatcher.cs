namespace Reroll.Core;

/// <summary>Watches the Medal folder (and its per-game subfolders) and raises ClipReady once a new
/// clip has stopped growing: Medal writes a clip over a few seconds, and reading it before it's
/// finished would analyse half a clip.</summary>
public sealed class ClipWatcher : IDisposable
{
    readonly FileSystemWatcher _watcher;
    readonly Dictionary<string, (long Size, DateTime Seen)> _pending = new(StringComparer.OrdinalIgnoreCase);
    readonly Timer _timer;
    readonly TimeSpan _settle;
    readonly object _lock = new();

    public event Action<string>? ClipReady;

    public ClipWatcher(string folder, TimeSpan? settle = null, TimeSpan? poll = null)
    {
        _settle = settle ?? TimeSpan.FromSeconds(3);
        _watcher = new FileSystemWatcher(folder)
        {
            IncludeSubdirectories = true,
            NotifyFilter = NotifyFilters.FileName | NotifyFilters.Size | NotifyFilters.LastWrite,
            InternalBufferSize = 64 * 1024,
        };
        _watcher.Created += (_, e) => Touch(e.FullPath);
        _watcher.Changed += (_, e) => Touch(e.FullPath);
        _watcher.Renamed += (_, e) => Touch(e.FullPath);
        var every = poll ?? TimeSpan.FromSeconds(1);
        _timer = new Timer(_ => Check(), null, every, every);
        _watcher.EnableRaisingEvents = true;
    }

    void Touch(string path)
    {
        if (!MedalLocator.IsVideo(path) || IsOurs(path))
            return;
        lock (_lock)
            _pending[path] = (-1, DateTime.UtcNow);
    }

    /// <summary>Reroll's own outputs and work files never count as new clips.</summary>
    static bool IsOurs(string path) =>
        path.Contains("(Reroll)", StringComparison.OrdinalIgnoreCase)
        || path.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
               .Any(p => p.Equals(".reroll", StringComparison.OrdinalIgnoreCase));

    void Check()
    {
        var ready = new List<string>();
        lock (_lock)
        {
            foreach (var (path, (size, seen)) in _pending.ToList())
            {
                long now;
                try { now = new FileInfo(path).Length; }
                catch (IOException) { continue; }
                catch (UnauthorizedAccessException) { continue; }
                if (!File.Exists(path)) { _pending.Remove(path); continue; }
                if (now != size) { _pending[path] = (now, DateTime.UtcNow); continue; }
                if (DateTime.UtcNow - seen >= _settle && now > 0 && CanOpen(path))
                {
                    _pending.Remove(path);
                    ready.Add(path);
                }
            }
        }
        foreach (var p in ready)
            ClipReady?.Invoke(p);
    }

    /// <summary>Medal still has the file open while writing it.</summary>
    static bool CanOpen(string path)
    {
        try
        {
            using var _ = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            return true;
        }
        catch (IOException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
    }

    public void Dispose()
    {
        _watcher.Dispose();
        _timer.Dispose();
    }
}
