CREATE TABLE writing_agent_runs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0,
  state_json TEXT NOT NULL,
  lease_token TEXT,
  lease_until REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_writing_agent_document ON writing_agent_runs(document_id);
