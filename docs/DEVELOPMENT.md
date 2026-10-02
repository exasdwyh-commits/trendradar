# Development

## Layout & tooling

* Python ≥ 3.11, `pip install -e ".[dev]"`; lint/format with `ruff` (line length 110); tests with `pytest` (`pythonpath = src`).
* Frontend: React 19 + TypeScript + Vite in `frontend/`; `npm run dev` proxies `/api` to `:8787`; `npm run build` emits `frontend/dist`, which the API serves.
* Configuration: `.env` (secrets/runtime) and `config/settings.yml` (thresholds/weights) + `config/sources.yml` (source registry).

## Common commands

```bash
make install        # deps
make seed-demo      # offline end-to-end run on fixtures
make dev            # build UI + serve with reload
make test / lint
trendradar daily --mock-only      # pipeline on mock adapters only
trendradar brief --mock-only      # refresh story sources + rebuild today's 简报, print it
trendradar explore "x" --mock-only
```

## Tests

Windows 的日常启动与前端入口规划见 [日常创作指南](DAILY_WRITING.md)。启动器入口是 `scripts/launch.py`，只启动本地 API/UI；前端源文件变化时构建，无变化时复用。`/api/studio/overview` 为首页提供有数量限制的只读摘要。

```powershell
.\.venv\Scripts\python.exe scripts/launch.py --check
.\.venv\Scripts\python.exe scripts/launch.py --smoke-test --port 8799 --no-browser
```

Smoke test 需要一个空闲端口，使用临时数据库、关闭模型配置，检查 health、工作台摘要和前端 HTML 后退出；已有服务的复用检查不会新建实例。

| File | Covers |
|---|---|
| `tests/test_adapters.py` | registry, mock adapters, Product Hunt mock trending/search, HN payload mapping (no network), effective mode sync |
| `tests/test_normalize.py` | URL canonicalisation, content hash, simhash distances, pain-lexicon fixture separation |
| `tests/test_dedup.py` | signal dedup layers, product domain aliases |
| `tests/test_providers.py` | local embedding determinism, rule classifier personas, FixtureLLM dispatch |
| `tests/test_clustering.py` | demo signals → 3 pure clusters, idempotency, live/mock never mixed |
| `tests/test_scoring.py` | competition asymmetry, demand monotonicity, final formula, unavailable judgement |
| `tests/test_pipeline.py` | full seed run: 3 grounded opportunities, re-run idempotency, lifecycle |
| `tests/test_api.py` | every endpoint against a seeded database (TestClient) |
| `tests/test_studio.py` | 写作台: v2→v3 migration upgrade, story assessment + brief, brief actions, versions/restore, materials, AI actions (fixture, number guard, 503 for live), variants/export/publications |
| `tests/test_workbench.py` | read-only home overview, complete counts, unfinished resume, archived material/document handling |
| `tests/test_launcher.py` | launcher preflight, build invalidation, port ownership and reuse |
| `tests/test_writing_agent.py` | Agent checkpoints, resumable execution, source changes, leases, atomic adoption and offline demo |

Tests never call external APIs or models; `FixtureLLM` and the local embedding are used.
写作台查询的离线性能基准和构建体积对比见 [性能与稳定性](PERFORMANCE.md)。
Model credentials are isolated from the developer's `.env`. Frontend regression tests run with `cd frontend && npm test` and cover save ordering, drafts after navigation, failed saves, AI save ordering and Markdown HTML sanitization; CI runs them alongside the frontend build.

## Fixtures

* `src/trendradar/sources/mock/fixtures/demand_signals.json` — 34 signals (29 pain + 5 noise) for the three demo cases with `created_days_ago` offsets.
* `products.json` — 16 fictional products (names are invented; never treat them as real market data).
* `analysis_fixtures.json` — canned classification/labels/analysis/brief per case, resolved by external-id overlap.

## Migrations

Add `src/trendradar/db/migrations/000N_name.sql`; they are applied in order on start (`db/migrate.py`). Keep them additive.

## Style rules that matter here

* Business logic never imports raw source payloads — only `RawSignal`/`RawProduct`.
* Never write a derived object without `origin`/`data_mode`.
* Model output is data, not truth: validate with pydantic, ground ids and quotes, record `generated_by`.
* Prefer deterministic code for anything countable; ask a model only for judgement.

## Adding a business (story) source

Add an entry to `config/sources.yml` with `kind: story`, `adapter: rss` (feed) or `adapter: html` (listing page +
article extraction, `config.include` regex for article paths), plus `lane / role / tier` metadata. `trendradar init`
registers it; enable/disable in the UI. Stories are assessed by FAST_MODEL (rule fallback) and surface in 简报 the next refresh.
