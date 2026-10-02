# Acceptance checklist

Run `make install && make seed-demo && make dev`, open http://127.0.0.1:8787.

| # | Criterion | How to verify |
|---|---|---|
| 1 | Clone → `.env` → install → dev works | README quick start; `pytest -q` green; CI workflow `ci.yml` |
| 2 | Today shows 1–5 high-quality opportunities or an honest empty state | Today page after seed: 1 pick (AI Coding Session Manager, score ≈77) + 2 "also on the radar" |
| 3 | Radar 7D/30D/90D with stages & velocity | Radar page: 3 clusters, one `emerging` |
| 4 | Explore query → market map with pains, products, gaps, draft | Explore presets; `trendradar explore "freelancer invoicing" --mock-only` |
| 5 | Opportunity card shows sub-scores with reasons + evidence with URLs/quotes | Detail page: "Why this score", pain evidence, evidence panel |
| 6 | Lifecycle transitions enforced | Detail actions; `POST /api/opportunities/{id}/status` returns 422 on illegal moves |
| 7 | Start product → builder brief with all 12 sections | Detail → Start product; `POST /api/opportunities/{id}/brief` |
| 8 | Ask answers only from DB with citations | Ask page; answers contain `[opp:id]` links |
| 9 | Product Hunt integration (trending, semantic search, competition profile) | `producthunt` adapter mock/live; competition tab shows density/maturity/rating/complaints/pricing |
| 10 | Dedup: URL / hash / simhash / semantic / product alias | `tests/test_dedup.py`, `tests/test_clustering.py`; seed re-run inserts 0 new signals |
| 11 | Live vs Mock labelled everywhere; never fabricated | Badges on cards, clusters, products, evidence; live clusters without a model are "not analysed" |
| 12 | Jobs page with per-step stats, AI calls, failures | Jobs page after seed |
| 13 | Sources page with health, mode, enable toggle, test | Sources page; `trendradar sources --test` |
| 14 | Settings shows model slots, embedding provider, usage/cost | Settings page |
| 15 | Daily job + scheduler + daily brief | `trendradar daily`, `serve --scheduler`, brief on Today |
| 16 | Three demo cases show Pain → Competition → Gap → Opportunity | Seeded cards: AI Coding Session Manager, Solo Freelancer Money Loop, Zero-Config Automation Recipes |
| 17 | Tests: adapters, normalization, dedup, scoring, generation, DB, API, integration | `pytest -q` (40 tests) |
| 18 | Docs complete | README + docs/* |

## 写作台 (v4.0, creation platform)

| # | Criterion | How to verify |
|---|---|---|
| S1 | 简报速览 is one page merging business stories + pain signals + opportunities, each with source / summary / why / angles | `/` after seed: 6 stories · 3 signals · 3 opportunities, all labelled 演示 |
| S2 | 延伸创作 opens a new draft with the material attached; 存为素材 / 忽略 work and persist | click on a card; `tests/test_studio.py::test_brief_extend_and_status` |
| S3 | Markdown editor with live preview, autosave, ⌘S named versions, restore | `/studio/:id`; 版本 tab; `test_document_versions_autosave_manual_restore` |
| S4 | AI: 选题角度 / 大纲 / 初稿 / 改写选中 / 起标题 / 平台版本, grounded in bound materials, unknown numbers flagged | AI 助手 tab on the demo draft (演示生成); live draft without model → 503 message |
| S5 | 公众号母稿 + 小红书 / 知乎 / 头条 / X versions; copy 公众号排版 HTML / plain text / .md download | 平台 tab; `GET /api/documents/{id}/export?fmt=html` |
| S6 | Publish ledger without platform APIs | 发布 tab → 记录发布; `/publish` matrix |
| S7 | Live/Mock labelled on brief items, materials, drafts, AI output | 演示 / 实时 badges; 演示生成 badge |
| S8 | Old databases upgrade in place | `test_migration_upgrades_v2_database`; `trendradar init` on a v2 DB prints schema v3 |
| S9 | UI in Chinese, radar pages kept as 扩展工具 | sidebar sections 扩展工具 / 系统 |
| S10 | `trendradar brief` refreshes story sources and prints the digest | `trendradar brief --mock-only` |

Known V1 limits (documented, not hidden): local hashed embeddings are a degraded fallback (persona-blocked clustering compensates); Product Hunt pros/cons/pricing are inferred from comments; Reddit is opt-in; no auth on the web UI.
