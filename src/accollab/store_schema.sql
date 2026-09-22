-- AC-Collab Store v1: локальный журнал операций (SQLite, WAL).
-- Соответствует схемам из 00-proposal.md §6.
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects(
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  pln_hash TEXT DEFAULT '',
  protocol_version TEXT NOT NULL DEFAULT '1.0',
  created_by TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS participants(
  participant_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT NOT NULL DEFAULT '#4DA3FF',
  pubkey TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'offline',
  last_seen TEXT DEFAULT '',
  version_vector TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS elements_cache(
  guid TEXT PRIMARY KEY,
  type TEXT NOT NULL DEFAULT '?',
  checksum TEXT NOT NULL DEFAULT '',
  last_change_id TEXT DEFAULT '',
  deleted INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations(
  change_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  element_guid TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL,
  wall_time TEXT NOT NULL,
  lamport INTEGER NOT NULL DEFAULT 0,
  base_vector TEXT NOT NULL DEFAULT '{}',
  seq INTEGER NOT NULL DEFAULT 0,
  op TEXT NOT NULL,
  before_json TEXT NOT NULL DEFAULT '{}',
  after_json TEXT NOT NULL DEFAULT '{}',
  tx_id TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'primary',
  deps_json TEXT NOT NULL DEFAULT '[]',
  signature TEXT DEFAULT '',
  applied INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ops_element ON operations(element_guid);
CREATE INDEX IF NOT EXISTS idx_ops_tx ON operations(tx_id);
CREATE INDEX IF NOT EXISTS idx_ops_author ON operations(author);

CREATE TABLE IF NOT EXISTS outbox(
  change_id TEXT PRIMARY KEY,
  enqueued_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locks(
  element_guid TEXT PRIMARY KEY,
  holder TEXT NOT NULL,
  lease_id TEXT NOT NULL,
  since TEXT NOT NULL,
  heartbeat TEXT NOT NULL,
  expires_in_s INTEGER NOT NULL DEFAULT 20
);

CREATE TABLE IF NOT EXISTS conflicts(
  conflict_id TEXT PRIMARY KEY,
  element_guid TEXT NOT NULL,
  ours_change TEXT NOT NULL,
  theirs_change TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  resolution TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS comments(
  comment_id TEXT PRIMARY KEY,
  target_json TEXT NOT NULL,
  author TEXT NOT NULL,
  created_at TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  replies_json TEXT NOT NULL DEFAULT '[]',
  mentions_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS checkpoints(
  checkpoint_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  author TEXT NOT NULL,
  created_at TEXT NOT NULL,
  vector_json TEXT NOT NULL DEFAULT '{}',
  oplog_offset INTEGER NOT NULL DEFAULT 0,
  pln_backup TEXT DEFAULT '',
  description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_state(
  peer TEXT PRIMARY KEY,
  last_vector TEXT NOT NULL DEFAULT '{}',
  pending_out INTEGER NOT NULL DEFAULT 0,
  pending_in INTEGER NOT NULL DEFAULT 0,
  last_sync TEXT DEFAULT '',
  errors_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  taken_at TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_snapshots_taken ON snapshots(taken_at);
