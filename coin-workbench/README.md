# 硬币先生 · 趋势认知与公众号创作工作台

这是一个与 TrendRadar 原有功能隔离的新工作区。它不是“新闻聚合器”，而是把全球公开信息转化为：

1. 每天 3–5 条真正值得理解的高价值信号；
2. 可持续更新的长期趋势与反证链；
3. 经过研究、观点确认、写作、挑战者审查后的公众号文章；
4. 可在 3/6/12 个月后复盘的判断账本。

## 为什么单独建这一层

现有 TrendRadar 更擅长“抓取 + 热点/关键词 + AI 摘要”。当前仓库配置仍包含大量国内热榜与少量 RSS，这适合热点雷达，但不适合“全球趋势认知 + 高质量公众号”。

本项目不直接破坏 TrendRadar 主流程，而是把它当作可选采集器之一，并新增：

- 高质量第一方信源目录
- 四条信息主线：科技 / 商业产业 / 民生 / 社会结构
- 事实层与认知层分离
- “值得长期理解”与“值得写公众号”两条独立下游
- Trend Evidence / Counter Evidence
- 硬币先生双面分析
- 人工观点确认 Gate
- Writer 与 Challenger 分离
- 每周世界模型变化
- 判断账本

## 默认用户体验

打开工作台时，不展示几百条新闻。

默认首页只回答三个问题：

- 今天哪 3 件事值得我真正理解？
- 哪 1 件最值得继续研究或写？
- 哪个长期判断发生了变化？

详细情报池、评分、调用日志、来源状态全部下沉到“专业工具”。

## 目标流水线

```
Sources
  ↓
Raw Intelligence
  ↓
Normalize / Deduplicate / Cluster
  ↓
Evidence Gate
  ├──────────────┐
  ↓              ↓
Cognition Pool   Content Candidate Pool
  ↓              ↓
Trend Update     TOP 3–5
  ↓              ↓
World Model      Research
                  ↓
                Thesis Gate
                  ↓
                Draft
                  ↓
                Challenger
                  ↓
                Publish / Archive
```

## 当前开发策略

- 不直接重写 TrendRadar。
- 新代码全部放在 `coin-workbench/`。
- 第一阶段先把“信源质量 + 证据模型 + 双线路由”做对。
- 第二阶段再做研究和写作。
- 第三阶段才做自动发布、数据表现和长期复盘。

详见 `docs/PRODUCT.md` 与 `config/sources.yml`。
