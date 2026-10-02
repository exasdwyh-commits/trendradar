# TrendRadar → Opportunity Radar V1：架构与执行方案

> 目标：在现有 TrendRadar 3.1 仓库基础上，交付一个可本地运行、可持续采集、可分析、可展示商业机会的 V1。
> 原则：复用基础设施，移除无关产品线，不为重构而重构。

---

## 0. 现状盘点（基于实际代码检查）

### 0.1 技术栈

| 层 | 现状 | 结论 |
|---|---|---|
| 后端 | Python 3.11+ / FastAPI / uvicorn / SQLite (WAL) / httpx / feedparser / bs4 | **保留**。规格要求"沿用当前技术栈优先"，后端迁 TS 属于推倒重做 |
| 前端 | React 19 + TypeScript + Vite 6 + TipTap + lucide-react，单文件路由（useState 切换视图） | 保留脚手架（Vite 代理、api.ts、构建链），页面重做，移除 TipTap |
| 数据库 | 单 `schema.sql` + `db.py` 里手写 `_ensure_column` 前向迁移 | 换成版本化迁移文件 |
| 任务 | `scheduler.daemon()` 每日 13:00 Asia/Shanghai，漏跑补跑；`runs` 表 | **保留** |
| AI | `llm.py`：5 个 OpenAI 兼容槽位、JSON 模式、429/5xx 有界重试、`ai_runs` 遥测、24h 成本/次数熔断 | **保留并扩展**（加 embeddings、改槽位命名） |
| 测试 | 51 个 pytest，全部通过；含"故意破坏时必须变红"的 falsification 测试 | 保留基础设施类测试，删除内容线测试 |
| CI | GitHub Actions：pytest + CLI smoke | 保留，增加 lint / typecheck / 前端 build |

### 0.2 资产分级

**A. 直接复用（迁移到新目录即可）**

| 文件 | 复用点 | 去向 |
|---|---|---|
| `llm.py` | 槽位加载、`chat_json`、重试、遥测、预算熔断 | `providers/llm.py` |
| `collect.py` | `canonicalize_url`、`title_hash`、`parse_datetime`、`_get_with_retry`、RSS/HTML 采集、正文抽取 | `normalize/url.py`、`sources/rss.py` |
| `pipeline.collect_all` | ThreadPool 并发采集 + `source_health` + 失败统计 | `ingestion/runner.py` |
| `cluster.py` | 词法相似度（Jaccard / bigram / 实体锚点） | `normalize/dedup.py`（仅用于近重复检测） |
| `scheduler.py` | 每日守护 + 补跑 | `jobs/scheduler.py` |
| `grounding.py` | "模型引用了不存在的 evidence id → 丢弃并记录 gap" | `opportunities/grounding.py` |
| `web.py` | 每请求独立连接、SPA 回退、静态挂载 | `api/app.py` |
| `api/ops.py` | sources / health / system status 端点模式 | `api/sources.py`、`api/jobs.py` |
| `config.py` | YAML 源注册 + 边界校验 | `sources/registry.py`（扩展字段） |
| schema: `sources` `source_health` `runs` `ai_runs` | 原样保留（加列） | — |

**B. 移除（与"内容创作/发布"产品线绑定，与新目标无关）**

- 代码：`writing.py` `content.py` `services/*` `exporter.py` `api/content.py` `judgement.py` `evaluation.py`（盲评）`snapshot.py` `brief.py`（重写）`cognition.py` `fast_rank.py` `trends.py`（重写）`prompts.py`（重写）
- 表：`documents` `document_versions` `evidence_links` `media_assets` `platform_variants` `publications` `content_snapshots` `theses` `articles` `article_reviews` `research*` `judgement_ledger` `blind_*` `candidate_runs*` `world_model_updates` `candidates` `trend_*`
- 前端：`Editor.tsx` `Content.tsx` `Research.tsx` `Knowledge.tsx` `QualityLab.tsx`
- 处理方式：打 tag `v3.1-content-os` 冻结，然后在新分支删除。不保留兼容层（README 已声明不维护旧产品逻辑）。

**C. 缺失、需要新建**

