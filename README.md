# TrendRadar 3.1 — 硬币先生 · 商业内容操作系统

> **发现 → 理解 → 判断 → 创作 → 发布 → 复盘**

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
- FACT / CLAIM / INFER 可追溯
- 配图建议
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
