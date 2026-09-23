using Microsoft.Data.Sqlite;

namespace Arena.LocalAgent;

internal sealed class StepRow
{
    public required string StepId { get; init; }
    public required string JobId { get; init; }
    public string JobDeadline { get; init; } = "";
    public required string RequestId { get; init; }
    public required string Action { get; init; }
    public required string State { get; init; }
    public required string Reason { get; init; }
    public required string Sha256 { get; init; }
    public required string TargetPath { get; init; }
    public required int ExecCount { get; init; }
    public required string UntrustedModelText { get; init; }
    public string Output { get; init; } = "";
}

internal sealed class StepStore : IDisposable
{
    private readonly SqliteConnection _connection;
    private readonly HashSet<string> _owned = new(StringComparer.Ordinal);

    public StepStore(string path)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Pooling = false
        };
        _connection = new SqliteConnection(builder.ToString());
        _connection.Open();
        Exec("PRAGMA busy_timeout=60000;");
        Scalar("PRAGMA journal_mode=WAL;");
        Exec("PRAGMA synchronous=FULL;");
        Exec("""
            CREATE TABLE IF NOT EXISTS steps (
              step_id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL,
              job_deadline TEXT NOT NULL DEFAULT '',
              request_id TEXT NOT NULL,
              action TEXT NOT NULL,
              state TEXT NOT NULL,
              reason TEXT NOT NULL,
              sha256 TEXT NOT NULL,
              target_path TEXT NOT NULL,
              exec_count INTEGER NOT NULL,
              model_text TEXT NOT NULL,
              output TEXT NOT NULL,
              updated TEXT NOT NULL
            );
            """);
        if (!HasColumn("job_deadline"))
        {
            Exec("ALTER TABLE steps ADD COLUMN job_deadline TEXT NOT NULL DEFAULT '';");
        }
    }

    private bool HasColumn(string name)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "PRAGMA table_info(steps);";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            if (string.Equals(reader.GetString(1), name, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        return false;
    }

    public string JournalMode()
    {
        return Scalar("PRAGMA journal_mode;") ?? "";
    }

    public StepRow? Find(string stepId)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT step_id, job_id, job_deadline, request_id, action, state, reason, sha256, target_path, exec_count, model_text, output FROM steps WHERE step_id = @id";
        cmd.Parameters.AddWithValue("@id", stepId);
        using var reader = cmd.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return Read(reader);
    }

    public bool SaveOwned(StepRow row)
    {
        if (_owned.Contains(row.StepId))
        {
            Update(row);
            return true;
        }
        if (!InsertNew(row))
        {
            return false;
        }
        _owned.Add(row.StepId);
        return true;
    }

    public bool InsertNew(StepRow row)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = """
            INSERT INTO steps (step_id, job_id, job_deadline, request_id, action, state, reason, sha256, target_path, exec_count, model_text, output, updated)
            VALUES (@step, @job, @deadline, @req, @action, @state, @reason, @sha, @path, @exec, @model, @output, @updated)
            ON CONFLICT(step_id) DO NOTHING
            """;
        Bind(cmd, row);
        return cmd.ExecuteNonQuery() == 1;
    }

    public void Update(StepRow row)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = """
            UPDATE steps SET
              request_id = @req,
              action = @action,
              state = @state,
              reason = @reason,
              sha256 = @sha,
              target_path = @path,
              exec_count = @exec,
              model_text = @model,
              output = @output,
              updated = @updated
            WHERE step_id = @step
            """;
        Bind(cmd, row);
        cmd.ExecuteNonQuery();
    }

    private static void Bind(SqliteCommand cmd, StepRow row)
    {
        cmd.Parameters.AddWithValue("@step", row.StepId);
        cmd.Parameters.AddWithValue("@job", row.JobId);
        cmd.Parameters.AddWithValue("@deadline", row.JobDeadline);
        cmd.Parameters.AddWithValue("@req", row.RequestId);
        cmd.Parameters.AddWithValue("@action", row.Action);
        cmd.Parameters.AddWithValue("@state", row.State);
        cmd.Parameters.AddWithValue("@reason", row.Reason);
        cmd.Parameters.AddWithValue("@sha", row.Sha256);
        cmd.Parameters.AddWithValue("@path", row.TargetPath);
        cmd.Parameters.AddWithValue("@exec", row.ExecCount);
        cmd.Parameters.AddWithValue("@model", row.UntrustedModelText);
        cmd.Parameters.AddWithValue("@output", row.Output);
        cmd.Parameters.AddWithValue("@updated", DateTime.UtcNow.ToString("o"));
    }

    private void Exec(string sql)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = sql;
        cmd.ExecuteNonQuery();
    }

    private string? Scalar(string sql)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = sql;
        return cmd.ExecuteScalar()?.ToString();
    }

    private static StepRow Read(SqliteDataReader reader)
    {
        return new StepRow
        {
            StepId = reader.GetString(0),
            JobId = reader.GetString(1),
            JobDeadline = reader.GetString(2),
            RequestId = reader.GetString(3),
            Action = reader.GetString(4),
            State = reader.GetString(5),
            Reason = reader.GetString(6),
            Sha256 = reader.GetString(7),
            TargetPath = reader.GetString(8),
            ExecCount = reader.GetInt32(9),
            UntrustedModelText = reader.GetString(10),
            Output = reader.GetString(11)
        };
    }

    public void Dispose()
    {
        _connection.Dispose();
    }
}
