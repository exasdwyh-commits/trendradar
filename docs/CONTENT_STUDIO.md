# 写作台（Content Studio）

创作平台的设计与实现说明。代码在 `src/trendradar/studio/`，接口在 `src/trendradar/api/studio.py`，
前端页面在 `frontend/src/pages/{Brief,Studio,Editor,Materials,Publish}.tsx`。

## 1. 对象模型（migration `0003_studio.sql`）

| 表 | 含义 |
|---|---|
| `sources` (rebuilt) | 新增 `kind='story'`（商业信源）；`config_json` 里带 `lane / role / tier`。旧库的行原样保留。 |
| `story_assessments` | 每条商业动态一行：`lane`、`business_value`（0–100，"值得写的程度"）、`why`、`angles_json`、`method`(`model`/`rule`/`fixture`)。 |
| `brief_items` | 某一天简报里的一条：`section`(story/signal/opportunity)、`ref_type/ref_id`、标题 / 来源 / 摘要 / why / angles / score / origin、`status`(new/saved/dismissed/used)、关联的 `material_id` / `document_id`。 |
| `materials` | 素材：`kind`(story/signal/cluster/opportunity/url/note)、标题、URL、来源、`summary`、`quote`、`content`、`origin`(live/mock/manual)。 |
| `documents` | 稿件（母稿）：`title`、`thesis`(核心判断)、`content_md`、`status`(idea/draft/ready/published/archived)、`target_platform`、`word_count`、`current_version`。 |
| `document_versions` | 版本快照：`source`(seed/autosave/manual/ai/restore)、`note`、完整 `content_md`。 |
| `document_materials` | 稿件 ↔ 素材，`relation`(seed/support/context)。 |
| `platform_variants` | 平台版本：`platform`、`title`、`content_md`、`meta_json`(tags)、`generated_by`、`warnings_json`。 |
| `publications` | 发布记录：平台、外链、备注、关联的版本。 |
| `ai_actions` | 每次 AI 调用的输入摘要 / 输出 / 模型 / 警告 / 是否采用。 |

`data_mode` 不落库，由绑定素材推导：只有演示素材 → `mock`；混有演示 → `mixed`；否则 `live`（手写笔记算真实内容）。

### 英文文章翻译（migration `0004_translations.sql`）

英文简报标题自动使用 `FAST_MODEL`（Agnes）翻译，只发送标题。素材详情及原始记录也先翻译标题；只有点击「翻译全文」才使用 `WRITING_MODEL`（MiMo，未配置时回退 `ANALYSIS_MODEL`）翻译已采集正文或摘要，支持中文／原文切换。简报关联原始记录时优先取原始正文。长文章分段处理，不主动截断；超过 10 万字符会提示分篇，但不影响标题翻译。

`article_translations` 按对象与原文哈希缓存译文，标题缓存只依赖原标题，正文修改后只失效全文缓存，不覆盖原始数据。已有全文译文可复用标题。`GET /api/translations/{ref_type}/{ref_id}?scope=title|full` 读取缓存，`POST` 按范围翻译，接口默认 `title`；没有模型或模型输出无效时提示错误，不生成演示译文。

## 2. 简报速览（`studio/brief.py`, `studio/stories.py`）

1. **采集**：`kind='story'` 的信源（RSS 或通用 `html` 适配器 + `article.py` 正文抽取）进入 `signals`，与痛点分类隔离（`analysis/classify.py` 跳过 story）。
2. **评估**：`assess_pending_stories` 用 FAST_MODEL 批量打分（lane / business_value / why / angles）；没有模型时用规则（tier + 商业关键词 + 噪音词 + 时效），`why` 明确写"规则评分"；演示信源用 fixture。
3. **组装**：`build_brief(day)` 取近 4 天的 story 候选（≥3 个信源时每源最多 3 条）+ 速度最快的痛点簇（≤5）+ 评分最高的机会（≤5），写入 `brief_items`（同一天幂等 upsert，保留用户状态）。
4. **动作**：`saved` → 生成素材；`extend` → 生成素材 + 新建稿件（`seed_markdown` 骨架，不含 H1）并把条目标记 `used`；`dismissed` 隐藏。
5. **刷新**：`POST /api/jobs/run {type:'brief'}` / `trendradar brief` = `run_brief_refresh`：只采集 story 信源 → 评估 → 重建今天的简报（1–3 分钟，不跑痛点流水线）。每日流水线末尾也有 `stories`、`digest` 两步。

