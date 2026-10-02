# Source adapters

Adapters live in `src/trendradar/sources/` and implement `BaseAdapter`:

```python
class BaseAdapter:
    adapter_id: str            # implementation id used in config/sources.yml
    type: "demand" | "supply"
    mode: "live" | "mock"      # effective mode (a live adapter may auto-mock without credentials)
    def search(self, query: SearchQuery) -> FetchResult           # on-demand (Explore, supply expansion)
    def fetch_latest(self) -> FetchResult                         # scheduled collection
    def fetch_trending(self, window: "7d"|"30d"|"month") -> FetchResult   # supply only
    def health(self) -> AdapterHealth
```

`FetchResult` carries `signals: list[RawSignal]`, `products: list[RawProduct]`, `warnings`. Everything downstream only sees these two models.

| id (sources.yml) | adapter | kind | auth | notes |
|---|---|---|---|---|
| `hn` | `hackernews` | demand | none | Algolia search API: comments + stories per query, `created_at_i` window. Primary keyless live source. |
| `github-issues` | `github_issues` | demand | optional `GITHUB_TOKEN` | Issue search sorted by reactions; issue-template boilerplate is stripped. |
| `reddit` | `reddit` | demand | `REDDIT_ENABLED=true`, `REDDIT_USER_AGENT` | Public JSON search per subreddit; disabled by default to respect API policy. |
| `producthunt` | `producthunt` | supply | `PRODUCTHUNT_TOKEN` | GraphQL v2; auto-mock without token. See PRODUCT_HUNT_INTEGRATION.md. |
| `github-repos` | `github_repos` | supply | optional token | Repository search; stars → votes, open issues → comments. |
| `rss` | `rss` | demand | none | Any feed; config `feeds: [...]`. |
| `mock-reddit`, `mock-hn`, `mock-github` | `mock` | demand | none | Bundled fixtures for the three demo cases + noise rows. |

## Adding a source

1. Create `sources/<name>.py` with a `BaseAdapter` subclass; map the raw payload to `RawSignal`/`RawProduct` (stable `external_id`, canonical `url`, `created_at`, engagement, `origin="live"`).
2. Register it in `sources/registry.py::ADAPTERS`.
3. Add an entry to `config/sources.yml` (`id`, `name`, `adapter`, `kind`, `mode`, `enabled`, `reliability`, `max_per_round`, `window_days`, plus adapter-specific keys such as `queries`, `subreddits`, `topics`, `feeds`).
4. Add a fixture-based test in `tests/test_adapters.py` (map a canned payload; no network in tests).

Adapters must never raise for a single bad item; wrap the whole fetch in `SourceError` only when the source is unusable.
`reliability` (0–100) is stored with the source and available to scoring; `max_per_round` bounds every fetch.

## Enabling / disabling

`enabled` in `sources.yml` seeds the `sources` table on first sync. From then on the **database value wins**: toggles from
the Sources page (`POST /api/sources/{id}/toggle`) survive restarts and are respected by `daily`, `collect` and Explore
(`registry.enabled_adapters`). Sources removed from the YAML are disabled automatically.

## Business story sources (`kind: story`)

Since v4.0 the registry also carries **story** sources for the 简报 (business news: AI 商业化 / 产业与利润池 / 公司与战略 /
商业模式 / 全球化与中国映射). They reuse the same ingestion, dedup and health machinery but are excluded from pain
classification and clustering; each new item receives a `story_assessment` instead (see `docs/CONTENT_STUDIO.md`).

* `adapter: rss` — feed URL (`url`), full-text extraction is attempted for short entries (`sources/article.py`).
* `adapter: html` — a listing page (`url`) with optional `include` regex for article paths; same-site links are discovered,
  each article fetched once and reduced to title / summary / content / published / author (`HtmlListAdapter`).
* Extra per-source metadata: `lane` (default lane for the assessment), `role` (primary / supporting / official),
  `tier` (1 = first-party or top-tier publication … 4 = aggregator) — used by the rule-based fallback score.
* `mock-stories` (adapter `mock`, fixtures `story_signals.json`) provides the six offline demo stories.

`config/sources.yml` ships 45 story sources; several are `enabled: false` by default because their sites are slow or
unstable — switch them on from the 信源 page when you want them.
