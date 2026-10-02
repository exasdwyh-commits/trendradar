# Data pipeline

`jobs/pipeline.py::run_daily` executes these steps, each recorded in `job_steps` with counts:

| # | Step | Module | What happens |
|---|---|---|---|
| 1 | collect | ingestion.runner | All enabled adapters fetch in parallel. `store_signal` applies dedup layers 1–3; `store_product` upserts and resolves domain aliases. Source health is updated. |
| 2 | classify | analysis.classify | Signals with `rule_score < 0.15` are `filtered`. The rest go to the classifier in batches of 20 (FAST model when configured, rule classifier otherwise): `is_pain`, relevance 0–100, persona, category. |
| 3 | embed | clustering | Pain signals with relevance ≥ 40 and all products are embedded (`EMBEDDING_MODEL` or local hashed n-grams). |
| 4 | cluster | clustering.pain_clusters | Incremental leader clustering, blocked by `(origin, persona)`; assign to the best centroid if cosine ≥ τ (0.45 API / 0.10 local), else new cluster. Members with cosine ≥ 0.97 to an existing member are semantic duplicates (layer 4). |
| 5 | label | clustering.pain_clusters | Clusters with ≥2 signals that still carry a rule label get a FAST-model label/summary/persona/category. |
| 6 | trends | trends.velocity | Daily snapshots per cluster; `velocity = mean/day(last 7d) ÷ max(mean/day(prior 21d), 0.4)`, acceleration = Δvelocity week over week; stage emerging / growing / stable / fading / new. |
| 7 | solution_clusters | clustering.solution_clusters | Products grouped into solution clusters (density, maturity, votes). |
| 8 | gate | jobs.pipeline | Clusters with `signal_count ≥ 3 ∧ (source_count ≥ 2 ∨ velocity ≥ 3)` and enough new evidence since the last analysis; capped at `max_clusters_analyzed_per_run`. |
| 9 | competition | market.competition | Per gated cluster: semantic search over the product index (+ on-demand Product Hunt / GitHub expansion for live clusters) → competitors, product insights (pros/cons/complaints derived from comments), density, maturity, ratings, pricing distribution, `solved_by` edges. |
| 10 | analyze | opportunities.generator | One ANALYSIS call per gated cluster → pain_signals (grounded quotes), cluster relabel, opportunity card, judgement scores. Deterministic dimensions are computed in code. Evidence rows + graph edges written. |
| 11 | rescore | opportunities.generator | Deterministic dimensions refreshed for every opportunity (demand/growth/competition/confidence) without model calls. |
| 12 | today | opportunities.today | Picks up to 5 with score ≥ 70 and confidence ≥ 60, preferring persona/category diversity. |
| 13 | brief | jobs.brief | Markdown daily brief stored in `reports`. |
| 14 | stories | studio.stories | Business stories (`kind: story` sources, skipped by the demand classifier) get a `story_assessments` row: lane, business value 0–100, why-it-matters, angles — FAST model when configured, otherwise a transparent rule score (`method='rule'`). |
| 15 | digest | studio.brief | Builds today's 简报 (`brief_items`): top stories (≥55 value, ≤3 per source when many feeds), pain clusters (velocity/size), opportunities (score/confidence). Idempotent: re-running keeps ids/status, prunes un-acted stale rows, and drops demo fixtures from a section as soon as live items exist. |

### Brief-only refresh

`run_brief_refresh(conn, mock_only)` (`trendradar brief`, UI button 抓取并刷新, `POST /api/jobs/run {"type":"brief"}`, job_type `brief`) runs only **collect (story sources) → stories → digest** — no classify/cluster/analyze — so the 简报 stays fresh without the full daily cost. Steps 14–15 also run at the end of `run_daily` and `seed_demo`.

## Dedup layers

1. Canonical URL (tracking params stripped, sorted query, `www.`/scheme normalised) across sources.
2. Content hash (normalised title + body).
3. Simhash (64-bit, word + bigram features; CJK runs contribute character bigrams) within Hamming distance 7 — catches reposts with small edits. Texts too short to fingerprint store simhash 0 and are only matched exactly.
4. Semantic (cosine ≥ 0.97 to a member of the target cluster).
5. Product aliases by website domain (`products.alias_of` + `alias_of` edge).

All layers are scoped to the same `origin`, so demo fixtures never absorb live posts.

## Explore flow

`explore.engine.run_explore`: on-demand search on demand adapters → store → semantic recall from the DB (relative threshold to the best hit) → classify + embed new signals → **session-scoped** clustering → label → supply expansion + product search → per-cluster relevance, coverage (`served` ≥2 close products, `underserved` 1, `unserved` 0) and competitor complaints → opportunity draft for the most relevant cluster that passes the evidence gate → optional overview text. Old sessions are pruned with `cleanup_sessions`.

## Ask flow

`ask.engine.ask`: FAST plan (filters/keywords) → SQL + centroid-similarity ranking over stored opportunities → ANALYSIS answer restricted to the retrieved material with `[opp:id]` citations → stored in `ask_sessions`. No web access.

## Failure behaviour

* A failing source only lowers `sources_ok`; the run continues (`partial` if a step fails).
* Model errors are retried with backoff (429/5xx), then recorded in `ai_runs.error`; the cluster keeps `analysis_status='failed'` and is retried next run.
* Budget/call limits raise `BudgetExceeded` (HTTP 429 in API context) and skip remaining model work.