## 3. 稿件与版本（`studio/documents.py`）

* `update_document(save_mode=…)`：
  * `autosave`（前端停止输入 1.5 s 后）：写入内容，**最多每 15 分钟**自动留一个快照；
  * `manual`（⌘S / 保存版本）：更新正文后留下命名版本，版本内容就是刚保存的正文；
  * `ai`（应用 AI 初稿前）：先快照再替换。
* `restore_version(n)`：先把当前状态快照为 `restore`，再写回第 n 版 —— 历史不会丢。
* 状态自动流转：有内容的 `idea` 自动变 `draft`；记录发布后变 `published`。
* `word_count`：中文按字、英文按词。

## 4. AI 助手（`studio/ai.py`）

| 动作 | 输入 | 输出 |
|---|---|---|
| `angles` | 素材 | 3–6 个 {title, angle, why_now, risk} |
| `outline` | 素材 + 核心判断 | {thesis, outline_md} |
| `draft` | 素材 + 大纲/正文 + 目标平台规则 | {title, content_md}（首行 H1 会被剥离，标题单独存） |
| `rewrite` | 选中文字 + 模式（精简/扩写/更口语/更专业/加强逻辑/更有张力/译成英文/自定义） | {text} |
| `titles` | 正文 | 6–8 个 {title, subtitle, style} |
| `variant` | 母稿 + 平台规则（`PLATFORM_RULES`：公众号/小红书/知乎/头条/X） | {title, content_md, meta.tags} |
| `summary` | 正文 | 三句话 |

约束：

* 系统提示只允许使用绑定素材与正文里的事实；`number_warnings` 把输出里出现、但素材/正文都没有的数字标出来（UI 以黄色警告显示）。
* 模型槽位：`WRITING_MODEL`（可选）→ 否则 `ANALYSIS_MODEL`。`GET /api/studio/capabilities` 返回当前槽位和 `model_available`。
* **不造假**：`data_mode='live'/'mixed'` 的稿件在没有写作模型时返回 503 `NotConfigured`；只有全演示素材的稿件才会得到 `FixtureLLM` 的模板输出，并标注 `generated_by='fixture'`（UI：演示生成）。
* 每次调用记入 `ai_actions`；用户点"插入 / 替换"时 `PATCH /ai/{action_id} {accepted:true}`。

## 5. 平台版本、导出与发布（`studio/publishing.py`）

* `create_variant(platform)` 调用 `variant` 动作并落库；同一平台可多次生成（保留多个）。
* `export_document(fmt=md|html|txt, variant_id?)`：`html` 用 `markdown-it-py` 渲染并内联样式（公众号编辑器只认内联 CSS），前端"复制公众号排版"把 HTML + 纯文本一起写入剪贴板；`txt` 去掉 Markdown 标记但保留链接 URL（小红书 / X 没有超链接）。
* `record_publication`：不接平台 API，只记录平台 / 外链 / 备注，并把稿件置为 `published`。`GET /api/publish` 给出稿件 × 平台矩阵。

## 6. 接口一览（都在 `/api`）

