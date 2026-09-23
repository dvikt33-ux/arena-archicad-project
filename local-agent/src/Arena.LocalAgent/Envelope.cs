using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Arena.LocalAgent;

public sealed class StepEnvelope
{
    public required string JobId { get; init; }
    public required string RequestId { get; init; }
    public required string StepId { get; init; }
    public required string Action { get; init; }
    public required IReadOnlyDictionary<string, JsonElement> Args { get; init; }
    public required IReadOnlyList<string> DependsOn { get; init; }
    public required DateTime ExpiresAt { get; init; }
    public required DateTime JobDeadline { get; init; }
    public required string Raw { get; init; }
}

public sealed class ParseOutcome
{
    public StepEnvelope? Envelope { get; init; }
    public string? StepId { get; init; }
    public string? JobId { get; init; }
    public string? RequestId { get; init; }
    public string Reason { get; init; } = "";
    public bool Ok => Envelope is not null;
}

public static class EnvelopeParser
{
    private static readonly Regex Uuid = new(
        "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static readonly string[] Top =
    {
        "schema", "job_id", "request_id", "step_id", "action", "args", "depends_on", "expires_at", "job_deadline"
    };

    public static ParseOutcome Parse(string json)
    {
        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(json, new JsonDocumentOptions
            {
                CommentHandling = JsonCommentHandling.Disallow,
                AllowTrailingCommas = false,
                MaxDepth = 8
            });
        }
        catch (JsonException)
        {
            return Fail("bad-schema");
        }
        using (doc)
        {
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return Fail("bad-schema");
            }
            var names = new List<string>();
            foreach (var prop in root.EnumerateObject())
            {
                if (names.Contains(prop.Name))
                {
                    return Fail("unknown-field", TryId(root, "step_id"), TryId(root, "job_id"), TryId(root, "request_id"));
                }
                names.Add(prop.Name);
            }
            foreach (var name in names)
            {
                if (Array.IndexOf(Top, name) < 0)
                {
                    return Fail("unknown-field", TryId(root, "step_id"), TryId(root, "job_id"), TryId(root, "request_id"));
                }
            }
            foreach (var required in Top)
            {
                if (!names.Contains(required))
                {
                    return Fail("bad-schema", TryId(root, "step_id"), TryId(root, "job_id"), TryId(root, "request_id"));
                }
            }
            if (root.GetProperty("schema").ValueKind != JsonValueKind.Number || !root.GetProperty("schema").TryGetInt32(out var schema) || schema != 1)
            {
                return Fail("bad-schema", TryId(root, "step_id"), TryId(root, "job_id"), TryId(root, "request_id"));
            }
            var stepId = ReadUuid(root, "step_id", out var idReason);
            var jobId = ReadUuid(root, "job_id", out var jobReason);
            var requestId = ReadUuid(root, "request_id", out var reqReason);
            if (stepId is null || jobId is null || requestId is null)
            {
                var reason = idReason ?? jobReason ?? reqReason ?? "bad-id";
                return Fail(reason, stepId, jobId, requestId);
            }
            if (root.GetProperty("action").ValueKind != JsonValueKind.String)
            {
                return Fail("unknown-action", stepId, jobId, requestId);
            }
            var action = root.GetProperty("action").GetString() ?? "";
            if (!AllowedActions.Contains(action))
            {
                return Fail("unknown-action", stepId, jobId, requestId);
            }
            if (!TryReadTime(root, "expires_at", out var expires))
            {
                return Fail("bad-time", stepId, jobId, requestId);
            }
            if (!TryReadTime(root, "job_deadline", out var deadline))
            {
                return Fail("bad-time", stepId, jobId, requestId);
            }
            if (expires > deadline)
            {
                return Fail("bad-deadline", stepId, jobId, requestId);
            }
            if (root.GetProperty("depends_on").ValueKind != JsonValueKind.Array)
            {
                return Fail("bad-schema", stepId, jobId, requestId);
            }
            var deps = new List<string>();
            foreach (var item in root.GetProperty("depends_on").EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.String)
                {
                    return Fail("bad-id", stepId, jobId, requestId);
                }
                var dep = item.GetString() ?? "";
                if (!Uuid.IsMatch(dep))
                {
                    return Fail("bad-id", stepId, jobId, requestId);
                }
                if (deps.Contains(dep))
                {
                    return Fail("bad-id", stepId, jobId, requestId);
                }
                deps.Add(dep);
            }
            if (root.GetProperty("args").ValueKind != JsonValueKind.Object)
            {
                return Fail("bad-args", stepId, jobId, requestId);
            }
            var args = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            var argNames = new List<string>();
            foreach (var prop in root.GetProperty("args").EnumerateObject())
            {
                if (argNames.Contains(prop.Name))
                {
                    return Fail("unknown-field", stepId, jobId, requestId);
                }
                argNames.Add(prop.Name);
                args[prop.Name] = prop.Value.Clone();
            }
            var argReason = CheckArgs(action, args);
            if (argReason is not null)
            {
                return Fail(argReason, stepId, jobId, requestId);
            }
            return new ParseOutcome
            {
                StepId = stepId,
                JobId = jobId,
                RequestId = requestId,
                Envelope = new StepEnvelope
                {
                    JobId = jobId,
                    RequestId = requestId,
                    StepId = stepId,
                    Action = action,
                    Args = args,
                    DependsOn = deps,
                    ExpiresAt = expires,
                    JobDeadline = deadline,
                    Raw = json
                }
            };
        }
    }

    private static string? CheckArgs(string action, Dictionary<string, JsonElement> args)
    {
        string[] allowed = action switch
        {
            "FILE_READ" => new[] { "path" },
            "FILE_HASH" => new[] { "path" },
            "FILE_WRITE_ATOMIC" => new[] { "path", "content_utf8", "expected_sha256" },
            "FILE_APPLY_PATCH" => new[] { "path", "expected_sha256", "patch_utf8" },
            "PROFILE_RUN" => Array.Empty<string>(),
            _ => Array.Empty<string>()
        };
        foreach (var name in args.Keys)
        {
            if (Array.IndexOf(allowed, name) < 0)
            {
                return "unknown-field";
            }
        }
        if (action == "PROFILE_RUN")
        {
            return args.Count == 0 ? null : "unknown-field";
        }
        if (!args.ContainsKey("path") || args["path"].ValueKind != JsonValueKind.String)
        {
            return "bad-args";
        }
        if (action == "FILE_WRITE_ATOMIC")
        {
            if (!args.ContainsKey("content_utf8") || args["content_utf8"].ValueKind != JsonValueKind.String)
            {
                return "bad-args";
            }
            if (args["content_utf8"].GetString()!.Length > 1_000_000)
            {
                return "bad-args";
            }
        }
        if (action == "FILE_APPLY_PATCH")
        {
            if (!args.ContainsKey("expected_sha256") || !args.ContainsKey("patch_utf8"))
            {
                return "bad-args";
            }
            if (args["patch_utf8"].ValueKind != JsonValueKind.String || args["patch_utf8"].GetString()!.Length > 1_000_000)
            {
                return "bad-args";
            }
        }
        if (args.TryGetValue("expected_sha256", out var hash))
        {
            if (hash.ValueKind != JsonValueKind.String || !Hashing.IsSha256(hash.GetString() ?? ""))
            {
                return "bad-hash";
            }
        }
        if (action == "FILE_APPLY_PATCH" && !args.ContainsKey("expected_sha256"))
        {
            return "bad-args";
        }
        return null;
    }

    private static string? ReadUuid(JsonElement root, string name, out string? reason)
    {
        reason = null;
        if (root.GetProperty(name).ValueKind != JsonValueKind.String)
        {
            reason = "bad-id";
            return null;
        }
        var text = root.GetProperty(name).GetString() ?? "";
        if (!Uuid.IsMatch(text))
        {
            reason = "bad-id";
            return null;
        }
        return text;
    }

    private static bool TryReadTime(JsonElement root, string name, out DateTime utc)
    {
        utc = default;
        if (root.GetProperty(name).ValueKind != JsonValueKind.String)
        {
            return false;
        }
        var text = root.GetProperty(name).GetString() ?? "";
        if (!text.EndsWith("Z", StringComparison.Ordinal) && !text.EndsWith("+00:00", StringComparison.Ordinal))
        {
            return false;
        }
        if (!DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var parsed))
        {
            return false;
        }
        if (parsed.Offset != TimeSpan.Zero)
        {
            return false;
        }
        utc = parsed.UtcDateTime;
        return true;
    }

    private static string? TryId(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var prop) || prop.ValueKind != JsonValueKind.String)
        {
            return null;
        }
        var text = prop.GetString() ?? "";
        return Uuid.IsMatch(text) ? text : null;
    }

    private static ParseOutcome Fail(string reason, string? stepId = null, string? jobId = null, string? requestId = null)
    {
        return new ParseOutcome
        {
            Reason = reason,
            StepId = stepId,
            JobId = jobId,
            RequestId = requestId
        };
    }
}
