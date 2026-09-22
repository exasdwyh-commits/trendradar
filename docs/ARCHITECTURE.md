# 架构基线

## 一、删除掉什么

3.0 不再保留旧版这些产品假设：

- 国内热搜聚合
- 关键词热度榜
- 娱乐/体育/泛社会热点
- 多渠道消息推送
- Docker/Cherry Studio/MCP 教程型资产
- “信息越多越好”的大池展示
- 以热度/榜单位置作为主要价值判断

仓库只服务一个人：商业内容创作者。

## 二、五层数据流

```
Source Registry
→ Intelligence
→ Story Cluster
→ Candidate
→ Cognition / Writing
```

### 1. Source Registry
高质量来源清单，来源本身有角色和商业 Lane。

### 2. Intelligence
单篇材料。保留来源、发布时间、抓取时间、role、lane、原文 URL、证据质量。

### 3. Story Cluster
多篇报道同一事件只算一个事件。来源数量不等于独立事件数量。

### 4. Candidate
同一个事件同时产生两个互不相加的判断：
- cognition_score：值不值得进入长期世界模型
- content_score：值不值得写公众号

### 5. Cognition / Writing
认知线更新趋势；内容线才进入研究和写作。

## 三、趋势身份

模型每次不能自由发明趋势名。

输入必须带当前 ACTIVE/DRAFT 趋势列表，输出只能：
- MATCH_EXISTING(trend_id)
- PROPOSE_NEW

新趋势要求至少两个独立事件，且最好来自不同主体；否则保留 DRAFT。

## 四、模型槽位

业务代码永远只认槽位，不硬编码模型名。

FAST / COGNITION / RESEARCH / WRITING / CRITIC。

认知失败时不允许规则引擎伪装成认知结果。

## 五、定时

目标固定为 Asia/Shanghai 13:00 每日主轮次。

本地机器 13:00 没开：
- 下次启动发现今天没有成功轮次
- 补跑一次
- 不按照“每 20 小时”漂移

## 六、前台

默认首页只显示 3 条。

后台可以有 10–15 条认知候选，但不能把信息池推给用户。

页面优先级：
1. 今日重点
2. 待我决定
3. 趋势变化
4. 研究/创作
5. 专业工具