Source Adapter 抽象、Product Hunt / HN / Reddit / GitHub 适配器、Mock 适配器 + fixtures、Embedding Provider、Classifier Provider、Pain Engine、语义聚类、趋势速度检测、竞争分析、Opportunity Engine、九维评分、Evidence 系统、关系表（图）、Explore、Ask、Builder Brief、全部前端页面、深色模式、版本化迁移、lint/typecheck。

---

## 1. 关键架构决策

### D1. 后端留在 Python，前端 TypeScript
理由见 0.1。规格中"TypeScript"作为基础技术要求，但排在"沿用当前技术栈优先"之后。类型安全通过 **pydantic v2 模型 + pyright 严格模式** 保证；API 契约通过 pydantic → OpenAPI → 前端类型（`openapi-typescript` 生成 `api/types.gen.ts`）保证端到端一致。

### D2. Product Hunt 语义搜索 = 本地向量索引 + Topic 回退
PH API v2（GraphQL，`https://api.producthunt.com/v2/api/graphql`）只提供 `posts(topic, order, postedAfter/Before, featured)`、`post(slug)`、`topics(query)`，**没有全文搜索**。因此：

```
ProductHuntAdapter.search(query)
  1) 本地：embed(query) → cosine over products.embedding（已入库 PH 产品）
  2) 回退：topics(query) → 取匹配 topic 的近 90 天 posts → 入库 → embed → 合并排序
  3) 结果缓存到 explore_sessions，24h 内同 query 不重复打 API
```

这同时满足"不要写低质量爬虫"和"持续积累供给侧语料"。每日任务通过 `fetchTrending(7d/30d/month)` + 关注 topic 列表持续扩充本地 PH 语料。

**字段真实性纪律**：`votesCount / commentsCount / reviewsCount / reviewsRating / topics / makers / comments / featuredAt / website` 来自 API，标 `source=api`；`pros / cons / review_summary / common_complaints` 由 FAST 模型从 comments 归纳，标 `derived`；`pricing` 由分类器从 description/website 推断，标 `inferred`。UI 上区分显示。Phase 1 第一步做一次 schema introspection，把实际可用字段固化到 `docs/PRODUCT_HUNT_INTEGRATION.md`。

**MCP**：`PRODUCTHUNT_MODE=graphql|mcp|mock`。后端服务默认走 GraphQL（不需要拉起子进程、可控制 complexity 预算：6250 点 / 15 分钟）；`McpProductHuntAdapter` 实现同一接口，供已经有 MCP 网关的环境使用。

### D3. 成本金字塔（严格分层）

```
全部 signals
  → RuleFilter        零成本：痛点词典（"is there a tool" / "I hate" / "alternative to" / "every time I have to" / "too expensive"…）+ 长度 + 语言 + 去重
  → FastClassifier    FAST_MODEL，每次 20 条批量：is_pain / relevance / persona / category（≈ 1 call / 20 signals）
  → Embedding         EMBEDDING_MODEL，每次 64 条批量
  → Cluster           纯计算
  → Gate              仅 signal_count≥3 且 (source_count≥2 或 velocity≥3) 的簇进入下一层
  → AnalysisModel     ANALYSIS_MODEL：每个合格簇 1 次调用（PainCluster 摘要 + 结构化 PainSignal + 机会分析 + 评分理由）
```

预算复用现有 `AI_24H_BUDGET_CNY` 和 `*_24H_CALL_LIMIT` 熔断；每一步在 `job_steps.counts_json` 记录 `in / out / cost`。

### D4. Provider 抽象（三类）

```python
class LLMProvider(Protocol):       # 已有 chat_json，槽位改名：FAST_MODEL / ANALYSIS_MODEL（原 COGNITION）
class EmbeddingProvider(Protocol): # embed(texts) -> list[list[float]]
    # OpenAICompatibleEmbedding(EMBEDDING_MODEL 槽位)
    # LocalHashEmbedding（hashed n-gram TF-IDF，512 维，零依赖；仅 demo/离线，标 degraded）
    # SentenceTransformerEmbedding（可选安装）
class ClassifierProvider(Protocol):# classify(batch) -> list[Classification]
    # RuleClassifier（永远可用，做预筛与离线回退）
    # LLMClassifier（FAST_MODEL）
    # JevClassifier / LocalClassifier（接口占位，抛 NotConfigured）
```
向量按 `(model, dim)` 存储；切换 embedding 模型后触发簇重算，而不是混用不同空间的向量。

