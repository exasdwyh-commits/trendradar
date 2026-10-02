# Opportunity scoring

Every opportunity has nine dimension scores (0–100), each with a written reason, a confidence (0–1), the evidence ids
it relies on, and a `method` (`deterministic`, `model`, `fixture`, `unavailable`). They are stored in `opportunity_scores`
and shown verbatim in the UI ("Why this score").

| Dimension | Method | Inputs |
|---|---|---|
| Pain | model | severity, frequency, workarounds, emotional intensity in the signals |
| Demand | deterministic | `14·ln(1+signals) + 8·ln(1+users) + 6·min(sources,4) + 4·ln(1+engagement/50)` |
| Growth | deterministic | stage base (emerging 80, growing 65, stable 45, new 40, fading 20) + velocity + acceleration |
| Competition | deterministic | `0.40·validation + 0.35·(100−intensity) + 0.25·differentiation` where validation grows with the number of comparable products (0 products → 15, i.e. **no competition is not a plus**), intensity = 0.6·density + 0.4·maturity, differentiation grows with recurring complaints and low ratings |
| Gap | model | what competitors miss vs. what users ask for (complaints, missing features, pricing mismatch) |
| Monetization | model | explicit willingness to pay, business context, existing paid alternatives |
| Build ease | model | scope of an MVP, integrations, platform risk (higher = easier) |
| Distribution | model | where the persona gathers, launch channels, virality |
| Evidence confidence | deterministic | sources, signals, distinct users, recency, data mode (mock capped at 70), model availability (−15 when judgement dimensions are unavailable) |

When no analysis model is available the five judgement dimensions are stored as 50 with `method='unavailable'`, low
confidence, and the confidence dimension is penalised — the card is visibly weaker rather than silently invented.

## Final score

```
weights = pain .15 · demand .15 · growth .10 · competition .15 · gap .15 · monetization .10 · build_ease .10 · distribution .05
opportunity_score = Σ(weight × score) × (0.7 + 0.3 × confidence / 100)
```

Weights and Today thresholds live in `config/settings.yml` (`scoring.weights`, `today.min_score = 70`, `today.min_confidence = 60`, `today.max_items = 5`).

## Trend metrics

`velocity = mean/day(last 7 days) ÷ max(mean/day(prior 21 days), 0.4)`; `acceleration = velocity − velocity one week earlier`.
Stage: emerging (velocity ≥ 3 ∧ ≥5 signals ∧ ≥2 sources) · growing (velocity ≥ 1.5) · fading (velocity < 0.5) · stable · new (<3 signals).
Absolute counts never decide on their own.

## Grounding rules

* `pain_signals[].signal_id` and every `evidence_ids` entry must be an id that was in the model's input; unknown ids are dropped.
* `evidence_quote` must appear verbatim (after whitespace/case normalisation) in the signal; otherwise it is dropped and the pain signal's confidence is lowered.
* Builder-brief competitors are filtered to products we actually indexed.
