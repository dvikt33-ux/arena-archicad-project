using System.Text.Json;

namespace Arena.LocalAgent;

public sealed class StepResult
{
    public string StepId { get; init; } = "";
    public string JobId { get; init; } = "";
    public string RequestId { get; init; } = "";
    public string Action { get; init; } = "";
    public string State { get; init; } = "";
    public string Reason { get; init; } = "";
    public string Sha256 { get; init; } = "";
    public string Output { get; init; } = "";
    public bool Executed { get; init; }
    public string UntrustedModelText { get; init; } = "";
}

public sealed class AgentOptions
{
    public required string DataDirectory { get; init; }
    public required string WorkspaceRoot { get; init; }
    public required IReadOnlyList<string> ForbiddenRoots { get; init; }
    public required IAuthorizer Authorizer { get; init; }
    public IClock Clock { get; init; } = new SystemClock();
    public IModelProvider Model { get; init; } = new NullModelProvider();
    public string? ProfilePath { get; init; }
    public string? ProfileSha256 { get; init; }
    public int ModelTimeoutMs { get; init; } = 1000;
}

public sealed class AgentHost
{
    private readonly AgentOptions _options;

    public AgentHost(AgentOptions options)
    {
        _options = options;
    }

    public string HandshakeJson()
    {
        return AgentInfo.HandshakeJson();
    }

