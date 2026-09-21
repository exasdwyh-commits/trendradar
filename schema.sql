PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  lane TEXT NOT NULL,
  role TEXT NOT NULL,
  type TEXT NOT NULL,
  url TEXT NOT NULL,
  include_pattern TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  note TEXT,
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
  kind TEXT NOT NULL DEFAULT 'CLAIM' CHECK(kind IN ('FACT','CLAIM','INFER')),
  source_role TEXT NOT NULL,
  lane TEXT NOT NULL,
  freshness_score REAL NOT NULL DEFAULT 0,
  evidence_score REAL NOT NULL DEFAULT 0,
  commercial_score REAL NOT NULL DEFAULT 0,
  title_hash TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT 'live',
  UNIQUE(source_id, canonical_url)
);

CREATE INDEX IF NOT EXISTS idx_intel_time ON intelligence(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_intel_lane ON intelligence(lane);
CREATE INDEX IF NOT EXISTS idx_intel_hash ON intelligence(title_hash);

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
  event_summary TEXT,
  what_changed TEXT,
  why_now TEXT,
  profit_pool TEXT,
  who_benefits TEXT,
  who_loses TEXT,
  china_mapping TEXT,
  evidence_gap TEXT,
  cognition_score REAL NOT NULL DEFAULT 0,
  content_score REAL NOT NULL DEFAULT 0,
  action TEXT NOT NULL DEFAULT 'TRACK' CHECK(action IN ('WRITE','TRACK','HOLD','SKIP')),
  generated_by TEXT NOT NULL DEFAULT 'rule',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trends (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  judgement TEXT NOT NULL,
  stage TEXT NOT NULL CHECK(stage IN ('EMERGING','ACCELERATING','MAINSTREAM')),
  momentum TEXT NOT NULL CHECK(momentum IN ('STRENGTHENING','STABLE','DIVERGING','WEAKENING','REVERSING')),
  china_relevance TEXT,
  profit_pool TEXT,
  watch_next TEXT,
  status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','ACTIVE')),
  first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trend_evidence (
  id TEXT PRIMARY KEY,
  trend_id TEXT NOT NULL REFERENCES trends(id) ON DELETE CASCADE,
  cluster_id TEXT REFERENCES story_clusters(id),
  intelligence_id TEXT REFERENCES intelligence(id),
  stance TEXT NOT NULL CHECK(stance IN ('SUPPORT','COUNTER','UNCERTAIN')),
  event_key TEXT NOT NULL,
  summary TEXT NOT NULL,
  subject_key TEXT,
  occurred_at TEXT,
  added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(trend_id,event_key,stance)
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
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  facts_json TEXT NOT NULL,
  claims_json TEXT NOT NULL,
  inferences_json TEXT NOT NULL,
  strongest_counter TEXT,
  evidence_gap TEXT,
  generated_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS theses (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  thesis TEXT NOT NULL,
  support_json TEXT,
  counter_json TEXT,
  falsification_signal TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','CONFIRMED','HELD')),
  generated_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS articles (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  thesis_id TEXT NOT NULL REFERENCES theses(id),
  title TEXT,
  outline TEXT,
  body TEXT,
  status TEXT NOT NULL DEFAULT 'TITLE' CHECK(status IN ('TITLE','OUTLINE','DRAFT','CHALLENGE','READY','ARCHIVED')),
  generated_by TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS article_reviews (
  id TEXT PRIMARY KEY,
  article_id TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  factual_issues TEXT,
  reasoning_issues TEXT,
  strongest_counter TEXT,
  headline_risk TEXT,
  verdict TEXT,
  generated_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS judgement_ledger (
  id TEXT PRIMARY KEY,
  trend_id TEXT REFERENCES trends(id),
  thesis_id TEXT REFERENCES theses(id),
  judgement TEXT NOT NULL,
  horizon TEXT NOT NULL,
  falsification_signal TEXT,
  review_at TEXT,
  result TEXT CHECK(result IN ('CORRECT','DIRECTIONALLY_RIGHT','PARTIAL','WRONG','UNKNOWN')),
  reviewed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  run_type TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  stats_json TEXT,
  error TEXT
);
