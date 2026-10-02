# TrendRadar 写作台 (v4)

**一个本地运行的内容创作平台：从工作台接着写，或从简报选题，一键延伸成公众号长文母稿，再生成各平台版本。**
信息采集是它的扩展功能——商业信源（RSS / 官网）和用户痛点信号（HN / Reddit / GitHub / Product Hunt）
汇成每天一页的《简报速览》；机会雷达、探索、问答作为"扩展工具"保留。

```
 商业信源 (RSS/官网, 45 个)  ─┐                       ┌─► 延伸创作 ─► 母稿 (Markdown + 实时预览)
 用户痛点 (HN/Reddit/GitHub) ─┼─► 简报速览 (一页) ────┤      │  素材绑定 · 自动保存 · 版本 · AI 助手
 机会雷达 (v4 pipeline)      ─┘   值得写 / 切口        └─► 存为素材 ─► 素材库          │
                                                                                     ▼
                                                              平台版本 (公众号 / 小红书 / 知乎 / 头条 / X)
                                                                                     ▼
                                                              导出 (公众号排版 HTML / 纯文本 / .md) · 发布记录
```

* **创作是核心：** 稿件 = 母稿 + 核心判断 + 绑定素材 + 版本历史 + 平台版本 + 发布记录。编辑器是 Markdown + 实时预览，
  1.5 秒自动保存，⌘S 留名版本，任意版本可恢复（恢复前自动快照）。
* **AI 只依据素材写：** 选题角度 / 大纲 / 依据素材写初稿 / 改写选中段落（精简、扩写、更口语、更专业、加强逻辑…）/ 起标题 /
  生成平台版本。提示词只允许使用素材和正文中的事实，输出里出现素材里没有的数字会被标记。
* **简报速览：** 每条给出 来源 · 摘要 · 为什么值得写 · 可直接开写的切口，三个动作：**延伸创作 / 存为素材 / 忽略**。
* **诚实标注数据：** 每个对象都带 `live` / `mock` / `mixed`。演示素材构成的稿件才会得到模板化的"演示生成"输出；
  真实素材没有配置写作模型时明确提示，不会假装写作。
* **不接平台 API：** 一键复制带排版的公众号 HTML / 纯文本，在平台后台发布后记录链接，形成发布账本。

---

## 5 分钟跑起来（无需任何 API 密钥）

要求：Python ≥ 3.11，Node ≥ 20。

Windows 日常使用：双击项目根目录的 **`启动写作台.cmd`**。首次启动会准备项目环境、安装缺少的依赖并构建前端，之后自动打开浏览器；前端未变化时跳过构建，重复启动复用已有服务。保持启动窗口打开，结束时按 Ctrl+C。

完整流程、启动参数和界面规划见 [日常创作指南](docs/DAILY_WRITING.md)。下面是开发者命令行方式：

```bash
git clone https://github.com/exasdwyh-commits/trendradar.git
cd trendradar
cp .env.example .env            # 之后再填模型密钥也可以
make install                    # pip install -e ".[dev]" + npm install
make seed-demo                  # 建库 + 用内置演示数据跑完整条流水线（含 6 条商业动态、3 个痛点簇、1 篇示例稿）
make dev                        # 构建前端，在 http://127.0.0.1:8787 提供 API + UI
```

打开 <http://127.0.0.1:8787>：

1. **工作台** 点 **继续写作** 恢复最近的未完成稿件；新选题可在 **选题简报** 点 **延伸创作**（或直接点某个切口）→ 进入编辑器，素材已绑定；
2. 右侧 **AI 助手** → 大纲 / 公众号初稿 / 起标题；选中一段 → 改写；
3. **平台** 页签生成小红书 / 知乎 / 头条 / X 版本，**复制公众号排版** 直接粘贴到公众号编辑器；
4. **发布** 页签记录发布链接 → 出现在发布中心。

演示数据全部标注 **演示**；AI 输出标注 **演示生成**（模板，不代表真实模型质量）。

### 接入真实模型与信源

当前项目的 Agnes Flash / MiMo Pro 路由、接口验收与 Windows 开发命令见 [模型配置](docs/MODEL_SETUP.md)。

1. 在 `.env` 里填任意 OpenAI 兼容端点（`/chat/completions` + `/embeddings`）：

   ```ini
   FAST_MODEL_BASE_URL=https://api.openai.com/v1      # 便宜：分类、标签、商业动态评估（值得写的程度 / 切口）
   FAST_MODEL_API_KEY=sk-...
   FAST_MODEL_MODEL=gpt-4o-mini
   ANALYSIS_MODEL_BASE_URL=https://api.openai.com/v1  # 推理：痛点簇分析、机会卡、问答；未设 WRITING_MODEL 时也负责写作
   ANALYSIS_MODEL_API_KEY=sk-...
   ANALYSIS_MODEL_MODEL=gpt-4o
   WRITING_MODEL_MODEL=                               # 可选：专用写作模型（选一个中文写得好的）
   EMBEDDING_MODEL_BASE_URL=https://api.openai.com/v1
   EMBEDDING_MODEL_API_KEY=sk-...
   EMBEDDING_MODEL_MODEL=text-embedding-3-small
   ```

   `MODEL_BASE_URL` / `MODEL_API_KEY` 是所有槽位的兜底。成本护栏：`AI_24H_BUDGET_CNY`、`<SLOT>_24H_CALL_LIMIT`、`<SLOT>_INPUT/OUTPUT_CNY_PER_M`。