    public IReadOnlyList<StepResult> Run(IReadOnlyList<string> rawEnvelopes)
    {
        if (!TryOpen(out var workspace, out var store, out var openReason))
        {
            return rawEnvelopes.Select(raw => Unsaved(EnvelopeParser.Parse(raw), openReason)).ToList();
        }
        using (store)
        {
            var parsed = rawEnvelopes.Select(EnvelopeParser.Parse).ToList();
            var results = new StepResult?[parsed.Count];
            var already = new StepRow?[parsed.Count];
            for (var i = 0; i < parsed.Count; i++)
            {
                var id = parsed[i].StepId ?? parsed[i].Envelope?.StepId;
                if (id is not null)
                {
                    already[i] = store!.Find(id);
                }
            }
            var jobs = new HashSet<string>(StringComparer.Ordinal);
            var deadlines = new HashSet<DateTime>();
            foreach (var outcome in parsed)
            {
                if (!outcome.Ok || outcome.Envelope is null)
                {
                    continue;
                }
                jobs.Add(outcome.Envelope.JobId);
                deadlines.Add(outcome.Envelope.JobDeadline);
            }
            var batchReason = jobs.Count > 1 ? "job-mismatch" : deadlines.Count > 1 ? "bad-deadline" : null;
            var canonical = new Dictionary<string, int>(StringComparer.Ordinal);
            var deferred = new Dictionary<string, List<int>>(StringComparer.Ordinal);
            var pending = new List<int>();
            for (var i = 0; i < parsed.Count; i++)
            {
                var outcome = parsed[i];
                var id = outcome.StepId ?? outcome.Envelope?.StepId;
                if (already[i] is not null)
                {
                    results[i] = FromRow(already[i]!, false);
                    continue;
                }
                if (id is not null && canonical.ContainsKey(id))
                {
                    if (!deferred.TryGetValue(id, out var later))
                    {
                        later = new List<int>();
                        deferred[id] = later;
                    }
                    later.Add(i);
                    continue;
                }
                if (!outcome.Ok || outcome.Envelope is null)
                {
                    results[i] = Persist(store!, outcome.StepId, outcome.JobId, outcome.RequestId, "", "REJECTED", outcome.Reason, "", "", 0, "", false);
                    if (id is not null)
                    {
                        canonical[id] = i;
                    }
                    continue;
                }
                var step = outcome.Envelope;
                if (batchReason is not null)
                {
                    results[i] = Persist(store!, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", batchReason, "", "", 0, "", false);
                    canonical[step.StepId] = i;
                    continue;
                }
                canonical[step.StepId] = i;
                pending.Add(i);
            }
            if (pending.Count > 0)
            {
                var waiting = pending.Select(index => parsed[index].Envelope!).ToList();
                var indexOf = new Dictionary<string, int>(StringComparer.Ordinal);
                foreach (var index in pending)
                {
                    indexOf[parsed[index].Envelope!.StepId] = index;
                }
                while (waiting.Count > 0)
                {
                    var progressed = false;
                    foreach (var step in waiting.ToList())
                    {
                        var blocked = false;
                        foreach (var dep in step.DependsOn)
                        {
                            if (waiting.Any(item => item.StepId == dep))
                            {
                                blocked = true;
                                break;
                            }
                        }
                        if (blocked)
                        {
                            continue;
                        }
                        results[indexOf[step.StepId]] = Dispatch(store!, workspace!, step);
                        waiting.Remove(step);
                        progressed = true;
                    }
                    if (!progressed)
                    {
                        foreach (var step in waiting)
                        {
                            results[indexOf[step.StepId]] = Persist(store!, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "dependency-cycle", "", "", 0, "", false);
                        }
                        break;
                    }
                }
            }
            foreach (var pair in deferred)
            {
                var source = results[canonical[pair.Key]];
                foreach (var index in pair.Value)
                {
                    results[index] = CopyReplay(source);
                }
            }
            return Materialize(results);
        }
    }

    internal string JournalMode()
    {
        if (!TryOpen(out _, out var store, out var reason))
        {
            return reason;
        }
        using (store)
        {
            return store!.JournalMode();
        }
    }

    public StepResult Recover(string stepId)
    {
        if (!TryOpen(out var workspace, out var store, out var reason))
        {
            return new StepResult { StepId = stepId, State = "REJECTED", Reason = reason, Executed = false };
        }
        using (store)
        {
            var row = store!.Find(stepId);
            if (row is null)
            {
                return new StepResult { StepId = stepId, State = "REJECTED", Reason = "not-found", Executed = false };
            }
            if (row.State != "RUNNING")
            {
                return FromRow(row, false);
            }
            if (row.Sha256.Length == 64 && row.TargetPath.Length > 0 && workspace!.TryResolve(row.TargetPath, out var full, out _))
            {
                if (File.Exists(full) && !((File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0))
                {
                    var actual = Hashing.Sha256(File.ReadAllBytes(full));
                    if (actual == row.Sha256)
                    {
                        var completed = row.Copy("COMPLETED", "", row.Sha256, row.ExecCount);
                        store.Update(completed);
                        return FromRow(completed, false);
                    }
                }
            }
            var review = row.Copy("NEEDS_REVIEW", "running-incomplete", row.Sha256, row.ExecCount);
            store.Update(review);
            return FromRow(review, false);
        }
    }

    internal void SeedRunning(string stepId, string jobId, string requestId, string action, string intendedSha, string relativePath)
    {
        if (!TryOpen(out _, out var store, out var reason))
        {
            throw new InvalidOperationException(reason);
        }
        using (store)
        {
            store!.InsertNew(new StepRow
            {
                StepId = stepId,
                JobId = jobId,
                RequestId = requestId,
                Action = action,
                State = "RUNNING",
                Reason = "",
                Sha256 = intendedSha,
                TargetPath = relativePath,
                ExecCount = 1,
                UntrustedModelText = ""
            });
        }
    }

    private StepResult Dispatch(StepStore store, BoundWorkspace workspace, StepEnvelope step)
    {
        var claimed = Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "RUNNING", "", "", "", 0, "", true);
        if (!claimed.Executed)
        {
            return claimed;
        }
        var now = _options.Clock.UtcNow;
        if (now > step.ExpiresAt || now > step.JobDeadline)
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "expired", "", "", 0, "", false);
        }
        foreach (var dep in step.DependsOn)
        {
            if (dep == step.StepId)
            {
                return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "dependency-cycle", "", "", 0, "", false);
            }
            var previous = store.Find(dep);
            if (previous is null || previous.JobId != step.JobId)
            {
                return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "missing-dependency", "", "", 0, "", false);
            }
            if (previous.State != "COMPLETED")
            {
                return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "dependency-not-satisfied", "", "", 0, "", false);
            }
        }
        var decision = _options.Authorizer.Decide(step);
        if (!decision.Allowed)
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", decision.Reason, "", "", 0, "", false);
        }
        var modelText = AskModel();
        return step.Action switch
        {
            "FILE_READ" => ReadOrHash(store, workspace, step, modelText),
            "FILE_HASH" => ReadOrHash(store, workspace, step, modelText),
            "FILE_WRITE_ATOMIC" => WriteAtomic(store, workspace, step, modelText),
            "FILE_APPLY_PATCH" => ApplyPatch(store, workspace, step, modelText),
            "PROFILE_RUN" => RunProfile(store, workspace, step, modelText),
            _ => Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "unknown-action", "", "", 0, modelText, false)
        };
    }

    private string AskModel()
    {
        try
        {
            using var cts = new CancellationTokenSource(_options.ModelTimeoutMs);
            return _options.Model.Ask("advisory", _options.ModelTimeoutMs, cts.Token) ?? "";
        }
        catch
        {
            return "";
        }
    }

    private StepResult ReadOrHash(StepStore store, BoundWorkspace workspace, StepEnvelope step, string modelText)
    {
        var path = Arg(step, "path");
        if (!workspace.TryResolve(path, out var full, out var reason))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", reason, "", path, 0, modelText, false);
        }
        var claimed = Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "RUNNING", "", "", path, 1, modelText, true);
        if (!claimed.Executed)
        {
            return claimed;
        }
        if (step.Action == "FILE_HASH")
        {
            var hashed = workspace.Read(full, out reason);
            if (hashed is null)
            {
                var hashState = reason == "not-found" ? "FAILED" : "REJECTED";
                return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, hashState, reason, "", path, 0, modelText, false);
            }
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "COMPLETED", "", Hashing.Sha256(hashed), path, 1, modelText, true);
        }
        var bytes = workspace.ReadLimited(full, AgentInfo.FileReadLimit, out reason);
        if (bytes is null)
        {
            var state = reason == "not-found" || reason == "read-limit" ? "FAILED" : "REJECTED";
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, state, reason, "", path, 0, modelText, false);
        }
        if (!Utf8.TryDecode(bytes, out var text))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "FAILED", "bad-encoding", "", path, 0, modelText, false);
        }
        var hash = Hashing.Sha256(bytes);
        return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "COMPLETED", "", hash, path, 1, modelText, true, text);
    }

    private StepResult WriteAtomic(StepStore store, BoundWorkspace workspace, StepEnvelope step, string modelText)
    {
        var path = Arg(step, "path");
        if (!workspace.TryResolve(path, out var full, out var reason))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", reason, "", path, 0, modelText, false);
        }
        var bytes = Utf8.NoBom.GetBytes(Arg(step, "content_utf8"));
        var intended = Hashing.Sha256(bytes);
        var exists = File.Exists(full);
        string? expected = step.Args.ContainsKey("expected_sha256") ? Hashing.NormalizeSha(Arg(step, "expected_sha256")) : null;
        if (exists && expected is null)
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "CONFLICT", "conflict-exists", "", path, 0, modelText, false);
        }
        if (!exists && expected is not null)
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "CONFLICT", "conflict-hash", "", path, 0, modelText, false);
        }
        if (exists && expected is not null)
        {
            var current = Hashing.Sha256(File.ReadAllBytes(full));
            if (current != expected)
            {
                return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "CONFLICT", "conflict-hash", current, path, 0, modelText, false);
            }
        }
        var running = Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "RUNNING", "", intended, path, 1, modelText, true);
        if (!running.Executed)
        {
            return running;
        }
        if (!workspace.TryWrite(full, bytes, out reason))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "NEEDS_REVIEW", "running-incomplete", intended, path, 1, modelText, true);
        }
        var readBack = File.ReadAllBytes(full);
        var actual = Hashing.Sha256(readBack);
        if (actual != intended)
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "NEEDS_REVIEW", "running-incomplete", intended, path, 1, modelText, true);
        }
        return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "COMPLETED", "", actual, path, 1, modelText, true);
    }

    private StepResult ApplyPatch(StepStore store, BoundWorkspace workspace, StepEnvelope step, string modelText)
    {
        var path = Arg(step, "path");
        if (!workspace.TryResolve(path, out var full, out var reason))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", reason, "", path, 0, modelText, false);
        }
        if (!File.Exists(full))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "CONFLICT", "conflict-exists", "", path, 0, modelText, false);
        }
        var currentBytes = File.ReadAllBytes(full);
        var currentHash = Hashing.Sha256(currentBytes);
        var expected = Hashing.NormalizeSha(Arg(step, "expected_sha256"));
        if (currentHash != expected)
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "CONFLICT", "conflict-hash", currentHash, path, 0, modelText, false);
        }
        var fileText = Utf8.NoBom.GetString(currentBytes);
        if (!Patcher.TryApply(fileText, Arg(step, "patch_utf8"), out var patched, out reason))
        {
            var state = reason == "patch-mismatch" ? "CONFLICT" : "REJECTED";
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, state, reason, currentHash, path, 0, modelText, false);
        }
        var bytes = Utf8.NoBom.GetBytes(patched);
        var intended = Hashing.Sha256(bytes);
        var running = Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "RUNNING", "", intended, path, 1, modelText, true);
        if (!running.Executed)
        {
            return running;
        }
        if (!workspace.TryWrite(full, bytes, out _))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "NEEDS_REVIEW", "running-incomplete", intended, path, 1, modelText, true);
        }
        var actual = Hashing.Sha256(File.ReadAllBytes(full));
        if (actual != intended)
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "NEEDS_REVIEW", "running-incomplete", intended, path, 1, modelText, true);
        }
        return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "COMPLETED", "", actual, path, 1, modelText, true);
    }

    private StepResult RunProfile(StepStore store, BoundWorkspace workspace, StepEnvelope step, string modelText)
    {
        if (string.IsNullOrWhiteSpace(_options.ProfilePath) || string.IsNullOrWhiteSpace(_options.ProfileSha256))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "profile-missing", "", "", 0, modelText, false);
        }
        if (!ProfileRunner.TryLoad(_options.ProfilePath, _options.ProfileSha256, out var profile, out var reason) || profile is null)
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", reason, "", "", 0, modelText, false);
        }
        if (BoundWorkspace.IsUnder(workspace.Root, profile.Executable))
        {
            return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "profile-mismatch", "", "", 0, modelText, false);
        }
        foreach (var forbidden in _options.ForbiddenRoots)
        {
            if (Directory.Exists(forbidden) && BoundWorkspace.IsUnder(forbidden, profile.Executable))
            {
                return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "REJECTED", "profile-mismatch", "", "", 0, modelText, false);
            }
        }
        var running = Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, "RUNNING", "", "", "", 1, modelText, true);
        if (!running.Executed)
        {
            return running;
        }
        var run = ProfileRunner.Run(profile, workspace.Root);
        var state = run.State == "COMPLETED" ? "COMPLETED" : "FAILED";
        return Persist(store, step.StepId, step.JobId, step.RequestId, step.Action, state, run.Reason, "", "", 1, modelText, true, run.Output);
    }

    private bool TryOpen(out BoundWorkspace? workspace, out StepStore? store, out string reason)
    {
        workspace = null;
        store = null;
        reason = "workspace-forbidden";
        if (!Directory.Exists(_options.WorkspaceRoot) || !Directory.Exists(_options.DataDirectory))
        {
            return false;
        }
        var root = Path.GetFullPath(_options.WorkspaceRoot);
        var data = Path.GetFullPath(_options.DataDirectory);
        if (ContainsReparse(_options.WorkspaceRoot) || ContainsReparse(root) || ContainsReparse(_options.DataDirectory) || ContainsReparse(data))
        {
            return false;
        }
        if (Directory.Exists(Path.Combine(root, ".git")))
        {
            return false;
        }
        if (BoundWorkspace.IsUnder(root, data) || BoundWorkspace.IsUnder(data, root))
        {
            return false;
        }
        foreach (var forbidden in _options.ForbiddenRoots)
        {
            if (string.IsNullOrWhiteSpace(forbidden) || !Directory.Exists(forbidden))
            {
                continue;
            }
            var full = Path.GetFullPath(forbidden);
            if (BoundWorkspace.IsUnder(full, root) || BoundWorkspace.IsUnder(root, full))
            {
                return false;
            }
        }
        workspace = new BoundWorkspace { Root = root };
        store = new StepStore(Path.Combine(data, "agent.sqlite"));
        reason = "";
        return true;
    }

    private static bool IsReparse(string path)
    {
        return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
    }

    internal static bool ContainsReparse(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }
        var root = Path.GetPathRoot(path) ?? "";
        var current = root;
        var rest = path.Length > root.Length ? path.Substring(root.Length) : "";
        foreach (var part in rest.Split(new[] { '/', '\\' }, StringSplitOptions.RemoveEmptyEntries))
        {
            current = current.Length == 0 ? part : Path.Combine(current, part);
            if (!Directory.Exists(current) && !File.Exists(current))
            {
                continue;
            }
            if (IsReparse(current))
            {
                return true;
            }
        }
        return false;
    }

    private static string Arg(StepEnvelope step, string name)
    {
        return step.Args[name].GetString() ?? "";
    }

    private static StepResult Persist(StepStore store, string? stepId, string? jobId, string? requestId, string action, string state, string reason, string sha, string path, int execCount, string modelText, bool executed, string output = "")
    {
        var id = stepId ?? "";
        var row = new StepRow
        {
            StepId = id,
            JobId = jobId ?? "",
            RequestId = requestId ?? "",
            Action = action,
            State = state,
            Reason = reason,
            Sha256 = sha,
            TargetPath = path,
            ExecCount = execCount,
            UntrustedModelText = modelText,
            Output = output
        };
        if (id.Length > 0 && !store.SaveOwned(row))
        {
            var existing = store.Find(id);
            return FromRow(existing ?? row, false);
        }
        return FromRow(row, executed);
    }

    private static StepResult CopyReplay(StepResult? source)
    {
        if (source is null)
        {
            return new StepResult { State = "REJECTED", Reason = "bad-schema", Executed = false };
        }
        return new StepResult
        {
            StepId = source.StepId,
            JobId = source.JobId,
            RequestId = source.RequestId,
            Action = source.Action,
            State = source.State,
            Reason = source.Reason,
            Sha256 = source.Sha256,
            Output = source.Output,
            Executed = false,
            UntrustedModelText = source.UntrustedModelText
        };
    }

    private static StepResult Unsaved(ParseOutcome outcome, string reason)
    {
        return new StepResult
        {
            StepId = outcome.StepId ?? "",
            JobId = outcome.JobId ?? "",
            RequestId = outcome.RequestId ?? "",
            Action = outcome.Envelope?.Action ?? "",
            State = "REJECTED",
            Reason = reason,
            Executed = false
        };
    }

    private static StepResult FromRow(StepRow row, bool executed)
    {
        return new StepResult
        {
            StepId = row.StepId,
            JobId = row.JobId,
            RequestId = row.RequestId,
            Action = row.Action,
            State = row.State,
            Reason = row.Reason,
            Sha256 = row.Sha256,
            Output = row.Output,
            Executed = executed,
            UntrustedModelText = row.UntrustedModelText
        };
    }

    private static IReadOnlyList<StepResult> Materialize(StepResult?[] results)
    {
        return results.Select(item => item ?? new StepResult { State = "REJECTED", Reason = "bad-schema" }).ToList();
    }
}

internal static class StepRowExtensions
{
    public static StepRow Copy(this StepRow row, string state, string reason, string sha, int execCount)
    {
        return new StepRow
        {
            StepId = row.StepId,
            JobId = row.JobId,
            RequestId = row.RequestId,
            Action = row.Action,
            State = state,
            Reason = reason,
            Sha256 = sha,
            TargetPath = row.TargetPath,
            ExecCount = execCount,
            UntrustedModelText = row.UntrustedModelText,
            Output = row.Output
        };
    }
}
