# TrendRadar 3.1 — 硬币先生 · 商业内容操作系统

> **发现 → 理解 → 判断 → 创作 → 发布 → 复盘**

## 唯一产品基线

`master` 是唯一真实产品状态，当前基线为 **TrendRadar 3.1**。

项目不维护旧版 TrendRadar 的兼容层、旧热榜页面或历史产品逻辑；后续所有开发直接围绕核心目标迭代：

> 高质量商业信号 → 可靠认知 → 自主创作 → 多平台发布 → 长期复盘

历史测试代码只有在仍服务上述闭环时才保留，否则直接删除。

TrendRadar 已从旧版“全网热榜雷达”彻底重构成一个 **商业内容专用** 的个人工作台。它不追求抓得多，而是每天帮助你找到真正值得长期理解的商业变化，并把其中少数高价值判断变成可发布的内容资产。

## 只做五类商业内容

1. **公司与战略**：财报、资本开支、组织调整、产品战略、并购。
2. **产业与利润池**：供应链、制造、能源、芯片、机器人、AI 基础设施，重点看利润迁移。
3. **商业模式**：新产品、新定价、新渠道、一人公司/小团队、AI 原生公司。
4. **AI 商业化**：不追参数榜，重点追真实 ROI、流程替代、成本结构和企业采购。
5. **全球化与中国映射**：出海、技术授权、海外渠道、跨国供应链，以及对中国企业的映射。

纯娱乐、明星、体育、泛社会热搜、短视频热榜不进入系统。

## 完整产品闭环

```
高质量商业来源
→ RSS / 官方网页 / 文章正文
→ URL 规范化与去重
→ 稳定 Story Cluster
→ 规则筛选
→ FAST_MODEL 商业价值筛选
→ COGNITION_MODEL
   ├─ 认知线：Trend / Evidence / Revision / World Model
   └─ 内容线：TOP3 / Research / Thesis
→ 人工确认观点
→ Writer 初稿
→ Content Studio 人机共创
→ Challenger
→ 配图方案
→ 平台版本
→ 发布记录
→ 判断账本
```

“值得写”和“值得长期理解”永远不是一个分数。

## 质量控制与自我校准

TrendRadar 3.1 不把“AI看起来聪明”当成质量指标，而是增加可验证的后台纪律：

- **Source Tier + Yield**：来源分 T1–T4，并记录 reliability / business_value / noise / accuracy / max_per_round；长期观察“采集多少 → 进入候选多少 → WRITE多少 → TOP3多少”。
- **两条排名线**：cognition_score 与 content_score 分开，长期趋势不被公众号传播性绑架。
- **Candidate Run Freeze**：每天冻结当时的候选、分数、证据与系统 TOP3，历史不会被后续重算覆盖。
- **盲评 10→3**：提交人工选择前隐藏系统排名，提交后再比较命中率，只检验选题选择能力。
- **AI Gateway Telemetry**：记录模型槽位、任务、Token、重试、HTTP状态和延迟；429/5xx 自动有界重试。
- **Graceful Degradation**：FAST / COGNITION / World Model 某一步模型失败，不再拖垮整条日任务。
- **Falsification Tests**：Discovery 单源、同主体趋势、未过 Challenger 发布等关键边界必须“故意破坏时变红”。
- **Publication Snapshot**：正式发布时冻结当时的母稿、Thesis、Research、Evidence 和平台版本，供未来复盘。

专业工具增加 **盲评 10→3、来源产出率、AI调用质量**，但这些信息不会污染首页决策界面。

## 研究与证据纪律

Research 不再只保存一段模型总结。每条 FACT / CLAIM / INFER 都保存为独立研究单元，并记录它引用的 intelligence id。模型如果返回不存在的来源 id，系统会自动丢弃对应事实/主张并记录 evidence gap。

进入 Thesis 前至少需要：

- 2 个可追溯研究单元；
- 2 个独立 evidence item。

