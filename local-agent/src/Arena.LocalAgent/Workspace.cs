using System.Text;

namespace Arena.LocalAgent;

internal sealed class BoundWorkspace
{
    public required string Root { get; init; }
    public int WriteCount { get; private set; }

    public bool TryResolve(string relative, out string full, out string reason)
    {
        full = "";
        reason = "";
        if (!PathRules.TryNormalize(relative, out var parts, out reason))
        {
            return false;
        }
        var current = Root;
        if (IsReparse(current))
        {
            reason = "path-escape";
            return false;
        }
        for (var i = 0; i < parts.Count; i++)
        {
            current = Path.Combine(current, parts[i]);
            if (IsReparse(current))
            {
                reason = "path-escape";
                return false;
            }
            if (i < parts.Count - 1 && File.Exists(current) && !Directory.Exists(current))
            {
                reason = "path-not-directory";
                return false;
            }
        }
        var fullPath = Path.GetFullPath(current);
        if (!IsUnder(Root, fullPath))
        {
            reason = "path-escape";
            return false;
        }
        full = fullPath;
        return true;
    }

    public byte[]? Read(string full, out string reason)
    {
        reason = "";
        if (IsReparse(full) || !File.Exists(full))
        {
            reason = File.Exists(full) ? "path-escape" : "not-found";
            return null;
        }
        return File.ReadAllBytes(full);
    }

    public byte[]? ReadLimited(string full, int maxBytes, out string reason)
    {
        reason = "";
        if (IsReparse(full) || !File.Exists(full))
        {
            reason = File.Exists(full) ? "path-escape" : "not-found";
            return null;
        }
        using var stream = new FileStream(full, FileMode.Open, FileAccess.Read, FileShare.Read);
        var cap = maxBytes < 0 ? 0 : maxBytes;
        var buffer = new byte[Math.Min(cap + 1L, 1024 * 1024)];
        using var body = new MemoryStream();
        var total = 0;
        while (true)
        {
            var room = cap + 1 - total;
            if (room <= 0)
            {
                reason = "read-limit";
                return null;
            }
            var n = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, room));
            if (n <= 0)
            {
                break;
            }
            total += n;
            if (total > cap)
            {
                reason = "read-limit";
                return null;
            }
            body.Write(buffer, 0, n);
        }
        return body.ToArray();
    }

    public bool TryWrite(string full, byte[] bytes, out string reason)
    {
        reason = "";
        var parent = Path.GetDirectoryName(full);
        if (string.IsNullOrEmpty(parent) || !IsUnder(Root, parent) && !PathsEqual(parent, Root))
        {
            reason = "path-escape";
            return false;
        }
        if (!EnsureParent(parent, out reason))
        {
            return false;
        }
        var tmp = Path.Combine(parent, "." + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            using (var stream = new FileStream(tmp, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.None))
            {
                stream.Write(bytes, 0, bytes.Length);
                try
                {
                    stream.Flush(true);
                }
                catch (IOException)
                {
                    stream.Flush();
                }
                catch (UnauthorizedAccessException)
                {
                    stream.Flush();
                }
            }
            if (File.Exists(full))
            {
                File.Replace(tmp, full, null);
            }
            else
            {
                File.Move(tmp, full);
            }
            WriteCount++;
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            reason = "conflict-exists";
            TryDelete(tmp);
            return false;
        }
        finally
        {
            if (File.Exists(tmp))
            {
                TryDelete(tmp);
            }
        }
    }

    private bool EnsureParent(string parent, out string reason)
    {
        reason = "";
        var relative = Path.GetRelativePath(Root, parent);
        if (relative == ".")
        {
            return true;
        }
        var walk = Root;
        foreach (var part in relative.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar))
        {
            if (part.Length == 0 || part == ".")
            {
                continue;
            }
            walk = Path.Combine(walk, part);
            if (IsReparse(walk))
            {
                reason = "path-escape";
                return false;
            }
            if (File.Exists(walk) && !Directory.Exists(walk))
            {
                reason = "path-not-directory";
                return false;
            }
            if (!Directory.Exists(walk))
            {
                try
                {
                    Directory.CreateDirectory(walk);
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    reason = "io-failed";
                    return false;
                }
            }
        }
        return true;
    }

    private static bool IsReparse(string path)
    {
        if (!File.Exists(path) && !Directory.Exists(path))
        {
            return false;
        }
        return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch
        {
        }
    }

    public static bool IsUnder(string root, string child)
    {
        return PathsEqual(root, child) || child.StartsWith(WithSep(root), PathComparison());
    }

    public static bool PathsEqual(string left, string right)
    {
        return string.Equals(Trim(left), Trim(right), PathComparison());
    }

    private static string WithSep(string path)
    {
        return Trim(path) + Path.DirectorySeparatorChar;
    }

    private static string Trim(string path)
    {
        return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static StringComparison PathComparison()
    {
        return OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
    }
}

internal static class PathRules
{
    private static readonly HashSet<string> Devices = new(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"
    };

