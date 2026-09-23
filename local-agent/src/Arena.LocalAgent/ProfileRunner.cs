using System.Diagnostics;
using System.Text.Json;

namespace Arena.LocalAgent;

internal sealed class NamedProfile
{
    public required string Name { get; init; }
    public required string Executable { get; init; }
    public required IReadOnlyList<string> Arguments { get; init; }
    public required string ExecutableSha256 { get; init; }
    public required int TimeoutMs { get; init; }
    public required int StdoutLimit { get; init; }
}

internal sealed class ChildRun
{
    public required string State { get; init; }
    public required string Reason { get; init; }
    public required string Output { get; init; }
}

internal static class ProfileRunner
{
    public static bool TryLoad(string profilePath, string expectedFileSha, out NamedProfile? profile, out string reason)
    {
        profile = null;
        reason = "";
        if (!File.Exists(profilePath))
        {
            reason = "profile-missing";
            return false;
        }
        var fileBytes = File.ReadAllBytes(profilePath);
        if (!string.Equals(Hashing.Sha256(fileBytes), Hashing.NormalizeSha(expectedFileSha), StringComparison.Ordinal))
        {
            reason = "profile-mismatch";
            return false;
        }
        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(fileBytes);
        }
        catch (JsonException)
        {
            reason = "profile-mismatch";
            return false;
        }
        using (doc)
        {
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                reason = "profile-mismatch";
                return false;
            }
            var allowed = new[] { "name", "executable", "arguments", "executable_sha256", "timeout_ms", "stdout_limit" };
            foreach (var prop in root.EnumerateObject())
            {
                if (Array.IndexOf(allowed, prop.Name) < 0)
                {
                    reason = "profile-mismatch";
                    return false;
                }
            }
            foreach (var name in allowed)
            {
                if (!root.TryGetProperty(name, out _))
                {
                    reason = "profile-mismatch";
                    return false;
                }
            }
            var profileName = root.GetProperty("name").GetString() ?? "";
            if (profileName != "test-profile")
            {
                reason = "profile-mismatch";
                return false;
            }
            var executable = root.GetProperty("executable").GetString() ?? "";
            if (!Path.IsPathRooted(executable) || !File.Exists(executable))
            {
                reason = "profile-mismatch";
                return false;
            }
            var expectedExe = root.GetProperty("executable_sha256").GetString() ?? "";
            if (!Hashing.IsSha256(expectedExe) || !string.Equals(Hashing.Sha256File(executable), Hashing.NormalizeSha(expectedExe), StringComparison.Ordinal))
            {
                reason = "profile-mismatch";
                return false;
            }
            if (!root.GetProperty("timeout_ms").TryGetInt32(out var timeout) || timeout < 1 || timeout > 30_000)
            {
                reason = "profile-mismatch";
                return false;
            }
            if (!root.GetProperty("stdout_limit").TryGetInt32(out var limit) || limit < 1 || limit > 1_048_576)
            {
                reason = "profile-mismatch";
                return false;
            }
            if (root.GetProperty("arguments").ValueKind != JsonValueKind.Array)
            {
                reason = "profile-mismatch";
                return false;
            }
            var args = new List<string>();
            foreach (var item in root.GetProperty("arguments").EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.String)
                {
                    reason = "profile-mismatch";
                    return false;
                }
                args.Add(item.GetString() ?? "");
            }
            profile = new NamedProfile
            {
                Name = profileName,
                Executable = Path.GetFullPath(executable),
                Arguments = args,
                ExecutableSha256 = Hashing.NormalizeSha(expectedExe),
                TimeoutMs = timeout,
                StdoutLimit = limit
            };
            return true;
        }
    }

    public static ChildRun Run(NamedProfile profile, string workingDirectory)
    {
        var psi = new ProcessStartInfo
        {
            FileName = profile.Executable,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        foreach (var arg in profile.Arguments)
        {
            psi.ArgumentList.Add(arg);
        }
        var names = new List<string>();
        foreach (System.Collections.DictionaryEntry entry in psi.EnvironmentVariables)
        {
            names.Add((string)entry.Key);
        }
        try
        {
            foreach (var name in names)
            {
                psi.EnvironmentVariables.Remove(name);
            }
        }
        catch
        {
            return Fail("profile-mismatch");
        }
        if (psi.EnvironmentVariables.Count != 0)
        {
            return Fail("profile-mismatch");
        }
        using var proc = new Process { StartInfo = psi };
        try
        {
            if (!proc.Start())
            {
                return Fail("profile-mismatch");
            }
        }
        catch
        {
            return Fail("profile-mismatch");
        }
        DateTime started;
        try
        {
            started = proc.StartTime.Kind == DateTimeKind.Utc ? proc.StartTime : proc.StartTime.ToUniversalTime();
        }
        catch
        {
            started = DateTime.UtcNow;
        }
        var identity = new ChildIdentity(proc.Id, profile.Executable, started);
        var limitFlag = new LimitFlag();
        var stdout = new MemoryStream();
        var stderr = new MemoryStream();
        var outTask = Task.Run(() => CopyLimited(proc.StandardOutput.BaseStream, stdout, profile.StdoutLimit, limitFlag, proc, identity));
        var errTask = Task.Run(() => CopyLimited(proc.StandardError.BaseStream, stderr, profile.StdoutLimit, limitFlag, proc, identity));
        var exited = proc.WaitForExit(profile.TimeoutMs);
        if (!exited)
        {
            TryKill(proc, identity);
            try { proc.WaitForExit(2000); } catch { }
            return Fail("timeout");
        }
        try
        {
            Task.WaitAll(new[] { outTask, errTask }, 2000);
        }
        catch
        {
        }
        if (limitFlag.Hit == 1)
        {
            TryKill(proc, identity);
            return Fail("stdout-limit");
        }
        try
        {
            if (!proc.HasExited || proc.ExitCode != 0)
            {
                return Fail("exit-code");
            }
        }
        catch
        {
            return Fail("exit-code");
        }
        var text = Utf8.NoBom.GetString(stdout.ToArray());
        if (text.Length > profile.StdoutLimit)
        {
            text = text.Substring(0, profile.StdoutLimit);
        }
        return new ChildRun { State = "COMPLETED", Reason = "", Output = text };
    }

    private static void CopyLimited(Stream source, Stream dest, int limit, LimitFlag flag, Process proc, ChildIdentity identity)
    {
        var buffer = new byte[1024];
        var total = 0;
        while (true)
        {
            int read;
            try
            {
                read = source.Read(buffer, 0, buffer.Length);
            }
            catch
            {
                return;
            }
            if (read <= 0)
            {
                return;
            }
            var room = limit - total;
            if (room <= 0)
            {
                Interlocked.Exchange(ref flag.Hit, 1);
                TryKill(proc, identity);
                return;
            }
            var take = Math.Min(room, read);
            dest.Write(buffer, 0, take);
            total += take;
            if (take < read)
            {
                Interlocked.Exchange(ref flag.Hit, 1);
                TryKill(proc, identity);
                return;
            }
        }
    }

    private static void TryKill(Process proc, ChildIdentity identity)
    {
        try
        {
            if (proc.HasExited)
            {
                return;
            }
            if (proc.Id != identity.Pid)
            {
                return;
            }
            DateTime started;
            try
            {
                started = proc.StartTime.Kind == DateTimeKind.Utc ? proc.StartTime : proc.StartTime.ToUniversalTime();
            }
            catch
            {
                return;
            }
            if (Math.Abs((started - identity.StartedUtc).TotalSeconds) > 2)
            {
                return;
            }
            if (!string.Equals(identity.Executable, proc.StartInfo.FileName, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))
            {
                return;
            }
            proc.Kill(entireProcessTree: true);
        }
        catch
        {
        }
    }

    private static ChildRun Fail(string reason)
    {
        return new ChildRun { State = "FAILED", Reason = reason, Output = "" };
    }

    private sealed record ChildIdentity(int Pid, string Executable, DateTime StartedUtc);

    private sealed class LimitFlag
    {
        public int Hit;
    }
}
