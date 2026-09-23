var mode = args.Length > 0 ? args[0] : "";
switch (mode)
{
    case "env":
        Console.Write(Environment.GetEnvironmentVariable(args.Length > 1 ? args[1] : "") ?? "");
        return 0;
    case "sleep":
        Thread.Sleep(int.Parse(args[1], System.Globalization.CultureInfo.InvariantCulture));
        return 0;
    case "flood":
        var count = int.Parse(args[1], System.Globalization.CultureInfo.InvariantCulture);
        var chunk = new string('x', 1024);
        var left = count;
        while (left > 0)
        {
            var take = Math.Min(chunk.Length, left);
            Console.Write(chunk.Substring(0, take));
            left -= take;
        }
        Console.Out.Flush();
        return 0;
    case "exit":
        return int.Parse(args[1], System.Globalization.CultureInfo.InvariantCulture);
    default:
        Console.Error.Write("unknown-mode");
        return 2;
}
