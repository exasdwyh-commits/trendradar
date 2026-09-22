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
  tier INTEGER NOT NULL DEFAULT 3,
  reliability INTEGER NOT NULL DEFAULT 70,
  business_value INTEGER NOT NULL DEFAULT 65,
  noise INTEGER NOT NULL DEFAULT 30,
  accuracy INTEGER NOT NULL DEFAULT 70,
  window_days INTEGER,
  scan_limit INTEGER,
  max_per_round INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_health (
  source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  last_attempt_at TEXT,
  last_success_at TEXT,
  last_error TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_item_count INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER
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
  PRIMARY KEY(cluster_id, intelligence_id),
  UNIQUE(intelligence_id)
);

CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL UNIQUE REFERENCES story_clusters(id),
  title TEXT NOT NULL,
  event_summary TEXT,
  what_changed TEXT,
  why_now TEXT,
  profit_pool TEXT,
  who_benefits TEXT,
  who_loses TEXT,
  china_mapping TEXT,
  strongest_counter TEXT,
  evidence_gap TEXT,
  cognition_score REAL NOT NULL DEFAULT 0,
  content_score REAL NOT NULL DEFAULT 0,
  action TEXT NOT NULL DEFAULT 'TRACK' CHECK(action IN ('WRITE','TRACK','HOLD','SKIP')),
  cognition_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(cognition_status IN ('PENDING','DONE','FAILED','SKIPPED')),
  generated_by TEXT NOT NULL DEFAULT 'rule',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidates_action ON candidates(action, content_score DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_cognition ON candidates(cognition_status, cognition_score DESC);

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

CREATE TABLE IF NOT EXISTS world_model_updates (
  id TEXT PRIMARY KEY,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  strengthened_json TEXT NOT NULL DEFAULT '[]',
  weakened_json TEXT NOT NULL DEFAULT '[]',
  diverging_json TEXT NOT NULL DEFAULT '[]',
  new_json TEXT NOT NULL DEFAULT '[]',
  summary TEXT,
  generated_by TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS research_items (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES research(id) ON DELETE CASCADE,
  candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('FACT','CLAIM','INFER')),
  text TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research_item_sources (
  research_item_id TEXT NOT NULL REFERENCES research_items(id) ON DELETE CASCADE,
  intelligence_id TEXT NOT NULL REFERENCES intelligence(id) ON DELETE CASCADE,
  PRIMARY KEY(research_item_id, intelligence_id)
);

CREATE INDEX IF NOT EXISTS idx_research_items_research ON research_items(research_id, kind);
CREATE INDEX IF NOT EXISTS idx_research_item_sources_intel ON research_item_sources(intelligence_id);

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

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  article_id TEXT UNIQUE REFERENCES articles(id) ON DELETE SET NULL,
  candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
  thesis_id TEXT REFERENCES theses(id) ON DELETE SET NULL,
  title TEXT NOT NULL DEFAULT '未命名文章',
  status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('IDEA','DRAFT','REVIEW','READY','ARCHIVED')),
  current_version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_versions (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  title TEXT NOT NULL,
  content_json TEXT NOT NULL DEFAULT '{}',
  content_html TEXT NOT NULL DEFAULT '',
  plain_text TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'MANUAL' CHECK(source IN ('AI_DRAFT','MANUAL','AI_EDIT','IMPORT','RESTORE')),
  note TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(document_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_doc_versions ON document_versions(document_id, version_number DESC);

CREATE TABLE IF NOT EXISTS evidence_links (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  intelligence_id TEXT NOT NULL REFERENCES intelligence(id) ON DELETE CASCADE,
  text_anchor TEXT,
  relation TEXT NOT NULL DEFAULT 'SUPPORT' CHECK(relation IN ('SUPPORT','COUNTER','CONTEXT')),
  note TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(document_id, intelligence_id, text_anchor)
);

CREATE TABLE IF NOT EXISTS media_assets (
  id TEXT PRIMARY KEY,
  document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
  asset_type TEXT NOT NULL CHECK(asset_type IN ('COVER','PHOTO','DATA_CHART','DIAGRAM','SCREENSHOT','ILLUSTRATION')),
  role TEXT NOT NULL DEFAULT 'INLINE' CHECK(role IN ('COVER','INLINE','REFERENCE')),
  title TEXT NOT NULL,
  brief TEXT,
  placement TEXT,
  prompt TEXT,
  aspect_ratio TEXT,
  source_url TEXT,
  local_path TEXT,
  status TEXT NOT NULL DEFAULT 'SUGGESTED' CHECK(status IN ('SUGGESTED','READY','USED','REJECTED')),
  generated_by TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS platform_variants (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  platform TEXT NOT NULL CHECK(platform IN ('WECHAT','XIAOHONGSHU','ZHIHU','TOUTIAO','X')),
  title TEXT NOT NULL,
  content_text TEXT NOT NULL DEFAULT '',
  content_html TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','READY','PUBLISHED','ARCHIVED')),
  generated_by TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_variants_document ON platform_variants(document_id, platform);

CREATE TABLE IF NOT EXISTS publications (
  id TEXT PRIMARY KEY,
  variant_id TEXT NOT NULL REFERENCES platform_variants(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'READY' CHECK(status IN ('READY','SCHEDULED','PUBLISHED','FAILED')),
  scheduled_at TEXT,
  published_at TEXT,
  external_url TEXT,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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


-- AI runtime observability. Model failures and throttling must be visible rather than silent.
CREATE TABLE IF NOT EXISTS ai_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  task TEXT NOT NULL,
  slot TEXT NOT NULL,
  model TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  ok INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  attempts INTEGER NOT NULL DEFAULT 1,
  retries INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ai_runs_time ON ai_runs(run_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_runs_slot ON ai_runs(slot, run_at DESC);


-- Freeze each daily candidate pool so historical selection quality is reproducible.
CREATE TABLE IF NOT EXISTS candidate_runs (
  id TEXT PRIMARY KEY,
  pipeline_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'FROZEN',
  system_top3_json TEXT NOT NULL DEFAULT '[]',
  settings_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS candidate_run_items (
  run_id TEXT NOT NULL REFERENCES candidate_runs(id) ON DELETE CASCADE,
  candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  content_rank INTEGER,
  cognition_rank INTEGER,
  content_score REAL NOT NULL,
  cognition_score REAL NOT NULL,
  action TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  PRIMARY KEY(run_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_candidate_run_content ON candidate_run_items(run_id, content_rank);
CREATE INDEX IF NOT EXISTS idx_candidate_run_cognition ON candidate_run_items(run_id, cognition_rank);

-- Blind 10→3 evaluation: human choices are compared with the system only after submit.
CREATE TABLE IF NOT EXISTS blind_rounds (
  id TEXT PRIMARY KEY,
  candidate_run_id TEXT REFERENCES candidate_runs(id) ON DELETE SET NULL,
  round_date TEXT NOT NULL UNIQUE,
  system_top3_json TEXT NOT NULL,
  human_picks_json TEXT,
  hits INTEGER,
  submitted_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blind_items (
  round_id TEXT NOT NULL REFERENCES blind_rounds(id) ON DELETE CASCADE,
  candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  PRIMARY KEY(round_id, candidate_id)
);

-- Freeze the research state that existed when content was actually published.
CREATE TABLE IF NOT EXISTS content_snapshots (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  variant_id TEXT REFERENCES platform_variants(id) ON DELETE SET NULL,
  publication_id TEXT REFERENCES publications(id) ON DELETE SET NULL,
  candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
  thesis_id TEXT REFERENCES theses(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_content_snapshots_doc ON content_snapshots(document_id, created_at DESC);