生成母稿后，研究中实际使用的证据会自动绑定到 Document；发布快照冻结的是**文章真正绑定过的证据**，而不是候选池里所有材料。

内容编辑器支持“选中文字 → AI 修改”。该能力只做局部替换，不直接改整篇母稿；后端同时传入 thesis、上下文和已绑定证据，禁止无来源补事实。

## 前端

3.1 开始使用 **React + TypeScript + Vite + TipTap**。

核心入口只有：

- 今日重点
- 待我决定
- 研究室
- 创作中心
- 发布中心
- 趋势库
- 判断账本

专业工具下沉为来源状态和系统状态。

### 创作中心

创作中心不是“看 AI 成稿”，而是真正的编辑工作台：

- 空白新建，或从已确认观点进入
- TipTap 富文本编辑
- 1.5 秒自动保存
- 手动保存版本
- 版本恢复
- 文章证据侧栏
- FACT / CLAIM / INFER 逐条绑定 intelligence id，可追溯到原始来源
- 研究包若不足两个独立证据，不能进入 Thesis
- 选中文字可直接调用 AI 精简、重写、加强逻辑；AI 只能使用文章已绑定证据
- 配图建议：数据图必须绑定真实 evidence id，无来源的数据图会被系统拒绝
- 多平台版本生成

母稿是长期资产，不是一次性 AI 输出。

### 发布中心

当前支持：

- 公众号版
- 小红书版
- 知乎版
- 头条版
- 平台文件导出
- 已发布 URL / 状态记录

当前阶段**不伪装成已经接入各平台官方直发 API**。直发需要对应平台授权和真实 API 能力，后续按实际使用逐个平台接。

## 本地启动

### 1. 后端

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
trendradar init
```

### 2. 前端

```bash
cd frontend
npm install
npm run build
cd ..
```

### 3. 运行

```bash
trendradar daily
trendradar serve
```

打开：

```
http://127.0.0.1:8787
```

开发前端时：

```bash
trendradar serve
cd frontend
npm run dev
```

Vite 会把 `/api` 与 `/exports` 代理到本地 8787。

## 每日自动化

```bash
trendradar daemon
```

系统以 **Asia/Shanghai 13:00** 为日主轮次；如果电脑 13:00 没开，后续启动后发现当天没有成功轮次会补跑一次。

macOS 可运行：

```bash
sh scripts/install-macos-launchagent.sh
```

## 模型槽位

复制 `.env.example`：

- `FAST_MODEL`：第一轮商业筛选
- `COGNITION_MODEL`：趋势、利润池、双面分析、中国映射
- `RESEARCH_MODEL`：研究包与 Thesis
- `WRITING_MODEL`：母稿、配图建议、平台适配
- `CRITIC_MODEL`：独立 Challenger

没有配置某个模型时，对应能力明确显示未配置，**不允许规则结果冒充 AI 认知结果**。

模型调用成本也可以被纳入运行纪律：在 `.env` 中配置各槽位的输入/输出单价后，系统会记录每次调用的人民币成本；可选配置 `AI_24H_BUDGET_CNY` 与各槽位 `*_24H_CALL_LIMIT`，对滚动24小时成本和调用次数做软停止，避免自动任务失控消耗额度。

## 数据资产

3.1 新增第一类内容资产：

- `documents`：母稿
- `document_versions`：版本历史
- `evidence_links`：文章与证据关系
- `media_assets`：配图/图表/截图建议
- `platform_variants`：各平台版本
- `publications`：发布状态、URL、后续指标

这使系统可以完整追踪：

```
某个商业信号
→ 某个趋势
→ 某个核心判断
→ 一篇母稿
→ 多个平台版本
→ 发布表现
→ 未来判断复盘
```

详见：

- `docs/ARCHITECTURE.md`
- `docs/EDITORIAL.md`
- `docs/CONTENT_STUDIO.md`
- `config/sources.yml`
