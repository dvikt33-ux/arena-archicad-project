namespace Arena.LocalAgent;

public static class AgentInfo
{
    public static readonly string[] Present =
    {
        "file.read",
        "file.hash",
        "file.write_atomic",
        "file.apply_patch",
        "profile.run"
    };

    public static readonly string[] Absent =
    {
        "ui.control",
        "archicad.write",
        "system.admin",
        "package.user_install",
        "workspace.exec",
        "mailbox.poll",
        "issue.publish",
        "git.commit",
        "git.push",
        "listener"
    };

    public static string HandshakeJson()
    {
        var present = string.Join(",", Present.Select(static x => "\"" + x + "\""));
        var absent = string.Join(",", Absent.Select(static x => "\"" + x + "\""));
        return "{\"schema\":1,\"present\":[" + present + "],\"absent\":[" + absent + "],\"remote_authorizer\":\"deny\",\"listener\":false}";
    }
}