### D5. 向量存储：V1 用 SQLite BLOB + numpy 暴力检索
V1 规模（万级 signal、千级 product）下 numpy cosine 全量检索 <50ms。表设计与 `sqlite-vec` / `pgvector` 兼容（`vector BLOB` + `model` + `dim`），后续切换只换 `clustering/index.py`。

### D6. Opportunity Graph = 一张通用 `edges` 关系表
```
edges(id, from_type, from_id, relation, to_type, to_id, weight, meta_json, created_at)
relation ∈ {affects, solved_by, has_complaint, belongs_to, related_to, derived_from, competes_with, supported_by, alias_of}
```
所有派生关系写入 edges；业务表保留外键用于查询效率。未来导出 Neo4j 只需遍历这张表。

### D7. 去重四层
1. `canonical_url` 精确（现有）
2. `content_hash`（规范化正文 sha256）
3. `simhash64` 近重复（Hamming ≤ 3）→ 标 `dedup_of`，保留但不重复计数
4. 语义跨源重复（cosine ≥ 0.95 且 7 天内）→ 同上；产品别名：规范化名称 + 网站主域 → `alias_of` 边

被去重的 signal 仍计入 `engagement` 与 `unique_users`，不再单独进入分类/分析。

### D8. Opportunity 与 Pain Cluster 一一对应
每个 pain_cluster 至多一个主 opportunity（`opportunities.pain_cluster_id UNIQUE`）。每日重跑更新 `version / last_seen / signal_count / growth / scores`，**不新建重复机会**；人工设置的 `status` 不被覆盖。

### D9. Live / Mock 不混淆
`sources.mode ∈ {live, mock}`，`signals.origin ∈ {live, mock}`，`products.origin` 同理。任何聚合对象（cluster / opportunity）计算 `data_mode ∈ {live, mock, mixed}`；UI 在卡片、详情、Today 顶部显式打标。Mock fixture 内容是**手写的、明确标注为演示**的样本，不伪装成真实抓取。

### D10. 清库重来，不做数据迁移
3.1 没有外部用户，旧库文件重命名为 `data/legacy-3.1.db`，新 schema 从 `0001_init.sql` 开始。

---

## 2. 目标架构

### 2.1 数据流

```
Sources (Adapter 插件)
  demand: hackernews(Algolia, 免 key) · reddit(public JSON, 可选) · github_issues(token 可选) · rss · mock
  supply: producthunt(GraphQL/MCP/mock) · github_repos · mock
        ↓ RawSignal / RawProduct（统一 pydantic 模型）
Ingestion  → signals / products（origin 打标、source_health、限速）
        ↓
Normalize  → 清洗、语言、canonical_url、content_hash、simhash、dedup_of
        ↓
RuleFilter → FastClassifier（is_pain / relevance / persona / category）
        ↓
Embedding  → signal_embeddings / product_embeddings
        ↓
Clustering → pain_clusters（增量质心分配）· product_clusters（solution）
        ↓
Trends     → trend_snapshots（每日计数）→ velocity / acceleration / emerging
        ↓ Gate（signal_count / source_count / velocity）
Market     → 每簇：PH 语义搜索 + GitHub → competition_profiles + product_insights
        ↓
Analysis   → pain_signals（结构化）· opportunities（title/wedge/monetization/…）
        ↓
Scoring    → opportunity_scores（9 维 × score/reason/confidence/evidence_ids）→ opportunity_score
        ↓
Evidence + edges（图）
        ↓
API → Today / Radar / Explore / Opportunities / Ask / Sources / Jobs
        ↓
Builder Brief（Start Product）
```

### 2.2 后端目录

