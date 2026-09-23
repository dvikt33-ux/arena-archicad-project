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
            var env = Profile("env", "GH_TOKEN", 2000, 1024);
            var host = new AgentHost(Options(Permit(34), env.Path, env.Sha));
            var result = host.Run(new[] { Env(34, "PROFILE_RUN", "{}") })[0];
            Assert.Equal("COMPLETED", result.State);
            Assert.DoesNotContain("not-a-real-secret-value", result.Output);
            var slow = Profile("sleep", "5000", 400, 1024);
            var host2 = new AgentHost(Options(Permit(35), slow.Path, slow.Sha));
            var timed = host2.Run(new[] { Env(35, "PROFILE_RUN", "{}") })[0];
            Assert.Equal("timeout", timed.Reason);
            var flood = Profile("flood", "200000", 2000, 64);
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
    public void Duplicate_step_in_one_call_executes_once()
    {
        var host = new AgentHost(Options(Permit(61)));
        var results = host.Run(new[]
        {
            Env(61, "FILE_WRITE_ATOMIC", "{\"path\":\"once.txt\",\"content_utf8\":\"one\"}"),
            Env(61, "FILE_WRITE_ATOMIC", "{\"path\":\"twice.txt\",\"content_utf8\":\"two\"}")
        });
        Assert.True(results[0].Executed);
        Assert.Equal("COMPLETED", results[0].State);
        Assert.False(results[1].Executed);
        Assert.Equal(results[0].Action, results[1].Action);
        Assert.Equal(results[0].Sha256, results[1].Sha256);
        Assert.Equal("one", File.ReadAllText(Path.Combine(_ws, "once.txt")));
        Assert.False(File.Exists(Path.Combine(_ws, "twice.txt")));
    }

    [Fact]
    public void Stored_job_blocks_a_new_step_from_another_job()
    {
        var host = new AgentHost(Options(Permit(62, 63, 70)));
        var first = host.Run(new[] { Env(62, "FILE_WRITE_ATOMIC", "{\"path\":\"a.txt\",\"content_utf8\":\"A\"}", job: 1) })[0];
        Assert.Equal("COMPLETED", first.State);
        var mixed = host.Run(new[]
        {
            Env(62, "FILE_READ", "{\"path\":\"a.txt\"}", job: 1),
            Env(63, "FILE_WRITE_ATOMIC", "{\"path\":\"b.txt\",\"content_utf8\":\"B\"}", job: 2)
        });
        Assert.False(mixed[0].Executed);
        Assert.Equal("FILE_WRITE_ATOMIC", mixed[0].Action);
        Assert.Equal("COMPLETED", mixed[0].State);
        Assert.Equal("job-mismatch", mixed[1].Reason);
        Assert.False(mixed[1].Executed);
        Assert.False(File.Exists(Path.Combine(_ws, "b.txt")));
        var deadline = host.Run(new[]
        {
            Env(62, "FILE_READ", "{\"path\":\"a.txt\"}"),
            Env(70, "FILE_WRITE_ATOMIC", "{\"path\":\"latejob.txt\",\"content_utf8\":\"x\"}", deadline: "2026-09-23T19:00:00Z")
        });
        Assert.False(deadline[0].Executed);
        Assert.Equal("bad-deadline", deadline[1].Reason);
        Assert.False(File.Exists(Path.Combine(_ws, "latejob.txt")));
    }

    [Fact]
    public void File_read_returns_bounded_text()
    {
        var host = new AgentHost(Options(Permit(65, 66, 67, 68)));
        var bytes = Utf8("a\r\nb");
        File.WriteAllBytes(Path.Combine(_ws, "note.txt"), bytes);
        var read = host.Run(new[] { Env(65, "FILE_READ", "{\"path\":\"note.txt\"}") })[0];
        Assert.Equal("COMPLETED", read.State);
        Assert.Equal("a\r\nb", read.Output);
        Assert.Equal(Sha(bytes), read.Sha256);
        var hashed = host.Run(new[] { Env(66, "FILE_HASH", "{\"path\":\"note.txt\"}") })[0];
        Assert.Equal("", hashed.Output);
        Assert.Equal(read.Sha256, hashed.Sha256);
        var big = new byte[AgentInfo.FileReadLimit + 1];
        File.WriteAllBytes(Path.Combine(_ws, "big.bin"), big);
        var limited = host.Run(new[] { Env(67, "FILE_READ", "{\"path\":\"big.bin\"}") })[0];
        Assert.Equal("read-limit", limited.Reason);
        Assert.Equal("FAILED", limited.State);
        Assert.Equal("", limited.Output);
        File.WriteAllBytes(Path.Combine(_ws, "bad.bin"), new byte[] { 0xFF });
        var bad = host.Run(new[] { Env(68, "FILE_READ", "{\"path\":\"bad.bin\"}") })[0];
        Assert.Equal("bad-encoding", bad.Reason);
        Assert.Equal("", bad.Output);
    }

    [Fact]
    public void Profile_nonzero_exit_is_failure()
    {
        var env = Profile("exit", "3", 2000, 1024);
        var host = new AgentHost(Options(Permit(69), env.Path, env.Sha));
        var result = host.Run(new[] { Env(69, "PROFILE_RUN", "{}") })[0];
        Assert.Equal("FAILED", result.State);
        Assert.Equal("exit-code", result.Reason);
        Assert.NotEqual("COMPLETED", result.State);
    }

    [Fact]
    public void Store_uses_wal()
    {
        var host = new AgentHost(Options(Permit(64)));
        host.Run(new[] { Env(64, "FILE_HASH", "{\"path\":\"missing.txt\"}") });
        Assert.Equal("wal", host.JournalMode());
    }

    [Fact]
    public void Workspace_reparse_ancestor_is_forbidden()
    {
        var tree = Path.Combine(_root, "forbidden-tree");
        var realWs = Path.Combine(tree, "ws");
        Directory.CreateDirectory(realWs);
        File.WriteAllText(Path.Combine(realWs, "secret.txt"), "no");
        var alias = Path.Combine(_root, "alias-parent");
        CreateAlias(alias, tree);
        var host = new AgentHost(new AgentOptions
        {
            DataDirectory = _data,
            WorkspaceRoot = Path.Combine(alias, "ws"),
            ForbiddenRoots = new[] { tree, _repo, _agent },
            Authorizer = Permit(71),
            Clock = _clock
        });
        var result = host.Run(new[] { Env(71, "FILE_WRITE_ATOMIC", "{\"path\":\"secret.txt\",\"content_utf8\":\"yes\"}") })[0];
        Assert.Equal("workspace-forbidden", result.Reason);
        Assert.False(result.Executed);
        Assert.Equal("no", File.ReadAllText(Path.Combine(realWs, "secret.txt")));
    }

    [Fact]
    public void Concurrent_callers_execute_a_step_once()
    {
        var gate = new GateAuthorizer(Id(60));
        var host = new AgentHost(Options(gate));
        var results = new StepResult[2];
        var errors = new Exception?[2];
        var start = new Barrier(2);
        var threads = new Thread[2];
        threads[0] = new Thread(() =>
        {
            try
            {
                start.SignalAndWait();
                results[0] = host.Run(new[] { Env(60, "FILE_WRITE_ATOMIC", "{\"path\":\"race-a.txt\",\"content_utf8\":\"A\"}") })[0];
            }
            catch (Exception ex)
            {
                errors[0] = ex;
            }
        });
        threads[1] = new Thread(() =>
        {
            try
            {
                start.SignalAndWait();
                results[1] = host.Run(new[] { Env(60, "FILE_WRITE_ATOMIC", "{\"path\":\"race-b.txt\",\"content_utf8\":\"B\"}") })[0];
            }
            catch (Exception ex)
            {
                errors[1] = ex;
            }
        });
        threads[0].Start();
        threads[1].Start();
        var saw = SpinWait.SpinUntil(() => Volatile.Read(ref gate.Entries) >= 1, 5000);
        var both = SpinWait.SpinUntil(() => Volatile.Read(ref gate.Entries) >= 2, 1000);
        gate.Release.Set();
        Assert.True(threads[0].Join(10000));
        Assert.True(threads[1].Join(10000));
        Assert.True(saw);
        Assert.False(both);
        Assert.Null(errors[0]);
        Assert.Null(errors[1]);
        var executed = (results[0].Executed ? 1 : 0) + (results[1].Executed ? 1 : 0);
        Assert.Equal(1, executed);
        var winner = results[0].Executed ? 0 : 1;
        var winnerPath = winner == 0 ? "race-a.txt" : "race-b.txt";
        var loserPath = winner == 0 ? "race-b.txt" : "race-a.txt";
        Assert.Equal(winner == 0 ? "A" : "B", File.ReadAllText(Path.Combine(_ws, winnerPath)));
        Assert.False(File.Exists(Path.Combine(_ws, loserPath)));
        var again = host.Run(new[] { Env(60, "FILE_WRITE_ATOMIC", "{\"path\":\"race-c.txt\",\"content_utf8\":\"C\"}") })[0];
        Assert.False(again.Executed);
        Assert.Equal("COMPLETED", again.State);
        Assert.False(File.Exists(Path.Combine(_ws, "race-c.txt")));
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

    private (string Path, string Sha) Profile(string mode, string arg, int timeout, int limit)
    {
        var dir = Path.Combine(_root, "profile-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var sourceDir = Path.GetDirectoryName(FindChildDll())!;
        foreach (var name in new[] { "Arena.LocalAgent.TestChild.dll", "Arena.LocalAgent.TestChild.runtimeconfig.json", "Arena.LocalAgent.TestChild.deps.json" })
        {
            File.Copy(Path.Combine(sourceDir, name), Path.Combine(dir, name), true);
        }
        var exe = FindDotnetHost();
        var dll = Path.Combine(dir, "Arena.LocalAgent.TestChild.dll");
        var exeHash = Sha(File.ReadAllBytes(exe));
        var arguments = new[] { "exec", dll, mode, arg };
        var json = "{\"name\":\"test-profile\",\"executable\":\"" + JsonEscape(exe) + "\",\"arguments\":[" + string.Join(",", arguments.Select(item => "\"" + JsonEscape(item) + "\"")) + "],\"executable_sha256\":\"" + exeHash + "\",\"timeout_ms\":" + timeout + ",\"stdout_limit\":" + limit + "}";
        var path = Path.Combine(dir, "profile.json");
        File.WriteAllText(path, json);
        return (path, Sha(File.ReadAllBytes(path)));
    }

    private string FindChildDll()
    {
        var root = Path.Combine(_agent, "tests", "Arena.LocalAgent.TestChild", "bin");
        if (!Directory.Exists(root))
        {
            throw new InvalidOperationException("test child not built");
        }
        var matches = Directory.GetFiles(root, "Arena.LocalAgent.TestChild.dll", SearchOption.AllDirectories);
        if (matches.Length == 0)
        {
            throw new InvalidOperationException("test child not built");
        }
        return matches.OrderByDescending(File.GetLastWriteTimeUtc).First();
    }

    private static string FindDotnetHost()
    {
        var file = OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet";
        var dirs = new List<string>();
        var root = Environment.GetEnvironmentVariable("DOTNET_ROOT");
        if (!string.IsNullOrWhiteSpace(root))
        {
            dirs.Add(root);
        }
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        dirs.AddRange(path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries));
        foreach (var dir in dirs)
        {
            var candidate = Path.Combine(dir, file);
            if (File.Exists(candidate))
            {
                return Path.GetFullPath(candidate);
            }
        }
        throw new InvalidOperationException("dotnet host not found");
    }

    private static string JsonEscape(string value)
    {
        return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }

    private static void CreateAlias(string link, string target)
    {
        if (OperatingSystem.IsWindows())
        {
            var psi = new ProcessStartInfo("cmd.exe")
            {
                UseShellExecute = false,
                RedirectStandardError = true
            };
            psi.ArgumentList.Add("/c");
            psi.ArgumentList.Add("mklink");
            psi.ArgumentList.Add("/J");
            psi.ArgumentList.Add(link);
            psi.ArgumentList.Add(target);
            using var proc = Process.Start(psi)!;
            proc.WaitForExit(15000);
            if (proc.ExitCode != 0)
            {
                throw new InvalidOperationException(proc.StandardError.ReadToEnd());
            }
            return;
        }
        Directory.CreateSymbolicLink(link, target);
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

public sealed class GateAuthorizer : IAuthorizer
{
    private readonly string _id;
    public int Entries;
    public readonly ManualResetEventSlim Release = new(false);

    public GateAuthorizer(string id)
    {
        _id = id;
    }

    public Authorization Decide(StepEnvelope step)
    {
        if (step.StepId == _id)
        {
            Interlocked.Increment(ref Entries);
            if (!Release.Wait(10000))
            {
                throw new TimeoutException("gate");
            }
        }
        if (!AllowedActions.Contains(step.Action) || step.StepId != _id)
        {
            return Authorization.Deny("not-permitted");
        }
        return Authorization.Allow();
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