2. 商业信源（RSS / 官网抓取）无需密钥，在 **系统 → 信源** 里按需启停（`config/sources.yml` 声明，数据库里的开关优先）。
   可选：`PRODUCTHUNT_TOKEN`、`GITHUB_TOKEN`、`REDDIT_ENABLED=true` + `REDDIT_USER_AGENT`。
3. 点 **简报 → 抓取并刷新**（或 `trendradar brief`）只跑商业信源 + 重建简报；`trendradar daily` / `make serve`（内置每日调度）跑完整流水线。

---

## 页面

| 页面 | 作用 |
|---|---|
| **工作台** `/` | 继续最近的未完成母稿、查看待发稿和最近稿件、从简报切口开写、快捷记录笔记与链接。 |
| **选题简报** `/brief` | 一页：今日值得写（商业动态，按值得写的程度排序）· 正在升温的用户痛点 · 产品机会。每条有来源 / 摘要 / 为什么值得写 / 切口；动作：延伸创作、存为素材、忽略。可回看历史日期。 |
| **稿件** `/studio` | 稿件列表（灵感 / 草稿 / 待发 / 已发布 / 已归档），字数、素材数、版本数；状态筛选保存在地址中。 |
| **编辑器** `/studio/:id` | 编辑 / 分栏 / 预览三种视图 + 右侧活动栏面板（AI 助手 / 素材 / 版本 / 平台版本 / 发布，可收起）。标题、核心判断、状态、目标平台；自动保存 + ⌘S 版本，⌘\\ 收起面板。 |
| **素材库** `/materials` | 收藏的动态、信号、痛点簇、机会、链接（自动抓正文）和笔记；搜索、归档、从素材延伸创作。 |
| **发布** `/publish` | 每篇母稿在各平台的版本 / 发布状态矩阵 + 发布记录。 |
| 扩展工具 | **今日精选 / 痛点雷达 / 产品机会 / 探索 / 问答** —— v4 机会雷达完整保留（评分、证据、产品简报、问答）。 |
| 系统 | **信源 / 任务 / 设置** —— 信源健康与启停、每次任务的分步计数与模型调用、生效配置与用量。 |

界面按 13–14 寸笔记本（1280–1440 宽）设计：侧栏可收成图标栏（编辑器内自动收起），简报区块 / 信源分组可折叠，浅色 / 深色主题，偏好记在浏览器本地。

## 创作 Agent

编辑器右侧的 **创作 Agent** 可整理已有素材和缺口、提出大纲，等作者确认后连续分节起草、审稿并准备多平台版本。候选稿单独保存，最终采用时保留原稿快照；支持暂停与继续。操作说明见 [创作 Agent](docs/WRITING_AGENT.md)。

## CLI

```
trendradar init                 建库 / 迁移，注册信源
trendradar seed-demo            用演示数据跑流水线（离线、确定性）
trendradar brief [--mock-only] [--no-fetch] [--day YYYY-MM-DD] [--json]   抓取商业信源并在终端打印简报
trendradar daily [--mock-only] [--force]
trendradar collect [--mock-only]
trendradar explore "<query>" [--mock-only]
trendradar ask "<question>"
trendradar status | sources [--test]
trendradar serve [--host] [--port] [--reload] [--scheduler]
trendradar daemon               只跑调度器
```

API 文档：<http://127.0.0.1:8787/api/docs>（写作台接口全部在 `/api/brief|materials|documents|variants|publications|publish|studio/*`）。

## 生产部署

* 单进程足够：`trendradar serve --scheduler`（或 `trendradar daemon` + `trendradar serve` 放在反向代理后）。
* 状态就是一个 SQLite 文件（`DATA_DIR/trendradar.db`，WAL）。备份它；迁移在启动时自动执行（v3.1 / 早期 v4 库可原地升级）。
* `HOST=0.0.0.0` 对外暴露；没有鉴权，请放在自己的代理 / 认证后面，并把访问用的域名 / IP 写进 `ALLOWED_HOSTS`
  （默认只信任本机 Host；跨站写请求一律拒绝，前端另有域名时用 `CORS_ORIGINS` 放行）。
* 素材「链接抓正文」只抓公网地址：拒绝本机 / 局域网 / 云元数据等地址，重定向逐跳校验，正文上限 3 MB。
* Cron 替代：`0 8 * * * cd /srv/trendradar && trendradar brief >> logs/brief.log 2>&1`。

## 开发

```bash
make test        # pytest：适配器、归一化、去重、模型层、聚类、评分、流水线、API、写作台、安全
make lint        # ruff check + ruff format --check；类型检查：mypy
make web-dev     # Vite 开发服务器 :5173，/api 代理到 :8787（另开 `trendradar serve`）
```

文档：[写作台](docs/CONTENT_STUDIO.md) · [架构](docs/ARCHITECTURE.md) · [数据流水线](docs/DATA_PIPELINE.md) · [信源适配器](docs/SOURCE_ADAPTERS.md) ·
[机会评分](docs/OPPORTUNITY_SCORING.md) · [Product Hunt](docs/PRODUCT_HUNT_INTEGRATION.md) · [开发](docs/DEVELOPMENT.md) ·
[验收](docs/ACCEPTANCE.md) · [V1 机会雷达计划](docs/V1_OPPORTUNITY_PLAN.md)

## 范围之外

移动端、多用户权限、计费、直连平台发布 API、营销站、动画、图数据库。
更早的内容操作系统保留在 tag `v3.1-content-os`。

## License

MIT — see [LICENSE](LICENSE).