```
src/trendradar/
  core/          settings.py(pydantic-settings) errors.py logging.py ids.py timeutil.py
  db/            connection.py migrate.py migrations/0001_init.sql … repositories/
  sources/       base.py(SourceAdapter, RawSignal, RawProduct, SearchQuery) registry.py
                 producthunt/{client.py, adapter.py, mcp_adapter.py, mapping.py}
                 hackernews.py reddit.py github.py rss.py
                 mock/{adapter.py, fixtures/*.json}
  ingestion/     runner.py(并发采集+health) store.py ratelimit.py
  normalize/     text.py url.py lang.py dedup.py(hash/simhash/semantic) rules.py(痛点词典)
  providers/     llm.py embeddings.py classifier.py
  analysis/      pain_extractor.py product_insights.py entities.py prompts/
  clustering/    index.py(numpy cosine) pain_clusters.py solution_clusters.py labeling.py
  trends/        snapshots.py velocity.py radar.py
  market/        competition.py(簇 → PH 搜索 → CompetitionProfile) aliases.py
  scoring/       dimensions.py weights.py explain.py
  opportunities/ generator.py lifecycle.py evidence.py grounding.py builder.py
  graph/         edges.py
  ask/           planner.py(NL → 检索计划) answer.py
  jobs/          daily.py steps.py scheduler.py stats.py
  api/           app.py today.py radar.py explore.py opportunities.py sources.py jobs.py ask.py settings.py schemas.py
  cli.py
```

### 2.3 前端目录

```
frontend/src/
  app/         router.tsx shell.tsx theme.ts(dark/light, CSS vars)
  api/         client.ts types.gen.ts(openapi-typescript 生成)
  pages/       Today Radar Explore Opportunities OpportunityDetail Sources Jobs Settings
  components/  OpportunityCard ScoreGrid ScoreBar EvidencePanel CompetitorList
               DataModeBadge(Live/Mock) TrendSparkline StatusSelect EmptyState
  lib/         format.ts
```
导航：Today（默认）· Radar · Explore · Opportunities · Sources · Jobs · Settings。移除 TipTap，新增 `react-router-dom`。视觉：Linear/Vercel 风格，排版优先，卡片式，`prefers-color-scheme` + 手动切换。

---

## 3. 数据模型（V1 schema 0001）

保留：`sources`（+ `kind` demand/supply/hybrid、`adapter`、`mode` live/mock、`config_json`）、`source_health`、`ai_runs`。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `signals` | id, source_id, adapter, external_id, url, canonical_url, title, content, author, author_id, lang, created_at, fetched_at, engagement_json, metadata_json, content_hash, simhash, origin, dedup_of | RawSignal 落库 |
| `signal_classifications` | signal_id, classifier, is_pain, relevance, persona, category, confidence, reason, model | 廉价分类结果 |
| `signal_embeddings` | signal_id, model, dim, vector BLOB | PK(signal_id, model) |
| `pain_signals` | id, signal_id, problem, persona, context, severity, frequency, willingness_to_pay, existing_workaround, current_solution, friction_json, evidence_quote, confidence, model | 结构化痛点 |
| `pain_clusters` | id, label, summary, persona, category, signal_count, unique_users, source_count, first_seen, last_seen, velocity, acceleration, stage, data_mode, centroid BLOB, centroid_model | |
| `pain_cluster_items` | cluster_id, pain_signal_id, similarity | |
| `products` | id, source, external_id, name, slug, tagline, description, url, website, domain, categories_json, votes, comments, rating, review_count, launched_at, makers_json, credibility_json, pricing, pricing_origin, origin, raw_json, fetched_at | 供给侧 |
| `product_embeddings` | product_id, model, dim, vector | |
| `product_insights` | product_id, pros_json, cons_json, review_summary, complaints_json, derived_from, sample_size, model, confidence | 标 derived |
| `product_clusters` / `product_cluster_items` | label, summary, product_count, new_90d, avg_rating, maturity | Solution Cluster |
| `trend_snapshots` | subject_type, subject_id, day, new_signals, cum_signals, unique_sources | 每日一行 |
| `competition_profiles` | id, pain_cluster_id, density, maturity, avg_rating, review_volume, recent_launches_90d, common_features_json, common_complaints_json, pricing_distribution_json, competitor_ids_json, computed_at | |
| `opportunities` | id, pain_cluster_id UNIQUE, title, description, target_user, core_pain, proposed_solution, wedge, monetization, distribution, build_type, build_difficulty, why_now, risks_json, next_action, status, opportunity_score, confidence, data_mode, version, first_seen, last_seen, signal_count, growth, model | |
| `opportunity_scores` | opportunity_id, dimension, score, reason, confidence, evidence_ids_json, computed_at, scoring_version | 每维一行 |
| `evidence` | id, subject_type, subject_id, kind(pain/complaint/competitor/trend/workaround), signal_id, product_id, quote, url, source_id, occurred_at | |
| `edges` | 见 D6 | 图 |
| `personas` | id, name, description | 维度表 |
| `jobs` / `job_steps` | jobs(原 runs)+ steps(name, started, finished, status, counts_json, error) | 可观测 |
| `reports` | id, day, kind(daily_brief), content_md, data_json | Daily Opportunity Brief |
| `builder_briefs` | opportunity_id, content_json, model, created_at | Start Product 输出 |
| `explore_sessions` | id, query, status, result_json, created_at, expires_at | Explore 缓存 |
| `ask_sessions` | id, question, plan_json, answer_md, evidence_ids_json, model, created_at | |

