# Architecture

TrendRadar 写作台 is a single Python service (FastAPI + SQLite) with a React/TypeScript UI. Everything lives in
`src/trendradar/` and is organised along the data flow, not by technical layer. Since v4.0 the **creation platform**
(`studio/`) is the core product and the opportunity radar is a data source for it; see [CONTENT_STUDIO.md](CONTENT_STUDIO.md).

```
sources/        SourceAdapter plugins → RawSignal / RawProduct (unified models, business logic never sees raw formats)
ingestion/      store (4-layer dedup, aliases) + parallel collection runner + source health
normalize/      text cleaning, canonical URLs, simhash, pain lexicon (rule_score)
providers/      llm (slots, budget, telemetry, FixtureLLM), embeddings (API + local fallback), classifier (LLM / rule)
analysis/       classify stage (cost pyramid step 2)
clustering/     vector index, pain clusters (persona+origin blocked leader clustering), solution clusters
trends/         daily snapshots → velocity / acceleration / stage
market/         semantic product search, supply expansion, product insights, competition profile
scoring/        deterministic + judgement dimensions, final score
opportunities/  analyze_cluster (ANALYSIS call, grounding), lifecycle, Today selection, builder brief
graph/          `edges` relation table (opportunity graph)
explore/ ask/   query → market map; NL question → DB-grounded answer
studio/         creation platform: stories (business-story assessment), brief (one-page digest), materials,
                documents (autosave/versions/restore), ai (grounded writing actions), publishing (variants, export, ledger)
jobs/           daily pipeline orchestration, brief refresh, demo seed, daily brief, scheduler
api/            FastAPI app + read models (+ api/studio.py router); web.py ASGI entry; cli.py
db/             connection, migrations (SQL files, applied in order)
core/           settings (.env), pipeline config (config/settings.yml), errors, ids, logging, time
```

## Key decisions

| Decision | Why |
|---|---|
| SQLite + numpy for vectors | Zero-ops local V1. Vectors are BLOBs keyed by `(item, model)`; cosine over an in-memory matrix is fine for <100k rows. Swapping to pgvector later touches only `clustering/index.py`. |
| Relation table instead of a graph DB | `edges(from_type, from_id, relation, to_type, to_id, weight)` gives us the Opportunity Graph (pain → cluster → opportunity → product → persona) with plain SQL; exportable later. |
| One opportunity per pain cluster | Prevents the "one card per post" failure mode. Re-analysis updates the card in place (`version++`), human status is preserved. |
| Cost pyramid | rule filter (free) → FAST classifier (20 signals/call) → embeddings → clustering → evidence gate → one ANALYSIS call per cluster. Only clusters with ≥3 signals and (≥2 sources or velocity ≥3) reach the reasoning model. |
| Provider slots | `FAST_MODEL`, `ANALYSIS_MODEL`, `EMBEDDING_MODEL`, all OpenAI-compatible. The classifier is an interface (`RuleClassifier` today, LLM-backed when a slot is configured) so it can later be a local model. |
| Live / Mock separation | `origin` on signals/products, `data_mode` on clusters/opportunities. Dedup and clustering are blocked by origin; the fixture "model" only ever answers for mock data; live clusters without a real model are marked `analysis_status='skipped'`. |
| Grounding | Model outputs must reference ids we sent; quotes must appear verbatim in the source text or they are dropped; competitors in a brief must be products we indexed. |
| Explore sessions | Session-scoped clusters (`pain_clusters.session_id`) so ad-hoc exploration never pollutes the global radar. |
| Story sources are signals, not pains | Business stories (`sources.kind='story'`) share ingestion/dedup with demand signals but are excluded from pain classification/clustering; they get a `story_assessment` (lane, 值得写的程度, why, angles) instead. |
| Documents carry evidence | A draft is bound to materials; `data_mode` is derived from those materials, and the AI helper is fixture-only for all-demo drafts and refuses (503) for live drafts without a writing model. |
| Versions are full snapshots | Simple, diff-free restore; autosave snapshots at most every 15 min, manual/AI/restore always. |

## Request/Job flow

* `trendradar serve` runs FastAPI; each request opens its own SQLite connection (WAL, FK on).
* Long jobs (`daily`, `collect`, `seed`, `brief`) run in a background thread started from `POST /api/jobs/run`; one at a time.
* `trendradar daemon` / `serve --scheduler` runs the daily pipeline at `DAILY_HOUR` in `TIMEZONE`.

## Data model (39 tables, see `db/migrations/0001_init.sql` … `0003_studio.sql`)

signals → signal_classifications, signal_embeddings, pain_signals · pain_clusters(+items) · products → product_embeddings, product_insights, product_clusters(+items) ·
trend_snapshots · competition_profiles · opportunities → opportunity_scores, opportunity_status_log, evidence, builder_briefs · edges · personas ·
sources, source_health · jobs, job_steps, ai_runs · reports · explore_sessions, ask_sessions · today_picks (0002).
story_assessments · brief_items · materials · documents → document_versions, document_materials, platform_variants, publications, ai_actions (0003).
