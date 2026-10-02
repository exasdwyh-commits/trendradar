# Product Hunt integration

Product Hunt is the tier-1 supply source. We use the official **GraphQL API v2** (`https://api.producthunt.com/v2/api/graphql`)
with a developer token — no scraping.

## Setup

1. Create an application at <https://www.producthunt.com/v2/oauth/applications> and copy the **Developer Token**.
2. `.env`: `PRODUCTHUNT_MODE=graphql`, `PRODUCTHUNT_TOKEN=<token>`.
3. `trendradar sources --test` should report `producthunt supply live ok`.

Without a token the adapter runs in `mock` mode with bundled fictional products (clearly labelled Mock in the UI).
`PRODUCTHUNT_MODE=mcp` is reserved for a read-only MCP bridge; the GraphQL path is the supported one in V1.

## What the API gives us — and what it does not

The v2 API has **no keyword search over posts**. It offers `posts(topic, order, postedAfter, postedBefore, featured)`,
`post(slug)` and `topics(query)`. Consequences for the design:

* **Semantic product search = local vector index.** Every collected post is embedded (`name + tagline + description + topics`)
  and searched by cosine similarity (`market.competition.search_products`). `topics(query)` + `posts(topic)` is used as an
  on-demand expansion when a live cluster needs more supply data (`expand_supply`).
* **Trending** = `posts(order: VOTES, postedAfter: now − 7d/30d/month)`; **latest** = `order: NEWEST` per configured topic.
* **Pros/cons/pricing are not API fields.** We collect a sample of comments per post and derive pros / cons / complaints /
  a pricing guess with the FAST model. These are stored in `product_insights` with `derived_from='comments'` and the sample
  size, and pricing set this way is marked `pricing_origin='inferred'`. The UI shows these labels.
* Rate limit: 6,250 complexity points / 15 min. The client reads `X-Rate-Limit-Remaining/Reset`, backs off on 429, and each
  fetch is bounded by `max_per_round`.

## Data mapping

| GraphQL field | products column |
|---|---|
| `id`, `slug`, `name`, `tagline`, `description`, `url`, `website` | same |
| `votesCount`, `commentsCount`, `reviewsRating`, `reviewsCount` | `votes`, `comments`, `rating`, `review_count` |
| `createdAt` / `featuredAt` | `launched_at` |
| `topics.edges.node.name` | `categories_json` |
| `makers` | `makers_json` |
| comment sample | `raw_json.comment_samples` → `product_insights` |

## Competition profile (per pain cluster)

Top-k products by similarity (relative threshold to the best hit; live clusters never pit against mock products) →
`competitor_count`, `density` (count + launches in 90 days), `maturity` (votes, age, paid share), `avg_rating`,
`review_volume`, `recent_launches_90d`, `common_features`, `common_complaints`, `pricing_distribution`. Stored in
`competition_profiles` and linked with `solved_by` edges.