状态机 `opportunities.status`：`discovered → watching → promising → researching → validated → building`，任意 → `rejected / archived`。

---

## 4. 核心算法与规则

### 4.1 Source Adapter 契约

```python
class SearchQuery(BaseModel):
    text: str; window_days: int = 90; limit: int = 50; kind: Literal["pain","product","any"] = "any"

class RawSignal(BaseModel):
    external_id: str; source: str; source_type: Literal["demand","supply","hybrid"]
    url: HttpUrl; title: str; content: str; author: str|None; author_id: str|None
    created_at: datetime; fetched_at: datetime
    engagement: Engagement|None   # votes comments likes reviews
    metadata: dict[str, Any] = {}

class SourceAdapter(Protocol):
    id: str; name: str; type: Literal["demand","supply","hybrid"]; mode: Literal["live","mock"]
    def search(self, q: SearchQuery) -> list[RawSignal]: ...
    def fetch_trending(self, window: Literal["7d","30d","month"]) -> list[RawSignal]: ...  # optional
    def fetch_latest(self, since: datetime) -> list[RawSignal]: ...                        # optional
    def health(self) -> AdapterHealth: ...
```
V1 live 适配器：HN（Algolia `search?tags=(story,comment)`，无需 key，**V1 需求侧主力**）、Product Hunt（token）、GitHub Issues（token 可选，无 token 10 req/min）、Reddit（`/r/{sub}/search.json` + UA，可选，易被限制→失败即降级）。`sources.yml` 升级为 v5 格式：

```yaml
- id: hn
  adapter: hackernews
  kind: demand
  mode: live
  queries: ["is there a tool", "alternative to", "I built a script"]
  max_per_round: 200
- id: producthunt
  adapter: producthunt
  kind: supply
  mode: live          # 无 token 时自动降级为 mock 并在 UI 标注
  topics: ["developer-tools","productivity","artificial-intelligence","saas","mac"]
```

### 4.2 Pain 识别（两段式）
- **FastClassifier**（批量 20）：`{signal_id, is_pain, relevance 0-100, persona, category, reason}`；`relevance<40` 或 `is_pain=false` 不再进入后续。
- **PainExtractor**（ANALYSIS，按簇批量而不是按条）：输入簇内 top-N 代表 signal，输出每条 `PainSignal`（problem / persona / context / severity / frequency / willingness_to_pay / existing_workaround / current_solution / friction[] / evidence_quote）。`evidence_quote` 必须是原文子串，否则丢弃（grounding 校验）。

### 4.3 聚类
- 增量：新 signal 向量与现有簇质心 cosine ≥ τ（API embedding τ=0.80；hash embedding τ=0.55，标 degraded）→ 加入并更新质心；否则暂存为 singleton。
- 每日：对 singleton + 小簇跑一次 agglomerative（N<5k 直接 scipy/numpy），合并；簇大小翻倍或 label 为空时用 FAST 模型重新生成 label/summary。
- Falsification 测试：三个 demo case 的 fixtures 不得互相合并；同 case 内跨源样本必须合并。

### 4.4 趋势
```
daily_new(c, d) 来自 trend_snapshots
velocity     = mean(new, last 3d) / max(mean(new, prior 14d), 0.5)
acceleration = velocity_today − velocity_3d_ago
stage: emerging (velocity≥3 ∧ signals≥5 ∧ sources≥2) · growing (1.5–3) · stable · fading (<0.5)
cross_source_bonus: 3 天内新增来源类型 +1 级
```
Radar 页面六个板块（Emerging Problems / Categories / Products / Fast Growing Tools / Unsolved Pain / Crowded Markets）全部是对 `pain_clusters + product_clusters + trend_snapshots + competition_profiles` 的查询，窗口 7D/30D/90D。

