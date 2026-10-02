-- Creator Studio: editorial (story) sources, daily brief, material library, documents, versions,
-- platform variants, publications. Also widens sources.kind to accept 'story'.

PRAGMA foreign_keys=OFF;

CREATE TABLE sources_v3 (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  adapter TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('demand','supply','hybrid','story')),
  mode TEXT NOT NULL DEFAULT 'live' CHECK(mode IN ('live','mock')),
  enabled INTEGER NOT NULL DEFAULT 1,
  reliability INTEGER NOT NULL DEFAULT 70,
  max_per_round INTEGER NOT NULL DEFAULT 100,
  config_json TEXT NOT NULL DEFAULT '{}',
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO sources_v3 SELECT id,name,adapter,kind,mode,enabled,reliability,max_per_round,config_json,note,created_at,updated_at FROM sources;
DROP TABLE sources;
ALTER TABLE sources_v3 RENAME TO sources;

PRAGMA foreign_keys=ON;

-- Editorial assessment of story signals ("is this worth writing about?")
CREATE TABLE IF NOT EXISTS story_assessments (
  signal_id TEXT PRIMARY KEY REFERENCES signals(id) ON DELETE CASCADE,
  lane TEXT NOT NULL DEFAULT 'OTHER',
  business_value INTEGER NOT NULL DEFAULT 0,
  why TEXT NOT NULL DEFAULT '',
  angles_json TEXT NOT NULL DEFAULT '[]',
  keywords_json TEXT NOT NULL DEFAULT '[]',
  method TEXT NOT NULL CHECK(method IN ('model','rule','fixture')),
  model TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_story_value ON story_assessments(business_value DESC);

-- One-page daily brief. Rows are frozen per day; status is the user's triage.
CREATE TABLE IF NOT EXISTS brief_items (
  id TEXT PRIMARY KEY,
  day TEXT NOT NULL,
  section TEXT NOT NULL CHECK(section IN ('story','signal','opportunity')),
  ref_type TEXT NOT NULL CHECK(ref_type IN ('signal','pain_cluster','opportunity')),
  ref_id TEXT NOT NULL,
  rank INTEGER NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  source_name TEXT,
  lane TEXT,
  summary TEXT NOT NULL DEFAULT '',
  why TEXT NOT NULL DEFAULT '',
  angles_json TEXT NOT NULL DEFAULT '[]',
  score REAL NOT NULL DEFAULT 0,
  origin TEXT NOT NULL DEFAULT 'live' CHECK(origin IN ('live','mock','mixed')),
  status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','saved','dismissed','used')),
  material_id TEXT,
  document_id TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(day, ref_type, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_brief_day ON brief_items(day, section, rank);

-- Material library: anything a piece can be built from.
CREATE TABLE IF NOT EXISTS materials (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('story','signal','cluster','opportunity','url','note')),
  title TEXT NOT NULL,
  url TEXT,
  source_name TEXT,
  author TEXT,
  published_at TEXT,
  summary TEXT NOT NULL DEFAULT '',
  quote TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  ref_type TEXT,
  ref_id TEXT,
  lane TEXT,
  tags_json TEXT NOT NULL DEFAULT '[]',
  origin TEXT NOT NULL DEFAULT 'live' CHECK(origin IN ('live','mock','manual')),
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_materials_ref ON materials(ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_materials_created ON materials(created_at DESC);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '未命名稿件',
  status TEXT NOT NULL DEFAULT 'idea' CHECK(status IN ('idea','draft','ready','published','archived')),
  lane TEXT,
  thesis TEXT NOT NULL DEFAULT '',
  target_platform TEXT NOT NULL DEFAULT 'wechat',
  content_md TEXT NOT NULL DEFAULT '',
  word_count INTEGER NOT NULL DEFAULT 0,
  seed_material_id TEXT REFERENCES materials(id) ON DELETE SET NULL,
  data_mode TEXT NOT NULL DEFAULT 'live' CHECK(data_mode IN ('live','mock','mixed')),
  current_version INTEGER NOT NULL DEFAULT 0,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at DESC);

CREATE TABLE IF NOT EXISTS document_versions (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  title TEXT NOT NULL,
  content_md TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('autosave','manual','ai','restore','seed')),
  note TEXT,
  word_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(document_id, version_number)
);

CREATE TABLE IF NOT EXISTS document_materials (
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  relation TEXT NOT NULL DEFAULT 'support' CHECK(relation IN ('seed','support','context')),
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (document_id, material_id)
);

CREATE TABLE IF NOT EXISTS platform_variants (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  platform TEXT NOT NULL CHECK(platform IN ('wechat','xiaohongshu','zhihu','toutiao','x')),
  title TEXT NOT NULL,
  content_md TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  generated_by TEXT NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_variants_doc ON platform_variants(document_id, created_at DESC);

CREATE TABLE IF NOT EXISTS publications (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  variant_id TEXT REFERENCES platform_variants(id) ON DELETE SET NULL,
  platform TEXT NOT NULL,
  external_url TEXT,
  note TEXT,
  published_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Writing-assistant history (what the model proposed, whether it was accepted)
CREATE TABLE IF NOT EXISTS ai_actions (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  mode TEXT,
  input_excerpt TEXT,
  output_json TEXT NOT NULL,
  model TEXT NOT NULL,
  generated_by TEXT NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  accepted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_actions_doc ON ai_actions(document_id, created_at DESC);
