-- Daily "Today" selection: which opportunities were shown on a given day and why.
CREATE TABLE IF NOT EXISTS today_picks (
  day TEXT NOT NULL,
  opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  rank INTEGER NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (day, opportunity_id)
);
CREATE INDEX IF NOT EXISTS idx_today_picks_day ON today_picks(day, rank);