### 4.5 竞争分析（每合格簇）
```
cluster.label + top pain quotes
  → producthunt.search()（本地向量 + topic 回退）+ github.search(repos)
  → Top N (≤12) competitors → 缺 insights 的产品跑 product_insights（FAST，基于 comments）
  → CompetitionProfile:
     density = f(产品数, 近 90 天新增)      maturity = f(最高 votes, 平均年龄, 有付费产品比例)
     avg_rating / review_volume / pricing_distribution / common_features / common_complaints
```

### 4.6 评分（可解释）
每维 `score 0-100 + reason + confidence + evidence_ids`，`scoring_version` 入库。

| 维度 | 权重 | 计算方式 |
|---|---|---|
| Pain | 0.15 | 模型：severity/frequency/wtp 加权 + 引用数量 |
| Demand | 0.15 | 确定性：signal_count、unique_users、engagement、source_count（对数缩放） |
| Growth | 0.10 | 确定性：velocity / acceleration / stage |
| Competition | 0.15 | `0.40×validation + 0.35×(100−intensity) + 0.25×differentiation`；**零竞品 ⇒ validation 低，不加分** |
| Gap | 0.15 | 确定性 + 模型：complaint_volume/solution_count、未覆盖 persona、缺失功能数 |
| Monetization | 0.10 | 模型：wtp 证据、竞品定价分布、买家类型 |
| Build Ease | 0.10 | 模型：build_type、依赖外部平台程度、数据壁垒（分高 = 易做） |
| Distribution | 0.05 | 模型：社区可达性、SEO/商店渠道、是否有明确聚集地 |
| Evidence Confidence | 乘子 | `final = Σ wᵢsᵢ × (0.7 + 0.3 × conf/100)`；conf 由来源多样性、时效、引用质量、data_mode 决定 |

Today 入选门槛：`opportunity_score ≥ 70 ∧ confidence ≥ 60 ∧ status ∉ {rejected, archived}`，每日最多 5 条；不足时首页明确写"今天没有机会过线"，并列出 watching 中增长最快的簇。**Quality > Quantity。**

### 4.7 Opportunity 生成（ANALYSIS，每簇 1 次调用）
输入：PainCluster 摘要 + pain_signals + CompetitionProfile + product_insights + trend 指标 + 允许引用的 `signal_id / product_id` 白名单。
输出：Opportunity 全字段 + 各"模型维度"的 score/reason/evidence_ids。
校验：pydantic 严格模型；evidence_ids 必须在白名单内（否则丢弃该条理由并降 confidence）；`title` 与现有 opportunity 语义重复（cosine ≥ 0.9）时合并到已有记录。

### 4.8 Explore
`POST /api/explore {query}` → 创建 session（异步 job）→ 并行 `search()` 所有 enabled adapter → 走与日任务相同的 normalize/classify/embed → session 内聚类 → competition → 生成 Market Map（overview / pains / competitors / complaints / open-source / trends / opportunity 草案）。结果写库（signals 永久保留，充实语料），session 缓存 24h。

### 4.9 Ask
FAST 模型把自然语言转为**结构化检索计划**（JSON：窗口、最小分数、build_difficulty、persona、category、排序、需要的表）→ 后端执行 SQL → ANALYSIS 模型基于返回的 opportunities/clusters/products/evidence 作答，答案里每个断言带 `[opp:id]` / `[sig:id]` 引用 → 前端渲染成可点击链接。**不触发 Web 搜索。**

### 4.10 Builder Brief（Start Product）
`POST /api/opportunities/{id}/builder` → ANALYSIS 一次调用生成 `Problem Definition / Target User / JTBD / MVP / Core Features / Pricing Idea / Competitors / Differentiation / Technical Difficulty / Recommended Stack / Go-to-Market / Validation Plan`，存 `builder_briefs`，同时状态可推进到 `researching`。

### 4.11 Daily Job（step runner，可断点续跑）
```
collect → normalize_dedup → classify → embed → cluster → trends → gate → market → analyze → score → evidence_graph → brief
```
每步一行 `job_steps`（in/out/dedup/cost/error），失败步不拖垮整轮（继承现有 graceful degradation 思路），Jobs 页面按步展示。

---

