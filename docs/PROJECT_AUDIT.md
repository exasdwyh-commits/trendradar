# TrendRadar 3.1 — 宏观架构审查与迭代基线

> 本文不是功能清单，而是后续所有改造的结构约束。原则：先保证系统判断链可信，再优化体验；先修根因，再修表现；每轮改动都必须经过回归测试或真实 Smoke。

## 1. 产品边界

TrendRadar 只服务一个目标：

**高质量商业信号 → 可靠认知 → 自主创作 → 多平台表达 → 发布与长期复盘。**

明确不做：

- 泛热搜 / 娱乐 / 体育 / 明星聚合；
- 为了“资讯量”堆低质量来源；
- 用单一综合分数代表“真相”；
- 未经证据支撑的自动写作；
- 为旧版测试产品保留兼容层。

## 2. 五层架构

### A. Intelligence — 输入层

职责：

- 来源注册、Tier、Role、健康度与 Yield；
- RSS / HTML / 专用 Adapter；
- 规范化 URL、正文、发布时间；
- Story Cluster；
- 多源交叉验证。

硬约束：

- Discovery 不能单独支撑高置信结论；
- WRITE 至少需要两个独立来源，其中至少一个 PRIMARY / VERIFIER；
- 采集失败必须可观测，不能静默。

### B. Cognition — 判断层

职责：

- Rule → FAST → COGNITION 分层筛选；
- Content Rank 与 Cognition Rank 分离；
- Trend MATCH_EXISTING / PROPOSE_NEW；
- SUPPORT / COUNTER / UNCERTAIN；
- Candidate Run Freeze；
- Blind 10→3 与长期校准。

硬约束：

- 每个 Blind Round 必须记录当时的 ranking mode：RULE / FAST / COGNITION；
- 不把规则排名与真实 COGNITION 排名混在一起做效果判断；
- Blind 结果只做诊断，不能根据单日结果自动调权；
- 趋势晋级依赖独立事件与独立主体，不依赖同一主体重复新闻。

### C. Research — 证据层

职责：

- FACT / CLAIM / INFER 分离；
- 每个研究单元绑定 intelligence id；
- strongest counter；
- evidence gap；
- Thesis 与 falsification signal。

硬约束：

- FACT / CLAIM 无有效 evidence id 时自动丢弃；
- 至少两个可追溯研究单元；
- 至少两个 evidence item；
- 至少两个独立来源；
- 至少包含 PRIMARY / VERIFIER，才能进入 Thesis。

### D. Studio — 创作层

职责：

- Thesis → Writer → TipTap 母稿；
- 局部 AI 修改；
- 版本历史；
- 文章实际使用证据；
- Challenger；
- 配图方案；
- 多平台 Variant。

硬约束：

- AI 生成文章发布前必须通过 Challenger；
- Writer / AI Edit / Platform Variant 不允许新造关键数字；
- DATA_CHART 必须绑定真实 evidence id；
- 发布 Snapshot 冻结的是文章实际绑定证据，而不是整个候选池。

### E. Runtime — 运行层

职责：

- SQLite 持久化；
- Daily Scheduler；
- Model Gateway；
- AI Telemetry / Budget；
- CI / Live Smoke；
- Web API。

硬约束：

- 模型不可用时必须显式 degraded；
- 任何模型故障不能伪装成“AI已判断”；
- 自动任务必须有调用次数/费用边界；
- GitHub Actions Smoke 是干净环境验收，不是生产数据库。

## 3. 当前结构审查

### 已稳定 / 继续保护

- 单一 master 产品线，旧热榜逻辑已退出核心路径；
- 采集 → 聚类 → 候选 → 排名 → Candidate Freeze → Blind；
- 来源质量、交叉验证、Source Yield；
- Trend 证据与 revision；
- Research → Thesis → Writer → Challenger → Publish Snapshot；
- TipTap、版本、配图建议、平台 Variant；
- AI Gateway retry / telemetry / cost guard；
- Falsification tests 与真实网络 Live Smoke。

### 仍需继续治理

#### P0：正确性

1. **研究来源独立性**
   - evidence id 多不等于来源独立；
   - Thesis gate 必须按 source_id 判断。
   - 状态：已进入修复。

2. **排名 provenance**
   - Rule-only 与 Cognition 结果不能混在同一 Blind 指标里解释。
   - 状态：已进入修复。

3. **SQLite Web 并发边界**
   - 当前 Web App 长期持有一个 SQLite connection；
   - 本地单用户压力不高，但异步前端请求与长模型调用可能造成事务交叉风险。
   - 目标：逐步切换到 request-scoped connections / 明确写事务边界。

#### P1：可维护性

1. `frontend/src/App.tsx` 已承担过多页面职责；
2. `web.py` 同时承担 API contract、路由和业务调用；
3. `content.py` 同时承担 Document、AI Edit、Media、Platform、Publish。

目标不是为了“漂亮目录”重构，而是在下一次明显新增功能前完成拆分：

- `frontend/src/views/*`
- `api/read.py / api/editorial.py / api/content.py / api/ops.py`
- `services/documents.py / services/media.py / services/publishing.py`

拆分必须保持 API 和数据库行为不变，并在 CI 全绿后逐步推进。

#### P2：运行与交付

1. GitHub Actions 的 SQLite 是临时文件，不能作为长期认知资产；
2. 真正每日运行仍应在本地 Mac / 常驻服务器 / 持久化数据库环境；
3. 多平台目前以生成与导出为主，真实直发要按平台授权逐个接；
4. 带真实模型的全链路验收需要运行环境提供合法的模型配置，不能把密钥写入仓库。

## 4. 迭代方法

后续每轮固定执行：

1. **宏观审查**
   - 数据流是否仍符合产品目标；
   - 有没有重复模块、错误抽象或旧逻辑回流；
   - 新功能是否破坏证据链、人工决策权或可复盘性。

2. **找最小根因**
   - 优先修数据模型 / gate / contract；
   - 不先用 UI 补丁遮住后端问题。

3. **微观修复**
   - 一次解决一个边界；
   - 同时补 falsification / regression test。

4. **CI**
   - Backend；
   - Falsification；
   - CLI；
   - Frontend Build。

5. **真实 Smoke**
   - 涉及采集、来源、调度、网络变化时，在 GitHub Runner 重新跑 live-smoke；
   - 涉及模型质量时，在真实模型环境运行，不用 Mock 结果冒充效果验证。

6. **只根据稳定数据校准**
   - Source Yield：至少积累多个运行日再降权；
   - Blind 10→3：至少 3 轮才展示初步方向，14 轮再考虑策略修改；
   - 判断正确性：依赖时间与 evidence，而不是阅读量。

## 5. 当前开发顺序

当前顺序保持：

**P0 正确性与 provenance → 运行稳定 → 前后端模块拆分 → 实际模型校准 → 平台直发。**

暂不为了“功能完整”增加大量外围能力。任何新能力都必须回答两个问题：

1. 它是否提高了商业判断质量或创作效率？
2. 它是否保持了证据可追溯、人工可控制、未来可复盘？

如果两个答案都是否，就不进入核心产品。
