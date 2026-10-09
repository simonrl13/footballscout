-- M4a: demo predictions served by the tools API and agent, plus the agent's trace tables.
-- Run by scout_loader (`python -m scout.agent.demo`). scout_reader can read every table (default privileges);
-- scout_tracer (db/init/04-tracer.sh) can only read and append the agent_* tables.

-- One row per player in the demo population: data as of the last valuation date (2026-06-12), model output precomputed.
CREATE TABLE IF NOT EXISTS demo_players (
    player_id            integer PRIMARY KEY,
    name                 text NOT NULL,
    name_search          text NOT NULL,            -- lowercase, accents removed
    as_of                date NOT NULL,
    club                 text,
    league               text,
    position             text,
    sub_position         text,
    age                  real,
    value_eur            bigint NOT NULL,          -- latest Transfermarkt valuation on or before as_of
    value_date           date NOT NULL,
    predicted_log_change real NOT NULL,
    interval_low_log     real,                     -- 80% split-conformal interval
    interval_high_log    real,
    factors              jsonb NOT NULL,           -- top SHAP factors: [{feature, value, shap}]
    model_run_id         text NOT NULL
);
CREATE INDEX IF NOT EXISTS demo_players_name ON demo_players (name_search);

-- One row per Claude API call made by the agent.
CREATE TABLE IF NOT EXISTS agent_calls (
    id                 bigserial PRIMARY KEY,
    created_at         timestamptz NOT NULL DEFAULT now(),
    conversation_id    uuid NOT NULL,
    step               integer NOT NULL,
    model              text NOT NULL,
    input_tokens       integer,
    output_tokens      integer,
    cache_read_tokens  integer,
    cache_write_tokens integer,
    cost_usd           numeric(10, 6) NOT NULL,
    latency_ms         integer,
    stop_reason        text,
    tools              jsonb,                     -- tool calls requested in this step: [{name, input}]
    cached             boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS agent_calls_created ON agent_calls (created_at);

-- Guardrail violations (e.g. numbers in an answer that no tool result supports) and what was done about them.
CREATE TABLE IF NOT EXISTS agent_violations (
    id              bigserial PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    conversation_id uuid NOT NULL,
    kind            text NOT NULL,                -- number_check
    detail          jsonb NOT NULL,
    action          text NOT NULL                 -- retried | blocked
);

-- Development/eval response cache (AGENT_CACHE=true): identical requests are answered without an API call.
CREATE TABLE IF NOT EXISTS agent_cache (
    request_hash text PRIMARY KEY,
    response     jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'scout_tracer') THEN
        GRANT SELECT, INSERT ON agent_calls, agent_violations, agent_cache TO scout_tracer;
        GRANT USAGE ON SEQUENCE agent_calls_id_seq, agent_violations_id_seq TO scout_tracer;
    END IF;
END $$;