## 5. API 契约（摘要）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/today` | `{greeting, date, data_mode, opportunities: OpportunityCard[≤5], emerging_pains[], new_categories[], fast_growing_products[], interesting_oss[]}` |
| GET | `/api/radar?window=7d|30d|90d` | 六板块 |
| POST/GET | `/api/explore` · `/api/explore/{id}` | 创建/轮询 Market Map |
| GET | `/api/opportunities?status=&min_score=&sort=` | 列表 |
| GET | `/api/opportunities/{id}` | 卡片全量 + scores + evidence + competitors + graph 邻居 |
| PATCH | `/api/opportunities/{id}/status` | 生命周期 |
| POST | `/api/opportunities/{id}/builder` | Builder Brief |
| GET | `/api/evidence?subject=opportunity:{id}` | 证据列表（source/url/quote/timestamp/signal_id） |
| POST | `/api/ask` | `{question}` → `{answer_md, citations[]}` |
| GET | `/api/sources` · POST `/api/sources/{id}/run` | 源状态、手动触发 |
| GET | `/api/jobs` · `/api/jobs/{id}` · POST `/api/jobs/daily` | 任务与步骤 |
| GET | `/api/settings/status` | 模型槽位、embedding 模式、PH 模式、预算用量 |

OpportunityCard 形状（Today 与列表共用）：
```json
{
  "id": "...", "title": "AI Coding Session Manager", "status": "discovered", "data_mode": "live",
  "problem": "...", "target_user": "...", "why_now": "...",
  "scores": {"pain": 87, "demand": 81, "growth": 82, "competition": 64, "gap": 85,
             "monetization": 74, "build_ease": 91, "distribution": 70, "confidence": 83, "opportunity": 86},
  "existing_solutions": [{"product_id": "...", "name": "...", "votes": 412, "rating": 4.1}],
  "main_complaints": ["..."], "wedge": "...", "monetization": "...",
  "evidence_summary": {"reddit": 12, "hackernews": 4, "github": 4, "producthunt_products": 7},
  "first_seen": "...", "last_seen": "...", "growth": 3.2
}
```

---

## 6. 配置与运行

`.env.example`（新）：
```
FAST_MODEL_BASE_URL / FAST_MODEL_API_KEY / FAST_MODEL_MODEL
ANALYSIS_MODEL_BASE_URL / ANALYSIS_MODEL_API_KEY / ANALYSIS_MODEL_MODEL
EMBEDDING_MODEL_BASE_URL / EMBEDDING_MODEL_API_KEY / EMBEDDING_MODEL_MODEL   # 未配置 → LocalHashEmbedding (degraded)
PRODUCTHUNT_MODE=graphql|mcp|mock   PRODUCTHUNT_TOKEN=
GITHUB_TOKEN=            # 可选
REDDIT_USER_AGENT=       # 可选
AI_24H_BUDGET_CNY / *_24H_CALL_LIMIT / *_CNY_PER_M   # 沿用
DAILY_HOUR=01  TIMEZONE=Asia/Shanghai
```
运行命令（保持等价于规格要求）：
```bash
git clone … && cp .env.example .env
make setup      # pip install -e ".[dev]" && cd frontend && npm install
make seed-demo  # 写入 3 个演示场景 fixtures（origin=mock）并跑一轮离线 pipeline
make dev        # 后端 8787 + Vite 5173（并行）
make check      # lint(ruff) typecheck(pyright + tsc) test(pytest + integration) build(frontend) migrate
trendradar daily | daemon | serve | explore "Claude Code" | ask "…"
```
无任何 API Key 时：HN 仍是 live，PH/Embedding/LLM 降级为 mock/rule/hash，系统完整可跑，UI 标 Mock/Degraded。

---

## 7. 执行计划（按验收链 §34 排序，先打通再加宽）

