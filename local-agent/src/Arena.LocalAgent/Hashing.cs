using System.Security.Cryptography;
using System.Text;

namespace Arena.LocalAgent;

internal static class Hashing
{
    public static string Sha256(byte[] bytes)
    {
        var hash = SHA256.HashData(bytes);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public static string Sha256File(string path)
    {
        using var stream = File.OpenRead(path);
        var hash = SHA256.HashData(stream);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public static bool IsSha256(string text)
    {
        if (text.Length != 64)
        {
            return false;
        }
        foreach (var ch in text)
        {
            var hex = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F');
            if (!hex)
            {
                return false;
            }
        }
        return true;
    }

    public static string NormalizeSha(string text)
    {
        return text.ToLowerInvariant();
    }
}