    public static bool TryNormalize(string relative, out List<string> parts, out string reason)
    {
        parts = new List<string>();
        reason = "";
        if (string.IsNullOrWhiteSpace(relative) || relative.Length > 240)
        {
            reason = "path-escape";
            return false;
        }
        if (relative.Contains(':') || relative.Contains('*') || relative.Contains('?') || relative.Contains('"')
            || relative.Contains('<') || relative.Contains('>') || relative.Contains('|'))
        {
            reason = "path-escape";
            return false;
        }
        if (relative.StartsWith('/') || relative.StartsWith('\\') || relative.Contains("//") || relative.Contains("\\\\"))
        {
            reason = "path-escape";
            return false;
        }
        var split = relative.Split('/', '\\');
        foreach (var raw in split)
        {
            if (raw.Length == 0 || raw == "." || raw == "..")
            {
                reason = "path-escape";
                return false;
            }
            if (raw.EndsWith(' ') || raw.EndsWith('.'))
            {
                reason = "path-escape";
                return false;
            }
            foreach (var ch in raw)
            {
                if (ch < 32)
                {
                    reason = "path-escape";
                    return false;
                }
            }
            var baseName = raw;
            var dot = raw.IndexOf('.');
            if (dot >= 0)
            {
                baseName = raw.Substring(0, dot);
            }
            if (Devices.Contains(baseName) || IsComOrLpt(baseName))
            {
                reason = "path-escape";
                return false;
            }
            parts.Add(raw);
        }
        return parts.Count > 0;
    }

    private static bool IsComOrLpt(string name)
    {
        if (name.Length != 4)
        {
            return false;
        }
        var prefix = name.Substring(0, 3);
        if (!prefix.Equals("COM", StringComparison.OrdinalIgnoreCase) && !prefix.Equals("LPT", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        return name[3] >= '1' && name[3] <= '9';
    }
}

internal static class Patcher
{
    public static bool TryApply(string fileText, string patchText, out string result, out string reason)
    {
        result = "";
        reason = "";
        if (patchText.Contains('\0') || patchText.Length > 1_000_000)
        {
            reason = "bad-patch";
            return false;
        }
        var patchLines = Split(patchText, out _);
        if (patchLines.Count == 0 || patchLines[0] != "ARENA-PATCH/1")
        {
            reason = "bad-patch";
            return false;
        }
        var fileLines = Split(fileText, out var endsWithNewline);
        var output = new List<string>();
        var cursor = 0;
        var any = false;
        var i = 1;
        while (i < patchLines.Count)
        {
            if (patchLines[i].Length == 0)
            {
                i++;
                continue;
            }
            if (patchLines[i] != "@@")
            {
                reason = "bad-patch";
                return false;
            }
            any = true;
            i++;
            var oldLines = new List<string>();
            var newLines = new List<string>();
            while (i < patchLines.Count && patchLines[i] != "@@")
            {
                var line = patchLines[i];
                if (line.StartsWith("diff ", StringComparison.Ordinal) || line.StartsWith("---", StringComparison.Ordinal) || line.StartsWith("+++", StringComparison.Ordinal))
                {
                    reason = "bad-patch";
                    return false;
                }
                if (line.Length == 0 || (line[0] != ' ' && line[0] != '-' && line[0] != '+'))
                {
                    reason = "bad-patch";
                    return false;
                }
                var body = line.Substring(1);
                if (line[0] == ' ')
                {
                    oldLines.Add(body);
                    newLines.Add(body);
                }
                else if (line[0] == '-')
                {
                    oldLines.Add(body);
                }
                else
                {
                    newLines.Add(body);
                }
                i++;
            }
            var found = IndexOf(fileLines, oldLines, cursor);
            if (found < 0)
            {
                reason = "patch-mismatch";
                return false;
            }
            for (var k = cursor; k < found; k++)
            {
                output.Add(fileLines[k]);
            }
            output.AddRange(newLines);
            cursor = found + oldLines.Count;
        }
        if (!any)
        {
            reason = "bad-patch";
            return false;
        }
        for (var k = cursor; k < fileLines.Count; k++)
        {
            output.Add(fileLines[k]);
        }
        result = string.Join("\n", output);
        if (endsWithNewline)
        {
            result += "\n";
        }
        return true;
    }

    private static int IndexOf(List<string> file, List<string> needle, int start)
    {
        if (needle.Count == 0)
        {
            return start;
        }
        for (var i = start; i <= file.Count - needle.Count; i++)
        {
            var match = true;
            for (var j = 0; j < needle.Count; j++)
            {
                if (file[i + j] != needle[j])
                {
                    match = false;
                    break;
                }
            }
            if (match)
            {
                return i;
            }
        }
        return -1;
    }

    private static List<string> Split(string text, out bool endsWithNewline)
    {
        endsWithNewline = text.EndsWith("\n", StringComparison.Ordinal);
        if (text.Length == 0)
        {
            return new List<string>();
        }
        var core = endsWithNewline ? text.Substring(0, text.Length - 1) : text;
        return new List<string>(core.Split('\n'));
    }
}

internal static class Utf8
{
    public static readonly Encoding NoBom = new UTF8Encoding(false);
    private static readonly Encoding Strict = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);

    public static bool TryDecode(byte[] bytes, out string text)
    {
        try
        {
            text = Strict.GetString(bytes);
            return true;
        }
        catch (DecoderFallbackException)
        {
            text = "";
            return false;
        }
    }
}