| 阶段 | 内容 | 产出 / 验收 | 工作量* |
|---|---|---|---|
| **P0 基线** | tag `v3.1-content-os`；新分支；删除内容线代码/表/页面；`core/settings`、logging、版本化迁移；ruff + pyright + tsc；CI 更新；Makefile | install/lint/typecheck/test 全绿；`trendradar init` 建新库 | 0.5 d |
| **P1 Source 层** | `SourceAdapter`/`RawSignal`；registry + `sources.yml` v5；Mock（3 个 demo case fixtures）、HN、Product Hunt（GraphQL + introspection 固化字段 + complexity 限速）、GitHub、Reddit、RSS 迁移；ingestion runner | 每个 adapter 有录制 fixture 的单测；`trendradar collect --source hn --query "…"` 入库；PH trending 7d/30d 入库 | 1.5 d |
| **P2 规范化 / 去重 / 分类 / 向量** | normalize、四层 dedup、痛点词典 RuleFilter、`ClassifierProvider`（Rule+LLM）、`EmbeddingProvider`（API+Hash）、向量表 | 去重测试（转发/跨源/别名）；FakeLLM 批量分类测试；离线 hash embedding 可跑 | 1 d |
| **P3 Pain Engine + 聚类 + 趋势** | PainExtractor（grounded quote）、增量质心聚类 + 日合并、簇 label、solution cluster、trend_snapshots + velocity/emerging | 3 个 demo case 正确成簇且互不合并（falsification）；合成时间序列触发 emerging | 1.5 d |
| **P4 市场 + 机会 + 评分 + 证据** | PH 语义搜索（本地索引 + topic 回退）、CompetitionProfile、product_insights、Opportunity 生成（白名单 grounding）、九维评分、evidence、edges、生命周期、Builder Brief | 集成测试：fixtures + FakeLLM 端到端 ≥3 个完整机会卡；评分单测含"零竞品不加分" | 1.5 d |
| **P5 API + UI** | 全部 router + pydantic schemas + openapi-typescript；前端重建 7 个页面、深色模式、Live/Mock 标识、Evidence 面板、状态流转、Explore 轮询、Ask | tsc 零错误、无 console error；Today 1–5 卡；详情页能回答规格"最终判断标准"的 12 个问题 | 2 d |
| **P6 任务 + 文档 + 验收** | step runner 日任务、daemon、Daily Brief、Jobs 页面数据、`make seed-demo`、README + `docs/{ARCHITECTURE, DATA_PIPELINE, SOURCE_ADAPTERS, OPPORTUNITY_SCORING, PRODUCT_HUNT_INTEGRATION, DEVELOPMENT, ACCEPTANCE}.md`、逐项跑 ACCEPTANCE | 新机器 `git clone → make setup → make seed-demo → make dev` 直接看到 Today | 1 d |

\* 专注开发人日（含测试），合计约 **9 人日**。若由 coding agent 连续执行，建议按此顺序一次推进到 P4 的集成测试通过（这是最小闭环），再做 UI。

### 每阶段共同纪律
- 先写失败测试再实现关键边界（沿用仓库既有 falsification 风格）。
- 每个 LLM 调用点都有 FakeLLM 测试路径；CI 不依赖任何外部 key。
- 每次提交保持 `make check` 绿。

---

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| PH token 审批慢 / complexity 预算（6250/15min）耗尽 | 本地缓存 raw_json；每日只拉 trending + 关注 topic 增量；限速器读 `X-Rate-Limit-Remaining`；mock 保证演示 |
| Reddit 非官方 JSON 被限制 | 标为 optional；失败只影响该源 health；HN 作为 V1 需求侧主力 |
| 离线 hash embedding 聚类质量差 | 明确 degraded 标识；向量按 model 存储，配置 API embedding 后自动重算 |
| LLM JSON 漂移 / 编造证据 | pydantic 严格校验 + 一次修复重试 + evidence 白名单 grounding + confidence 降级 |
| 机会重复 / 泛滥 | 簇级唯一 + 语义合并 + 入选门槛 + 每日 ≤5 |
| SQLite 并发（daemon 写 + API 读） | WAL、每请求独立连接（已有）、单写者任务、`busy_timeout` |
| 范围蔓延 | 严格遵守规格 §38 不做清单；Builder 只到 Brief |

---

## 9. 待确认的非阻塞决策（默认值可直接开工）

1. **UI 语言**：默认 English（目标是海外软件市场，规格 mock 全是英文），文案集中在 `i18n/en.ts` 便于后加中文。
2. **产品/包名**：V1 保留 Python 包名 `trendradar`（避免大规模改动），UI 标题改为新产品名；后续需要再整体 rename。
3. **后端语言**：保留 Python（见 D1）。
4. **Reddit**：默认 enabled=false，配置 UA 后打开。
