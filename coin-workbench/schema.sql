PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  lane TEXT NOT NULL CHECK (lane IN ('TECHNOLOGY','BUSINESS','LIVELIHOOD','SOCIETY')),
  role TEXT NOT NULL CHECK (role IN ('PRIMARY','VERIFIER','DISCOVERY')),
  type TEXT NOT NULL,
  url TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS intelligence (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  published_at TEXT,
  collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  summary TEXT,
  content TEXT,
  content_kind TEXT NOT NULL DEFAULT 'CLAIM' CHECK (content_kind IN ('FACT','CLAIM','INFER')),
  source_role TEXT NOT NULL,
  lane TEXT NOT NULL,
  freshness_score REAL NOT NULL DEFAULT 0,
  evidence_score REAL NOT NULL DEFAULT 0,
  title_hash TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT 'live',
  UNIQUE(source_id, canonical_url)
);

CREATE INDEX IF NOT EXISTS idx_intelligence_collected ON intelligence(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_intelligence_lane ON intelligence(lane);
CREATE INDEX IF NOT EXISTS idx_intelligence_hash ON intelligence(title_hash);

CREATE TABLE IF NOT EXISTS story_clusters (
  id TEXT PRIMARY KEY,
  canonical_title TEXT NOT NULL,
  lane TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cluster_items (
  cluster_id TEXT NOT NULL REFERENCES story_clusters(id) ON DELETE CASCADE,
  intelligence_id TEXT NOT NULL REFERENCES intelligence(id) ON DELETE CASCADE,
  PRIMARY KEY(cluster_id, intelligence_id)
);

CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES story_clusters(id),
  title TEXT NOT NULL,
  what_changed TEXT,
  why_now TEXT,
  who_benefits TEXT,
  who_loses TEXT,
  ordinary_impact TEXT,
  china_mapping TEXT,
  evidence_gap TEXT,
  cognition_priority TEXT NOT NULL DEFAULT 'TRACK' CHECK (cognition_priority IN ('HIGH','TRACK','LOW')),
  content_priority TEXT NOT NULL DEFAULT 'TRACK' CHECK (content_priority IN ('WRITE','TRACK','SKIP')),
  cognition_score REAL,
  content_score REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trends (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  judgement TEXT NOT NULL,
  stage TEXT NOT NULL CHECK (stage IN ('EMERGING','ACCELERATING','MAINSTREAM')),
  momentum TEXT NOT NULL CHECK (momentum IN ('STRENGTHENING','STABLE','DIVERGING','WEAKENING','REVERSING')),
  china_relevance TEXT,
  ordinary_impact TEXT,
  watch_next TEXT,
  status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','ACTIVE')),
  first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trend_evidence (
  id TEXT PRIMARY KEY,
  trend_id TEXT NOT NULL REFERENCES trends(id) ON DELETE CASCADE,
  intelligence_id TEXT REFERENCES intelligence(id),
  cluster_id TEXT REFERENCES story_clusters(id),
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('SUPPORT','COUNTER','UNCERTAIN')),
  summary TEXT NOT NULL,
  event_key TEXT NOT NULL,
  occurred_at TEXT,
  added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(trend_id, event_key, evidence_type)
);

CREATE TABLE IF NOT EXISTS trend_revisions (
  id TEXT PRIMARY KEY,
  trend_id TEXT NOT NULL REFERENCES trends(id) ON DELETE CASCADE,
  old_judgement TEXT,
  new_judgement TEXT,
  old_stage TEXT,
  new_stage TEXT,
  old_momentum TEXT,
  new_momentum TEXT,
  reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS theses (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  thesis TEXT NOT NULL,
  strongest_support TEXT,
  strongest_counter TEXT,
  falsification_signal TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','CONFIRMED','HELD')),
  confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS articles (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  thesis_id TEXT NOT NULL REFERENCES theses(id),
  title TEXT,
  outline TEXT,
  body TEXT,
  challenger_notes TEXT,
  status TEXT NOT NULL DEFAULT 'RESEARCH' CHECK (status IN ('RESEARCH','TITLE','OUTLINE','DRAFT','CHALLENGE','READY','ARCHIVED')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS judgement_ledger (
  id TEXT PRIMARY KEY,
  trend_id TEXT REFERENCES trends(id),
  thesis_id TEXT REFERENCES theses(id),
  judgement TEXT NOT NULL,
  horizon TEXT NOT NULL,
  falsification_signal TEXT,
  review_at TEXT,
  result TEXT CHECK (result IN ('CORRECT','DIRECTIONALLY_RIGHT','PARTIAL','WRONG','UNKNOWN')),
  reviewed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
