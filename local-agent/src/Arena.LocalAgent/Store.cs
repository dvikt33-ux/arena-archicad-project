using Microsoft.Data.Sqlite;

namespace Arena.LocalAgent;

internal sealed class StepRow
{
    public required string StepId { get; init; }
    public required string JobId { get; init; }
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

    public StepStore(string path)
    {
        var builder = new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadWriteCreate };
        _connection = new SqliteConnection(builder.ToString());
        _connection.Open();
        Exec("PRAGMA synchronous=FULL;");
        Exec("""
            CREATE TABLE IF NOT EXISTS steps (
              step_id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL,
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
    }

    public StepRow? Find(string stepId)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT step_id, job_id, request_id, action, state, reason, sha256, target_path, exec_count, model_text, output FROM steps WHERE step_id = @id";
        cmd.Parameters.AddWithValue("@id", stepId);
        using var reader = cmd.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return Read(reader);
    }

    public void Save(StepRow row)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = """
            INSERT INTO steps (step_id, job_id, request_id, action, state, reason, sha256, target_path, exec_count, model_text, output, updated)
            VALUES (@step, @job, @req, @action, @state, @reason, @sha, @path, @exec, @model, @output, @updated)
            ON CONFLICT(step_id) DO UPDATE SET
              state = excluded.state,
              reason = excluded.reason,
              sha256 = excluded.sha256,
              target_path = excluded.target_path,
              exec_count = excluded.exec_count,
              model_text = excluded.model_text,
              output = excluded.output,
              updated = excluded.updated
            """;
        cmd.Parameters.AddWithValue("@step", row.StepId);
        cmd.Parameters.AddWithValue("@job", row.JobId);
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
        cmd.ExecuteNonQuery();
    }

    private void Exec(string sql)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = sql;
        cmd.ExecuteNonQuery();
    }

    private static StepRow Read(SqliteDataReader reader)
    {
        return new StepRow
        {
            StepId = reader.GetString(0),
            JobId = reader.GetString(1),
            RequestId = reader.GetString(2),
            Action = reader.GetString(3),
            State = reader.GetString(4),
            Reason = reader.GetString(5),
            Sha256 = reader.GetString(6),
            TargetPath = reader.GetString(7),
            ExecCount = reader.GetInt32(8),
            UntrustedModelText = reader.GetString(9),
            Output = reader.GetString(10)
        };
    }

    public void Dispose()
    {
        _connection.Dispose();
    }
}
