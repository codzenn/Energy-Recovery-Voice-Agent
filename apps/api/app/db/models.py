SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id),
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS calls_lead_id ON calls(lead_id);
CREATE TABLE IF NOT EXISTS dnc (
    lead_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS call_messages (
    call_id TEXT REFERENCES calls(call_id), position INTEGER, data TEXT NOT NULL,
    PRIMARY KEY(call_id, position)
);
CREATE TABLE IF NOT EXISTS collected_fields (
    call_id TEXT REFERENCES calls(call_id), field TEXT, value TEXT NOT NULL,
    PRIMARY KEY(call_id, field)
);
CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id TEXT PRIMARY KEY, call_id TEXT REFERENCES calls(call_id), data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journey_submissions (
    submission_id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dnc_checks (
    id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, blocked INTEGER NOT NULL, timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    call_id TEXT REFERENCES calls(call_id), position INTEGER, data TEXT NOT NULL,
    PRIMARY KEY(call_id, position)
);
"""
