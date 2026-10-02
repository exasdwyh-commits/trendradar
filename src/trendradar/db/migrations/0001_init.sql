-- Opportunity Radar V1 schema.
-- Conventions: TEXT ids (sha256 prefix or uuid), ISO-8601 UTC timestamps, *_json columns hold JSON.
-- origin/data_mode ∈ live | mock | mixed is carried on every raw and derived object so the UI never
-- presents demo fixtures as real market data.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ───────────────────────── sources & health ─────────────────────────
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  adapter TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('demand','supply','hybrid')),
  mode TEXT NOT NULL DEFAULT 'live' CHECK(mode IN ('live','mock')),
  enabled INTEGER NOT NULL DEFAULT 1,
  reliability INTEGER NOT NULL DEFAULT 70,
  max_per_round INTEGER NOT NULL DEFAULT 100,
  config_json TEXT NOT NULL DEFAULT '{}',
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
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

-- ───────────────────────── demand side: signals ─────────────────────────
CREATE TABLE IF NOT EXISTS signals (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  adapter TEXT NOT NULL,
  external_id TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  author TEXT,
  author_id TEXT,
  lang TEXT,
  created_at TEXT,
  fetched_at TEXT NOT NULL,
  engagement_json TEXT NOT NULL DEFAULT '{}',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL,
  simhash INTEGER,
  origin TEXT NOT NULL DEFAULT 'live' CHECK(origin IN ('live','mock')),
  dedup_of TEXT REFERENCES signals(id),
  rule_score REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','filtered','classified','embedded','clustered','duplicate')),
  UNIQUE(source_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_signals_canonical ON signals(canonical_url);
CREATE INDEX IF NOT EXISTS idx_signals_hash ON signals(content_hash);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at DESC);

CREATE TABLE IF NOT EXISTS signal_classifications (
  signal_id TEXT PRIMARY KEY REFERENCES signals(id) ON DELETE CASCADE,
  classifier TEXT NOT NULL,             -- rule | llm | fixture | jev | local
  is_pain INTEGER NOT NULL DEFAULT 0,
  relevance REAL NOT NULL DEFAULT 0,    -- 0..100 relevance to software/tool opportunities
  persona TEXT,
  category TEXT,
  confidence REAL NOT NULL DEFAULT 0,
  reason TEXT,
  model TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS signal_embeddings (
  signal_id TEXT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL,
  PRIMARY KEY(signal_id, model)
);

CREATE TABLE IF NOT EXISTS pain_signals (
  id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL UNIQUE REFERENCES signals(id) ON DELETE CASCADE,
  cluster_id TEXT REFERENCES pain_clusters(id) ON DELETE SET NULL,
  problem TEXT NOT NULL,
  persona TEXT,
  context TEXT,
  severity REAL,                        -- 0..100
  frequency REAL,                       -- 0..100
  willingness_to_pay REAL,              -- 0..100
  existing_workaround TEXT,
  current_solution TEXT,
  friction_json TEXT NOT NULL DEFAULT '[]',
  evidence_quote TEXT,
  confidence REAL NOT NULL DEFAULT 0,
  generated_by TEXT NOT NULL,           -- model name | fixture | rule
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS pain_clusters (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  summary TEXT,
  persona TEXT,
  category TEXT,
  signal_count INTEGER NOT NULL DEFAULT 0,
  unique_users INTEGER NOT NULL DEFAULT 0,
  source_count INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT,
  last_seen TEXT,
  velocity REAL NOT NULL DEFAULT 0,
  acceleration REAL NOT NULL DEFAULT 0,
  stage TEXT NOT NULL DEFAULT 'new' CHECK(stage IN ('new','emerging','growing','stable','fading')),
  data_mode TEXT NOT NULL DEFAULT 'live' CHECK(data_mode IN ('live','mock','mixed')),
  centroid BLOB,
  centroid_model TEXT,
  label_source TEXT NOT NULL DEFAULT 'rule',
  analysis_status TEXT NOT NULL DEFAULT 'pending' CHECK(analysis_status IN ('pending','gated','done','failed','skipped')),
  analysis_error TEXT,
  session_id TEXT,                      -- explore session scope; NULL = global corpus
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_pain_clusters_stage ON pain_clusters(stage, signal_count DESC);

CREATE TABLE IF NOT EXISTS pain_cluster_items (
  cluster_id TEXT NOT NULL REFERENCES pain_clusters(id) ON DELETE CASCADE,
  signal_id TEXT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  similarity REAL NOT NULL DEFAULT 0,
  PRIMARY KEY(cluster_id, signal_id)
);
CREATE INDEX IF NOT EXISTS idx_pci_signal ON pain_cluster_items(signal_id);

-- ───────────────────────── supply side: products ─────────────────────────
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  adapter TEXT NOT NULL,
  external_id TEXT NOT NULL,
  name TEXT NOT NULL,
  slug TEXT,
  tagline TEXT,
  description TEXT,
  url TEXT NOT NULL,
  website TEXT,
  domain TEXT,
  categories_json TEXT NOT NULL DEFAULT '[]',
  votes INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  rating REAL,
  review_count INTEGER NOT NULL DEFAULT 0,
  launched_at TEXT,
  makers_json TEXT NOT NULL DEFAULT '[]',
  credibility_json TEXT NOT NULL DEFAULT '{}',
  pricing TEXT,
  pricing_origin TEXT,                   -- api | inferred | unknown
  origin TEXT NOT NULL DEFAULT 'live' CHECK(origin IN ('live','mock')),
  alias_of TEXT REFERENCES products(id),
  raw_json TEXT NOT NULL DEFAULT '{}',
  fetched_at TEXT NOT NULL,
  UNIQUE(source_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_products_domain ON products(domain);
CREATE INDEX IF NOT EXISTS idx_products_launched ON products(launched_at DESC);

CREATE TABLE IF NOT EXISTS product_embeddings (
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL,
  PRIMARY KEY(product_id, model)
);

CREATE TABLE IF NOT EXISTS product_insights (
  product_id TEXT PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
  pros_json TEXT NOT NULL DEFAULT '[]',
  cons_json TEXT NOT NULL DEFAULT '[]',
  review_summary TEXT,
  complaints_json TEXT NOT NULL DEFAULT '[]',
  derived_from TEXT NOT NULL,            -- comments | reviews | fixture
  sample_size INTEGER NOT NULL DEFAULT 0,
  generated_by TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS product_clusters (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  summary TEXT,
  product_count INTEGER NOT NULL DEFAULT 0,
  new_90d INTEGER NOT NULL DEFAULT 0,
  avg_rating REAL,
  total_votes INTEGER NOT NULL DEFAULT 0,
  maturity TEXT,
  data_mode TEXT NOT NULL DEFAULT 'live',
  centroid BLOB,
  centroid_model TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS product_cluster_items (
  cluster_id TEXT NOT NULL REFERENCES product_clusters(id) ON DELETE CASCADE,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  similarity REAL NOT NULL DEFAULT 0,
  PRIMARY KEY(cluster_id, product_id),
  UNIQUE(product_id)
);

-- ───────────────────────── trends ─────────────────────────
CREATE TABLE IF NOT EXISTS trend_snapshots (
  subject_type TEXT NOT NULL,            -- pain_cluster | product_cluster | category
  subject_id TEXT NOT NULL,
  day TEXT NOT NULL,                     -- YYYY-MM-DD (UTC)
  new_items INTEGER NOT NULL DEFAULT 0,
  cum_items INTEGER NOT NULL DEFAULT 0,
  unique_sources INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(subject_type, subject_id, day)
);

-- ───────────────────────── market / competition ─────────────────────────
CREATE TABLE IF NOT EXISTS competition_profiles (
  id TEXT PRIMARY KEY,
  pain_cluster_id TEXT NOT NULL UNIQUE REFERENCES pain_clusters(id) ON DELETE CASCADE,
  density REAL NOT NULL DEFAULT 0,       -- 0..100
  maturity REAL NOT NULL DEFAULT 0,      -- 0..100
  avg_rating REAL,
  review_volume INTEGER NOT NULL DEFAULT 0,
  recent_launches_90d INTEGER NOT NULL DEFAULT 0,
  competitor_count INTEGER NOT NULL DEFAULT 0,
  common_features_json TEXT NOT NULL DEFAULT '[]',
  common_complaints_json TEXT NOT NULL DEFAULT '[]',
  pricing_distribution_json TEXT NOT NULL DEFAULT '{}',
  competitors_json TEXT NOT NULL DEFAULT '[]',  -- [{product_id, similarity}]
  data_mode TEXT NOT NULL DEFAULT 'live',
  computed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────── opportunities ─────────────────────────
CREATE TABLE IF NOT EXISTS opportunities (
  id TEXT PRIMARY KEY,
  pain_cluster_id TEXT NOT NULL UNIQUE REFERENCES pain_clusters(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  target_user TEXT,
  core_pain TEXT,
  proposed_solution TEXT,
  wedge TEXT,
  monetization TEXT,
  distribution TEXT,
  build_type TEXT,                       -- web | mac | chrome_extension | cli | api | mobile | plugin
  build_difficulty TEXT,                 -- weekend | 2_weeks | 1_3_months | 3_plus_months
  why_now TEXT,
  competitor_weakness TEXT,
  risks_json TEXT NOT NULL DEFAULT '[]',
  next_action TEXT,
  status TEXT NOT NULL DEFAULT 'discovered' CHECK(status IN (
    'discovered','watching','promising','researching','validated','building','rejected','archived')),
  opportunity_score REAL NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0,
  data_mode TEXT NOT NULL DEFAULT 'live' CHECK(data_mode IN ('live','mock','mixed')),
  version INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  signal_count INTEGER NOT NULL DEFAULT 0,
  growth REAL NOT NULL DEFAULT 0,
  generated_by TEXT NOT NULL,
  session_id TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_opportunities_score ON opportunities(status, opportunity_score DESC);

CREATE TABLE IF NOT EXISTS opportunity_scores (
  opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  dimension TEXT NOT NULL,               -- pain demand growth competition gap monetization build_ease distribution confidence
  score REAL NOT NULL,
  reason TEXT,
  confidence REAL NOT NULL DEFAULT 0,
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  method TEXT NOT NULL,                  -- deterministic | model | blended | fixture
  scoring_version TEXT NOT NULL,
  computed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY(opportunity_id, dimension)
);

CREATE TABLE IF NOT EXISTS opportunity_status_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  from_status TEXT,
  to_status TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ───────────────────────── evidence & graph ─────────────────────────
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL,            -- opportunity | pain_cluster | competition_profile
  subject_id TEXT NOT NULL,
  kind TEXT NOT NULL,                    -- pain | complaint | competitor | trend | workaround
  signal_id TEXT REFERENCES signals(id) ON DELETE CASCADE,
  product_id TEXT REFERENCES products(id) ON DELETE CASCADE,
  source_id TEXT,
  quote TEXT,
  url TEXT,
  occurred_at TEXT,
  origin TEXT NOT NULL DEFAULT 'live',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence(subject_type, subject_id);

CREATE TABLE IF NOT EXISTS edges (
  id TEXT PRIMARY KEY,
  from_type TEXT NOT NULL,
  from_id TEXT NOT NULL,
  relation TEXT NOT NULL,                -- affects solved_by has_complaint belongs_to related_to derived_from competes_with supported_by alias_of
  to_type TEXT NOT NULL,
  to_id TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(from_type, from_id, relation, to_type, to_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_type, from_id, relation);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_type, to_id, relation);

CREATE TABLE IF NOT EXISTS personas (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT
);

-- ───────────────────────── jobs / observability ─────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,                -- daily | explore | collect | seed
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('running','success','partial','failed')),
  stats_json TEXT NOT NULL DEFAULT '{}',
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at DESC);

CREATE TABLE IF NOT EXISTS job_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  step TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('running','success','skipped','failed')),
  counts_json TEXT NOT NULL DEFAULT '{}',
  error TEXT
);

CREATE TABLE IF NOT EXISTS ai_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
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
  http_status INTEGER,
  job_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_runs_time ON ai_runs(run_at DESC);

-- ───────────────────────── reports / sessions ─────────────────────────
CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,
  day TEXT NOT NULL,
  kind TEXT NOT NULL,                    -- daily_brief
  content_md TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(day, kind)
);

CREATE TABLE IF NOT EXISTS builder_briefs (
  id TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  content_json TEXT NOT NULL,
  generated_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_builder_opp ON builder_briefs(opportunity_id, created_at DESC);

CREATE TABLE IF NOT EXISTS explore_sessions (
  id TEXT PRIMARY KEY,
  query TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','done','failed')),
  result_json TEXT NOT NULL DEFAULT '{}',
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  expires_at TEXT
);

CREATE TABLE IF NOT EXISTS ask_sessions (
  id TEXT PRIMARY KEY,
  question TEXT NOT NULL,
  plan_json TEXT NOT NULL DEFAULT '{}',
  answer_md TEXT,
  citations_json TEXT NOT NULL DEFAULT '[]',
  generated_by TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
