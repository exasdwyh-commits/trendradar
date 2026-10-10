# Kern · TrendRadar Signal Board

TrendRadar exposes a self-contained daily intelligence page at:

```text
/signal-board
```

The page is server-rendered from the latest frozen candidate run, has no CDN or external JavaScript dependency, is responsive, and refreshes itself every five minutes. It is intended to be embedded in Kern as a lightweight iframe/webview panel.

The template stays fixed. Daily runs only change the underlying TrendRadar data.

Contents:

- counts for `NEW / RISING / TRACKING`;
- the current top three commercial signals;
- signal momentum deltas (rank, content score, independent sources);
- remaining tracked signals;
- ranking provenance (`RULE / FAST / COGNITION`).

The board is a presentation surface only. Evidence gates, candidate actions, research, thesis confirmation and publishing remain owned by the existing TrendRadar pipeline.
