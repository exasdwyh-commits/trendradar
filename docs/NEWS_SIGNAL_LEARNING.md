# News Signal Learning

This note records the first selective integration inspired by `Rion-Wu-tech/ai-daily-briefing`.

TrendRadar does **not** import that project wholesale. TrendRadar already owns the broader evidence pipeline: source roles, cross-source corroboration, clustering, cognition, research, thesis, writing, publication snapshots and blind evaluation. The borrowed ideas are limited to gaps that improve observability and long-term calibration without weakening provenance.

## Added in schema v6

### 1. Source health history

`source_health` remains the current snapshot used by the UI and operations API.

`source_health_history` is append-only and records every insert/update of the snapshot through SQLite triggers:

- source id
- checked time
- success / failure
- item count
- latency
- error

This makes seven-day or longer source-quality analysis possible. A transient outage no longer overwrites the evidence of earlier healthy runs.

API:

- `GET /api/source-health/history?days=7&limit=500`

The response contains recent checks plus per-source aggregate success/failure counts, average latency and average item count.

### 2. Candidate feedback ledger

`candidate_feedback` records explicit editorial behavior:

- `OPENED` = +1
- `SAVED` = +3
- `DRAFTED` = +5
- `PUBLISHED` = +8
- `DISMISSED` = -6

API:

- `POST /api/candidates/{candidate_id}/feedback`
- `GET /api/feedback`

A publication status transition to `PUBLISHED` also writes a `PUBLISHED` feedback event automatically when the publication can be traced back to a candidate.

## Important calibration rule

Feedback is **not** injected into candidate scores yet.

This is intentional. TrendRadar's architecture requires stable evidence before modifying ranking policy. First collect behavior, then compare it with Blind 10→3, source yield, publication outcomes and judgement reviews. Only after enough independent runs should a bounded feedback prior be considered.

Recommended minimum before ranking changes:

- at least 14 daily candidate runs;
- feedback from multiple actions, not only opens;
- no single source or single topic dominating the sample;
- calibration reviewed separately for RULE / FAST / COGNITION ranking modes.

## Next selective integrations

Useful follow-ups from the reference project, in priority order:

1. richer official changelog/model-release adapters where TrendRadar source coverage is still weak;
2. source-health trend display in the frontend;
3. candidate feedback controls in the frontend;
4. first-seen / strengthening / persistent signal labels derived from existing candidate-run history;
5. Kern-facing `news-radar` skill that returns 1–3 actionable opportunities instead of a generic news digest.

Do not replace TrendRadar's evidence gates, cognition, research or publication provenance with a briefing-only pipeline.
