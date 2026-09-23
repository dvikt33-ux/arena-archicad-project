namespace Arena.LocalAgent;

public static class Program
{
    public static int Main(string[] args)
    {
        Console.WriteLine(AgentInfo.HandshakeJson());
        if (args.Length > 0)
        {
            Console.Error.WriteLine("jobs are not accepted from the command line");
            return 2;
        }
        return 0;
    }
}
