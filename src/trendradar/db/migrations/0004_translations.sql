-- Translations are separate derived records; original evidence stays unchanged.
CREATE TABLE IF NOT EXISTS article_translations (
  ref_type TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  model TEXT NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY(ref_type, ref_id, source_hash)
);