```
GET  /brief?day=&include_dismissed=          POST /brief/items/{id}/status {status}
POST /brief/items/{id}/extend {angle?}       POST /brief/rebuild
GET  /materials?q=&kind=&archived=           POST /materials {kind:url|note,...}   POST /materials/from-ref {ref_type,ref_id}
GET|PATCH /materials/{id}                    POST /materials/{id}/extend
GET  /documents?status=&q=                   POST /documents
GET|PATCH|DELETE /documents/{id}             (PATCH: fields + save_mode autosave|manual|ai + note)
POST /documents/{id}/versions {note}         GET /documents/{id}/versions/{n}   POST /documents/{id}/versions/{n}/restore
POST /documents/{id}/materials {material_id,relation}   DELETE /documents/{id}/materials/{mid}
POST /documents/{id}/ai/{action} {selection,mode,instruction,platform}   PATCH /documents/{id}/ai/{action_id} {accepted}
GET  /studio/capabilities
POST /documents/{id}/variants {platform}     GET|PATCH|DELETE /variants/{id}
GET  /documents/{id}/export?fmt=md|html|txt&variant_id=&download=
POST /documents/{id}/publications {platform,external_url,note,variant_id}   DELETE /publications/{id}
GET  /publish
POST /jobs/run {type:'brief', mock_only}
```

错误统一为 `{error, message, details}`（422 ValidationFailed / 404 NotFound / 503 NotConfigured；状态码取自 `core/errors.py` 的 `RadarError.status`）。

## 7. 前端要点

* `Editor.tsx`：本地状态（title/content/thesis）在稿件切换时从服务端灌入一次；`dirty` 触发 1.5 s 防抖 autosave；⌘/Ctrl+S 手动版本。
  保存请求按稿件顺序提交；旧请求完成不会清除新修改的未保存状态。浏览器本地保留未上传的标题、正文和核心判断，重新打开时恢复；关闭页面时提醒未保存内容。
  AI 请求、平台生成、母稿复制/导出和恢复版本前先提交当前正文；保存失败则停止该操作。预览统一经 DOMPurify 清洗后插入页面。
  文本选区通过 `onSelect/onKeyUp/onMouseUp` 捕获，供改写使用；AI 结果提供 插入到光标 / 替换选中 / 替换全文 / 设为标题 / 设为核心判断。
* 预览用 `marked`（同一份 Markdown，标题单独渲染为 H1；正文若已以 `# ` 开头则不再重复，后端 `split_leading_h1` 在导出 / 初稿里做同样处理）。
* 所有列表都显示 `ModeBadge`（实时 / 演示 / 混合 / 手动）。
* 布局为笔记本小屏设计（1280–1440 宽验证过）：
  * 侧栏可收起为 56 px 图标栏（编辑器内与 <1200 px 时默认收起，手动选择会记住）；分组「扩展工具 / 系统」可折叠。
  * 简报是紧凑列表：每条一行元信息 + 标题 + 判断，切口 chip 直接开写；「摘要」按钮展开正文摘要；区块可折叠并记住状态；忽略时行会滑出。
  * 编辑器右侧是 VS Code 式活动栏（AI / 素材 / 版本 / 平台版本 / 发布），点击同一图标即收起面板；⌘/Ctrl+\ 也可切换。视图（编辑 / 分栏 / 预览）、面板与页签都记在 localStorage。
  * 素材库详情在宽屏是右侧固定列，<1200 px 变成滑出抽屉。
* 通用组件在 `components/ui.tsx`：`Menu`（下拉菜单，Esc / 点击外部关闭，靠近底部自动上翻）、`Collapsible` / `Disclosure`（高度动画折叠）、`Segmented`（滑块分段控件）、`IconButton`（CSS tooltip）、`Skeleton`、`useStored`（localStorage 状态）；`components/toast.tsx` 提供 `useToast()` 全局提示；图标是 `components/icons.tsx` 里的内联 SVG，无外部依赖。
* 动效只用 CSS transition / keyframes（140–220 ms），`prefers-reduced-motion` 下关闭。列表行的入场动画使用 `animation-fill-mode: backwards`——`both` 会让行保留合成层，把下拉菜单压在下面。

## 8. 测试（`tests/test_studio.py`）

迁移原地升级（v2 → v3 保留数据）、演示种子生成评估与简报、规则评分确定性、简报动作（收藏 / 延伸 / 忽略）、
版本（自动 / 手动 / 恢复）、字数、素材绑定与搜索、AI 动作（fixture、数字警告、真实稿件 503）、平台版本 / 导出 / 发布记录、公众号 HTML 内联样式。
