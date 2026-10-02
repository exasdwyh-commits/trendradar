-- Job liveness (jobs/state.py): running jobs refresh heartbeat_at; rows whose heartbeat went stale
-- belong to a dead process and are marked failed with an 'interrupted:' error.
ALTER TABLE jobs ADD COLUMN heartbeat_at TEXT;
ALTER TABLE jobs ADD COLUMN owner TEXT;
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
