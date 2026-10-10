# Daily Signal Board

TrendRadar now derives candidate momentum from frozen `candidate_runs` instead of treating every daily brief as a fresh list.

## States

- `NEW` / 首次出现：候选第一次进入冻结候选池。
- `RISING` / 持续升温：相较上一轮，满足任一条件：内容分 +5、内容排名上升 3 位、独立来源数增加。
- `TRACKING` / 持续跟踪：仍在候选池，但没有达到升温阈值。

The state is diagnostic metadata. It does not override evidence gates, action, cognition provenance, or content ranking.

## Board

`GET /api/signals` returns the latest frozen candidate run, ranking mode, state counts and the current signal list. `/api/dashboard` includes the same board so the Today page can render a single daily intelligence surface.

Opening a candidate from the Today board records an `OPENED` feedback event. Feedback remains observational until enough history exists for explicit calibration.
