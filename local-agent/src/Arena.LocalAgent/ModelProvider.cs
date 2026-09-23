namespace Arena.LocalAgent;

public interface IClock
{
    DateTime UtcNow { get; }
}

public sealed class SystemClock : IClock
{
    public DateTime UtcNow => DateTime.UtcNow;
}

public interface IModelProvider
{
    string Ask(string prompt, int timeoutMs, CancellationToken cancellationToken);
}

public sealed class NullModelProvider : IModelProvider
{
    public string Ask(string prompt, int timeoutMs, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return "";
    }
}
