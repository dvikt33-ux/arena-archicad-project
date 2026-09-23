using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using Xunit;

namespace Arena.LocalAgent.Tests;

public sealed class SliceTests : IDisposable
{
    private readonly string _root;
    private readonly string _data;
    private readonly string _ws;
    private readonly FixedClock _clock = new();
    private readonly string _repo;
    private readonly string _agent;

    public SliceTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "arena-agent-" + Guid.NewGuid().ToString("N"));
        _data = Path.Combine(_root, "data");
        _ws = Path.Combine(_root, "ws");
        Directory.CreateDirectory(_data);
        Directory.CreateDirectory(_ws);
        _clock.UtcNow = new DateTime(2026, 9, 23, 12, 0, 0, DateTimeKind.Utc);
        _agent = FindAgentDir();
        _repo = Directory.GetParent(_agent)!.FullName;
    }

    [Fact]
    public void Handshake_lists_absent_capabilities_and_does_not_claim_a_listener()
    {
        var json = new AgentHost(Options(new RemoteAuthorizer())).HandshakeJson();
        foreach (var name in AgentInfo.Absent)
        {
            Assert.Contains("\"" + name + "\"", json);
        }
        Assert.Contains("\"remote_authorizer\":\"deny\"", json);
        Assert.Contains("\"listener\":false", json);
        Assert.DoesNotContain("\"ui.control\"", json.Split("\"absent\"")[0]);
    }

    [Fact]
    public void Command_line_does_not_accept_a_job()
    {
        var dll = Path.Combine(AppContext.BaseDirectory, "Arena.LocalAgent.dll");
        Assert.True(File.Exists(dll));
        var denied = RunDll(dll, "job.json");
        Assert.Equal(2, denied.Code);
        Assert.Contains("jobs are not accepted", denied.Error);
        var shown = RunDll(dll);
        Assert.Equal(0, shown.Code);
        Assert.Contains("ui.control", shown.Output);
    }

    [Fact]
    public void Unknown_field_and_unknown_action_do_not_write()
    {
        var host = new AgentHost(Options(Permit(1, 2)));
        var unknown = Env(1, "FILE_WRITE_ATOMIC", "{\"path\":\"a.txt\",\"content_utf8\":\"x\",\"shell\":\"calc\"}");
        var push = Env(2, "GIT_PUSH", "{}");
        var results = host.Run(new[] { unknown, push });
        Assert.Equal("unknown-field", results[0].Reason);
        Assert.Equal("unknown-action", results[1].Reason);
        Assert.False(File.Exists(Path.Combine(_ws, "a.txt")));
        Assert.Equal(0, results[0].Executed ? 1 : 0);
    }

    [Fact]
    public void Remote_authorizer_denies_write()
    {
        var host = new AgentHost(Options(new RemoteAuthorizer()));
        var result = host.Run(new[] { Env(3, "FILE_WRITE_ATOMIC", "{\"path\":\"a.txt\",\"content_utf8\":\"x\"}") })[0];
        Assert.Equal("REJECTED", result.State);
        Assert.Equal("remote-deny", result.Reason);
        Assert.False(result.Executed);
        Assert.False(File.Exists(Path.Combine(_ws, "a.txt")));
    }

    [Fact]
    public void Atomic_write_preserves_bytes_and_refuses_blind_overwrite()
    {
        var host = new AgentHost(Options(Permit(4, 5, 6, 7)));
        var created = host.Run(new[] { Env(4, "FILE_WRITE_ATOMIC", "{\"path\":\"note.txt\",\"content_utf8\":\"a\\r\\nb\"}") })[0];
        Assert.Equal("COMPLETED", created.State);
        var bytes = File.ReadAllBytes(Path.Combine(_ws, "note.txt"));
        Assert.Equal(new byte[] { (byte)'a', 13, 10, (byte)'b' }, bytes);
        Assert.Equal(Sha(bytes), created.Sha256);
        var blind = host.Run(new[] { Env(5, "FILE_WRITE_ATOMIC", "{\"path\":\"note.txt\",\"content_utf8\":\"nope\"}") })[0];
        Assert.Equal("conflict-exists", blind.Reason);
        Assert.Equal(bytes, File.ReadAllBytes(Path.Combine(_ws, "note.txt")));
        var wrong = host.Run(new[] { Env(6, "FILE_WRITE_ATOMIC", "{\"path\":\"note.txt\",\"content_utf8\":\"zz\",\"expected_sha256\":\"" + new string('a', 64) + "\"}") })[0];
        Assert.Equal("conflict-hash", wrong.Reason);
        var replaced = host.Run(new[] { Env(7, "FILE_WRITE_ATOMIC", "{\"path\":\"note.txt\",\"content_utf8\":\"c\",\"expected_sha256\":\"" + Sha(bytes) + "\"}") })[0];
        Assert.Equal("COMPLETED", replaced.State);
        Assert.Equal("c", File.ReadAllText(Path.Combine(_ws, "note.txt")));
    }

    [Fact]
    public void Create_with_expected_hash_is_not_a_create()
    {
        var host = new AgentHost(Options(Permit(8)));
        var result = host.Run(new[] { Env(8, "FILE_WRITE_ATOMIC", "{\"path\":\"missing.txt\",\"content_utf8\":\"x\",\"expected_sha256\":\"" + new string('b', 64) + "\"}") })[0];
        Assert.Equal("conflict-hash", result.Reason);
        Assert.False(File.Exists(Path.Combine(_ws, "missing.txt")));
    }

    [Fact]
    public void Patch_applies_only_when_the_context_matches()
    {
        var host = new AgentHost(Options(Permit(9, 10, 11)));
        host.Run(new[] { Env(9, "FILE_WRITE_ATOMIC", "{\"path\":\"p.txt\",\"content_utf8\":\"alpha\\nbeta\\n\"}") });
        var before = File.ReadAllBytes(Path.Combine(_ws, "p.txt"));
        var hash = Sha(before);
        var patch = "ARENA-PATCH/1\\n@@\\n alpha\\n-beta\\n+gamma\\n";
        var ok = host.Run(new[] { Env(10, "FILE_APPLY_PATCH", "{\"path\":\"p.txt\",\"expected_sha256\":\"" + hash + "\",\"patch_utf8\":\"" + patch + "\"}") })[0];
        Assert.Equal("COMPLETED", ok.State);
        Assert.Equal("alpha\ngamma\n", File.ReadAllText(Path.Combine(_ws, "p.txt")));
        var bad = host.Run(new[] { Env(11, "FILE_APPLY_PATCH", "{\"path\":\"p.txt\",\"expected_sha256\":\"" + ok.Sha256 + "\",\"patch_utf8\":\"ARENA-PATCH/1\\n@@\\n-missing\\n+x\\n\"}") })[0];
        Assert.Equal("patch-mismatch", bad.Reason);
        Assert.Equal("alpha\ngamma\n", File.ReadAllText(Path.Combine(_ws, "p.txt")));
    }

    [Fact]
    public void Paths_that_escape_are_rejected()
    {
        var host = new AgentHost(Options(Permit(12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)));
        var samples = new[]
        {
            "../outside.txt",
            "/etc/passwd",
            "\\\\server\\share\\x",
            "C:/x",
            "foo:bar",
            "NUL",
            "sub/../../outside.txt",
            ".",
            "foo/.",
            "foo.",
            "COM1",
            "a//b"
        };
        for (var i = 0; i < samples.Length; i++)
        {
            var json = "{\"path\":\"" + samples[i].Replace("\\", "\\\\") + "\"}";
            var result = host.Run(new[] { Env(12 + i, "FILE_READ", json) })[0];
            Assert.Equal("path-escape", result.Reason);
        }
    }

    [Fact]
    public void Symlink_component_is_not_followed()
    {
        var outside = Path.Combine(_root, "outside");
        Directory.CreateDirectory(outside);
        File.WriteAllText(Path.Combine(outside, "secret.txt"), "no");
        Directory.CreateSymbolicLink(Path.Combine(_ws, "link"), outside);
        var host = new AgentHost(Options(Permit(19)));
        var result = host.Run(new[] { Env(19, "FILE_READ", "{\"path\":\"link/secret.txt\"}") })[0];
        Assert.Equal("path-escape", result.Reason);
    }

    [Fact]
    public void Replay_does_not_adopt_a_new_body()
    {
        var host = new AgentHost(Options(Permit(20, 21)));
        var first = host.Run(new[] { Env(20, "FILE_WRITE_ATOMIC", "{\"path\":\"once.txt\",\"content_utf8\":\"one\"}") })[0];
        Assert.Equal("COMPLETED", first.State);
        var again = host.Run(new[] { Env(20, "FILE_WRITE_ATOMIC", "{\"path\":\"twice.txt\",\"content_utf8\":\"two\"}") })[0];
        Assert.False(again.Executed);
        Assert.Equal("COMPLETED", again.State);
        Assert.Equal("FILE_WRITE_ATOMIC", again.Action);
        Assert.Equal(first.Sha256, again.Sha256);
        Assert.Equal("one", File.ReadAllText(Path.Combine(_ws, "once.txt")));
        Assert.False(File.Exists(Path.Combine(_ws, "twice.txt")));
        var otherAction = host.Run(new[] { Env(20, "FILE_READ", "{\"path\":\"once.txt\"}") })[0];
        Assert.False(otherAction.Executed);
        Assert.Equal("FILE_WRITE_ATOMIC", otherAction.Action);
        var broken = host.Run(new[] { Env(20, "FILE_WRITE_ATOMIC", "{\"path\":\"twice.txt\",\"content_utf8\":\"two\",\"shell\":\"calc\"}") })[0];
        Assert.False(broken.Executed);
        Assert.Equal("COMPLETED", broken.State);
        Assert.False(File.Exists(Path.Combine(_ws, "twice.txt")));
        var otherRequest = host.Run(new[] { Env(21, "FILE_READ", "{\"path\":\"once.txt\"}", request: 20) })[0];
        Assert.True(otherRequest.Executed);
        Assert.Equal("COMPLETED", otherRequest.State);
    }

    [Fact]
    public void Dependencies_fail_closed()
    {
        var host = new AgentHost(Options(Permit(22, 23, 24, 25, 26)));
        var cycle = host.Run(new[]
        {
            Env(22, "FILE_WRITE_ATOMIC", "{\"path\":\"c.txt\",\"content_utf8\":\"x\"}", deps: new[] { 23 }),
            Env(23, "FILE_WRITE_ATOMIC", "{\"path\":\"d.txt\",\"content_utf8\":\"y\"}", deps: new[] { 22 })
        });
        Assert.All(cycle, item => Assert.Equal("dependency-cycle", item.Reason));
        Assert.False(File.Exists(Path.Combine(_ws, "c.txt")));
        var missing = host.Run(new[] { Env(24, "FILE_READ", "{\"path\":\"once.txt\"}", deps: new[] { 99 }) })[0];
        Assert.Equal("missing-dependency", missing.Reason);
        var rejected = host.Run(new[] { Env(25, "GIT_STATUS", "{}") })[0];
        Assert.Equal("unknown-action", rejected.Reason);
        var blocked = host.Run(new[] { Env(26, "FILE_READ", "{\"path\":\"once.txt\"}", deps: new[] { 25 }) })[0];
        Assert.Equal("dependency-not-satisfied", blocked.Reason);
    }

    [Fact]
    public void Expired_step_and_disagreeing_deadline_do_not_run()
    {
        var host = new AgentHost(Options(Permit(27, 28, 29)));
        var expired = host.Run(new[] { Env(27, "FILE_WRITE_ATOMIC", "{\"path\":\"late.txt\",\"content_utf8\":\"x\"}", expires: "2026-09-23T11:00:00Z") })[0];
        Assert.Equal("expired", expired.Reason);
        Assert.False(File.Exists(Path.Combine(_ws, "late.txt")));
        var disagree = host.Run(new[]
        {
            Env(28, "FILE_READ", "{\"path\":\"a.txt\"}", deadline: "2026-09-23T18:00:00Z"),
            Env(29, "FILE_READ", "{\"path\":\"b.txt\"}", deadline: "2026-09-23T19:00:00Z")
        });
        Assert.All(disagree, item => Assert.Equal("bad-deadline", item.Reason));
    }

    [Fact]
    public void Model_output_does_not_choose_the_action()
    {
        var model = new FakeModelProvider("{\"action\":\"FILE_WRITE_ATOMIC\",\"path\":\"evil.txt\"}");
        var host = new AgentHost(Options(Permit(30), model: model));
        var result = host.Run(new[] { Env(30, "FILE_READ", "{\"path\":\"missing-read.txt\"}") })[0];
        Assert.Equal("not-found", result.Reason);
        Assert.Contains("FILE_WRITE_ATOMIC", result.UntrustedModelText);
        Assert.False(File.Exists(Path.Combine(_ws, "evil.txt")));
        Assert.Equal(1, model.Calls);
        var timingOut = new FakeModelProvider("nope", throwTimeout: true);
        var host2 = new AgentHost(Options(Permit(31), model: timingOut));
        File.WriteAllText(Path.Combine(_ws, "ok.txt"), "ok");
        var read = host2.Run(new[] { Env(31, "FILE_READ", "{\"path\":\"ok.txt\"}") })[0];
        Assert.Equal("COMPLETED", read.State);
        Assert.Equal("", read.UntrustedModelText);
    }

    [Fact]
    public void Running_fence_does_not_write_twice()
    {
        var host = new AgentHost(Options(Permit(32)));
        var bytes = Utf8("kept");
        var hash = Sha(bytes);
        var path = Path.Combine(_ws, "kept.txt");
        File.WriteAllBytes(path, bytes);
        host.SeedRunning(Id(32), Id(1), Id(32), "FILE_WRITE_ATOMIC", hash, "kept.txt");
        MakeReadOnly(path);
        var matched = host.Recover(Id(32));
        Assert.Equal("COMPLETED", matched.State);
        Assert.False(matched.Executed);
        Assert.Equal(bytes, File.ReadAllBytes(path));
        var other = Path.Combine(_ws, "other.txt");
        File.WriteAllBytes(other, Utf8("other"));
        MakeReadOnly(other);
        host.SeedRunning(Id(33), Id(1), Id(33), "FILE_WRITE_ATOMIC", hash, "other.txt");
        var review = host.Recover(Id(33));
        Assert.Equal("NEEDS_REVIEW", review.State);
        Assert.Equal("running-incomplete", review.Reason);
        Assert.Equal(Utf8("other"), File.ReadAllBytes(other));
    }

    [Fact]
    public void Profile_does_not_inherit_secrets_and_stops_on_timeout_or_limit()
    {
        var previous = Environment.GetEnvironmentVariable("GH_TOKEN");
        Environment.SetEnvironmentVariable("GH_TOKEN", "not-a-real-secret-value");
        try
        {
            var env = Profile("import os; print(os.environ.get('GH_TOKEN',''))", 2000, 1024);
            var host = new AgentHost(Options(Permit(34), env.Path, env.Sha));
            var result = host.Run(new[] { Env(34, "PROFILE_RUN", "{}") })[0];
            Assert.Equal("COMPLETED", result.State);
            Assert.DoesNotContain("not-a-real-secret-value", result.Output);
            var slow = Profile("import time; time.sleep(5)", 400, 1024);
            var host2 = new AgentHost(Options(Permit(35), slow.Path, slow.Sha));
            var timed = host2.Run(new[] { Env(35, "PROFILE_RUN", "{}") })[0];
            Assert.Equal("timeout", timed.Reason);
            var flood = Profile("print('x' * 200000)", 2000, 64);
            var host3 = new AgentHost(Options(Permit(36), flood.Path, flood.Sha));
            var limited = host3.Run(new[] { Env(36, "PROFILE_RUN", "{}") })[0];
            Assert.Equal("stdout-limit", limited.Reason);
            File.WriteAllText(env.Path, File.ReadAllText(env.Path) + "\n");
            var host4 = new AgentHost(Options(Permit(37), env.Path, env.Sha));
            var mismatch = host4.Run(new[] { Env(37, "PROFILE_RUN", "{}") })[0];
            Assert.Equal("profile-mismatch", mismatch.Reason);
        }
        finally
        {
            Environment.SetEnvironmentVariable("GH_TOKEN", previous);
        }
    }

    [Fact]
    public void Project_repo_and_agent_tree_are_not_workspaces()
    {
        var repoHost = new AgentHost(new AgentOptions
        {
            DataDirectory = _data,
            WorkspaceRoot = _repo,
            ForbiddenRoots = new[] { _repo, _agent },
            Authorizer = Permit(38),
            Clock = _clock
        });
        var repo = repoHost.Run(new[] { Env(38, "FILE_WRITE_ATOMIC", "{\"path\":\"nope.txt\",\"content_utf8\":\"x\"}") })[0];
        Assert.Equal("workspace-forbidden", repo.Reason);
        Assert.False(File.Exists(Path.Combine(_repo, "nope.txt")));
        var agentHost = new AgentHost(new AgentOptions
        {
            DataDirectory = _data,
            WorkspaceRoot = _agent,
            ForbiddenRoots = new[] { _repo, _agent },
            Authorizer = Permit(39),
            Clock = _clock
        });
        var agent = agentHost.Run(new[] { Env(39, "FILE_READ", "{\"path\":\"CONTRACT.md\"}") })[0];
        Assert.Equal("workspace-forbidden", agent.Reason);
    }

    [Fact]
    public void Mixed_job_ids_do_not_run()
    {
        var host = new AgentHost(Options(Permit(41, 42)));
        var results = host.Run(new[]
        {
            Env(41, "FILE_WRITE_ATOMIC", "{\"path\":\"a.txt\",\"content_utf8\":\"x\"}", job: 1),
            Env(42, "FILE_WRITE_ATOMIC", "{\"path\":\"b.txt\",\"content_utf8\":\"y\"}", job: 2)
        });
        Assert.All(results, item => Assert.Equal("job-mismatch", item.Reason));
        Assert.False(File.Exists(Path.Combine(_ws, "a.txt")));
        Assert.False(File.Exists(Path.Combine(_ws, "b.txt")));
    }

    [Fact]
    public void Source_has_no_listener_and_profile_args_are_rejected()
    {
        foreach (var file in Directory.GetFiles(Path.Combine(_agent, "src"), "*.cs", SearchOption.AllDirectories))
        {
            var code = File.ReadAllText(file);
            Assert.DoesNotContain("HttpListener", code);
            Assert.DoesNotContain("TcpListener", code);
            Assert.DoesNotContain("NamedPipeServerStream", code);
            Assert.DoesNotContain("Invoke-Expression", code);
        }
        var host = new AgentHost(Options(Permit(40)));
        var result = host.Run(new[] { Env(40, "PROFILE_RUN", "{\"argv\":\"calc\"}") })[0];
        Assert.Equal("unknown-field", result.Reason);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_root))
            {
                Directory.Delete(_root, true);
            }
        }
        catch
        {
        }
    }

    private AgentOptions Options(IAuthorizer authorizer, string? profile = null, string? profileSha = null, IModelProvider? model = null)
    {
        return new AgentOptions
        {
            DataDirectory = _data,
            WorkspaceRoot = _ws,
            ForbiddenRoots = new[] { _repo, _agent },
            Authorizer = authorizer,
            Clock = _clock,
            Model = model ?? new NullModelProvider(),
            ProfilePath = profile,
            ProfileSha256 = profileSha
        };
    }

    private static TestAuthorizer Permit(params int[] ids)
    {
        return new TestAuthorizer(ids.Select(Id));
    }

    private static string Id(int n)
    {
        return "00000000-0000-4000-8000-" + n.ToString("000000000000");
    }

    private static string Env(int step, string action, string args, int[]? deps = null, string? expires = null, string? deadline = null, int job = 1, int request = 0)
    {
        var depJson = "[]";
        if (deps is not null && deps.Length > 0)
        {
            depJson = "[" + string.Join(",", deps.Select(item => "\"" + Id(item) + "\"")) + "]";
        }
        var requestId = request == 0 ? step : request;
        return "{\"schema\":1,\"job_id\":\"" + Id(job) + "\",\"request_id\":\"" + Id(requestId) + "\",\"step_id\":\"" + Id(step)
            + "\",\"action\":\"" + action + "\",\"args\":" + args + ",\"depends_on\":" + depJson
            + ",\"expires_at\":\"" + (expires ?? "2026-09-23T18:00:00Z") + "\",\"job_deadline\":\"" + (deadline ?? "2026-09-23T18:00:00Z") + "\"}";
    }

    private (string Path, string Sha) Profile(string python, int timeout, int limit)
    {
        var dir = Path.Combine(_root, "profile-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var exe = "/usr/bin/python3";
        var exeHash = Sha(File.ReadAllBytes(exe));
        var json = "{\"name\":\"test-profile\",\"executable\":\"" + exe + "\",\"arguments\":[\"-c\",\"" + python.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"],\"executable_sha256\":\"" + exeHash + "\",\"timeout_ms\":" + timeout + ",\"stdout_limit\":" + limit + "}";
        var path = Path.Combine(dir, "profile.json");
        File.WriteAllText(path, json);
        return (path, Sha(File.ReadAllBytes(path)));
    }

    private static void MakeReadOnly(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            new FileInfo(path).IsReadOnly = true;
            return;
        }
        File.SetUnixFileMode(path, UnixFileMode.UserRead);
    }

    private static string Sha(byte[] bytes)
    {
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }

    private static byte[] Utf8(string text)
    {
        return new UTF8Encoding(false).GetBytes(text);
    }

    private static string FindAgentDir()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "CONTRACT.md")) && Directory.Exists(Path.Combine(dir.FullName, "src")))
            {
                return dir.FullName;
            }
            dir = dir.Parent;
        }
        throw new InvalidOperationException("agent dir not found");
    }

    private static (int Code, string Output, string Error) RunDll(string dll, string? arg = null)
    {
        var psi = new ProcessStartInfo("dotnet")
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false
        };
        psi.ArgumentList.Add("exec");
        psi.ArgumentList.Add(dll);
        if (arg is not null)
        {
            psi.ArgumentList.Add(arg);
        }
        using var proc = Process.Start(psi)!;
        var output = proc.StandardOutput.ReadToEnd();
        var error = proc.StandardError.ReadToEnd();
        proc.WaitForExit(15000);
        return (proc.ExitCode, output, error);
    }

    private sealed class FixedClock : IClock
    {
        public DateTime UtcNow { get; set; }
    }
}

public sealed class FakeModelProvider : IModelProvider
{
    private readonly string _reply;
    private readonly bool _throwTimeout;

    public int Calls { get; private set; }

    public FakeModelProvider(string reply, bool throwTimeout = false)
    {
        _reply = reply;
        _throwTimeout = throwTimeout;
    }

    public string Ask(string prompt, int timeoutMs, CancellationToken cancellationToken)
    {
        Calls++;
        cancellationToken.ThrowIfCancellationRequested();
        if (_throwTimeout)
        {
            throw new TimeoutException("model timeout");
        }
        return _reply;
    }
}
