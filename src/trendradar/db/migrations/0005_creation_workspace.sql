CREATE TABLE IF NOT EXISTS document_workspaces (
  document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
  data_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS document_excerpts (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  fact TEXT NOT NULL,
  quote TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  stance TEXT NOT NULL DEFAULT 'support',
  source_hash TEXT NOT NULL,
  source_title TEXT NOT NULL,
  source_url TEXT,
  source_date TEXT,
  origin TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_excerpts_document ON document_excerpts(document_id);
