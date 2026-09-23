namespace Arena.LocalAgent;

public sealed class Authorization
{
    public bool Allowed { get; }
    public string Reason { get; }

    private Authorization(bool allowed, string reason)
    {
        Allowed = allowed;
        Reason = reason;
    }

    public static Authorization Allow()
    {
        return new Authorization(true, "");
    }

    public static Authorization Deny(string reason)
    {
        return new Authorization(false, reason);
    }
}

public interface IAuthorizer
{
    Authorization Decide(StepEnvelope step);
}

public sealed class RemoteAuthorizer : IAuthorizer
{
    public Authorization Decide(StepEnvelope step)
    {
        return Authorization.Deny("remote-deny");
    }
}

public sealed class TestAuthorizer : IAuthorizer
{
    private readonly HashSet<string> _permitted;

    public TestAuthorizer(IEnumerable<string> permittedStepIds)
    {
        _permitted = new HashSet<string>(permittedStepIds, StringComparer.Ordinal);
    }

    public Authorization Decide(StepEnvelope step)
    {
        if (!AllowedActions.Contains(step.Action))
        {
            return Authorization.Deny("unknown-action");
        }
        if (!_permitted.Contains(step.StepId))
        {
            return Authorization.Deny("not-permitted");
        }
        return Authorization.Allow();
    }
}

public static class AllowedActions
{
    public static readonly HashSet<string> All = new(StringComparer.Ordinal)
    {
        "FILE_READ",
        "FILE_HASH",
        "FILE_WRITE_ATOMIC",
        "FILE_APPLY_PATCH",
        "PROFILE_RUN"
    };

    public static bool Contains(string action)
    {
        return All.Contains(action);
    }
}
