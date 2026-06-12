-- =============================================================================
-- Reconciliation AI Agent — Initial Schema
-- RFP: DOF AI Government Financial Intelligence, Use Case 5
-- Run:  psql -U postgres -d reconciliation_db -f migrations/001_initial_schema.sql
-- =============================================================================

-- Enable pgcrypto for password hashing support
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- ENUMS
-- =============================================================================

CREATE TYPE source_type      AS ENUM ('bank', 'ledger', 'erp', 'manual');
CREATE TYPE txn_status       AS ENUM ('pending', 'matched', 'exception', 'excluded');
CREATE TYPE match_type       AS ENUM ('1:1', '1:many', 'many:many');
CREATE TYPE match_status     AS ENUM ('auto_matched', 'pending_review', 'confirmed', 'rejected');
CREATE TYPE exception_type   AS ENUM ('unmatched', 'low_confidence', 'ambiguous', 'duplicate');
CREATE TYPE priority_level   AS ENUM ('critical', 'high', 'medium', 'low');
CREATE TYPE exception_status AS ENUM ('open', 'in_review', 'resolved', 'escalated', 'closed');
CREATE TYPE action_type      AS ENUM ('manual_match', 'reject', 'split', 'escalate', 'writeoff');
CREATE TYPE approval_status  AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE run_status       AS ENUM ('running', 'completed', 'failed');

-- =============================================================================
-- RBAC
-- =============================================================================

CREATE TABLE roles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(64)   NOT NULL UNIQUE,
    name_ar     VARCHAR(128)  NOT NULL DEFAULT '',
    permissions JSONB         NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(64)  NOT NULL UNIQUE,
    full_name       VARCHAR(256) NOT NULL,
    full_name_ar    VARCHAR(256) NOT NULL DEFAULT '',
    email           VARCHAR(256) NOT NULL UNIQUE,
    hashed_password VARCHAR(256) NOT NULL,
    role_id         INTEGER      NOT NULL REFERENCES roles(id),
    language_pref   VARCHAR(4)   NOT NULL DEFAULT 'en',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login      TIMESTAMPTZ
);

CREATE INDEX idx_users_role ON users(role_id);
CREATE INDEX idx_users_email ON users(email);

-- =============================================================================
-- INGESTION  (FR-05)
-- =============================================================================

CREATE TABLE transaction_sources (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(128)  NOT NULL,
    name_ar           VARCHAR(256)  NOT NULL DEFAULT '',
    source_type       source_type   NOT NULL,
    connection_config JSONB         NOT NULL DEFAULT '{}',
    is_active         BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE transactions (
    id               BIGSERIAL PRIMARY KEY,
    source_id        INTEGER         NOT NULL REFERENCES transaction_sources(id),
    external_id      VARCHAR(256),
    amount           NUMERIC(20, 4)  NOT NULL,
    currency         VARCHAR(8)      NOT NULL DEFAULT 'AED',
    transaction_date DATE            NOT NULL,
    value_date       DATE,
    description      TEXT,
    description_ar   TEXT,
    reference_no     VARCHAR(256),
    counterparty     VARCHAR(256),
    status           txn_status      NOT NULL DEFAULT 'pending',
    raw_data         JSONB           NOT NULL DEFAULT '{}',
    ingested_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_txn_source    ON transactions(source_id);
CREATE INDEX idx_txn_date      ON transactions(transaction_date);
CREATE INDEX idx_txn_status    ON transactions(status);
CREATE INDEX idx_txn_reference ON transactions(reference_no);
CREATE INDEX idx_txn_amount    ON transactions(amount);
-- Full-text search on description (bilingual)
CREATE INDEX idx_txn_desc_fts  ON transactions USING gin(to_tsvector('english', COALESCE(description, '')));

-- Keep updated_at current automatically
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$;

CREATE TRIGGER trg_txn_updated_at
BEFORE UPDATE ON transactions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- RECONCILIATION RUN
-- =============================================================================

CREATE TABLE reconciliation_runs (
    id                   SERIAL PRIMARY KEY,
    run_date             DATE        NOT NULL,
    source_a_id          INTEGER     NOT NULL REFERENCES transaction_sources(id),
    source_b_id          INTEGER     NOT NULL REFERENCES transaction_sources(id),
    total_transactions   INTEGER     NOT NULL DEFAULT 0,
    matched_count        INTEGER     NOT NULL DEFAULT 0,
    exception_count      INTEGER     NOT NULL DEFAULT 0,
    auto_reconciled_pct  FLOAT,
    status               run_status  NOT NULL DEFAULT 'running',
    started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ,
    duration_seconds     FLOAT,
    error_message        TEXT
);

CREATE INDEX idx_runs_date   ON reconciliation_runs(run_date);
CREATE INDEX idx_runs_status ON reconciliation_runs(status);

-- =============================================================================
-- MATCHING ENGINE  (FR-06)
-- =============================================================================

CREATE TABLE match_results (
    id                BIGSERIAL PRIMARY KEY,
    run_id            INTEGER      NOT NULL REFERENCES reconciliation_runs(id),
    transaction_a_id  BIGINT       NOT NULL REFERENCES transactions(id),
    transaction_b_id  BIGINT       NOT NULL REFERENCES transactions(id),
    match_type        match_type   NOT NULL,
    rule_matched      VARCHAR(128),
    confidence_score  FLOAT        NOT NULL,
    match_status      match_status NOT NULL DEFAULT 'pending_review',
    explanation       TEXT,                    -- human-readable SHAP explanation
    shap_values       JSONB,
    matched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_match_run        ON match_results(run_id);
CREATE INDEX idx_match_txn_a      ON match_results(transaction_a_id);
CREATE INDEX idx_match_txn_b      ON match_results(transaction_b_id);
CREATE INDEX idx_match_confidence ON match_results(confidence_score);
CREATE INDEX idx_match_status     ON match_results(match_status);

-- =============================================================================
-- EXCEPTION QUEUE  (FR-07)
-- =============================================================================

CREATE TABLE exception_queue (
    id                   BIGSERIAL PRIMARY KEY,
    run_id               INTEGER          NOT NULL REFERENCES reconciliation_runs(id),
    transaction_id       BIGINT           NOT NULL REFERENCES transactions(id),
    exception_type       exception_type   NOT NULL,
    priority_score       FLOAT            NOT NULL DEFAULT 0.0,
    priority_level       priority_level   NOT NULL DEFAULT 'medium',
    amount               NUMERIC(20, 4)   NOT NULL,
    currency             VARCHAR(8)       NOT NULL DEFAULT 'AED',
    assigned_to          INTEGER          REFERENCES users(id),
    status               exception_status NOT NULL DEFAULT 'open',
    ai_suggested_action  TEXT,
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    resolved_at          TIMESTAMPTZ
);

CREATE INDEX idx_exc_run      ON exception_queue(run_id);
CREATE INDEX idx_exc_txn      ON exception_queue(transaction_id);
CREATE INDEX idx_exc_status   ON exception_queue(status);
CREATE INDEX idx_exc_priority ON exception_queue(priority_level, priority_score DESC);
CREATE INDEX idx_exc_assigned ON exception_queue(assigned_to);

CREATE TABLE resolution_actions (
    id                     BIGSERIAL PRIMARY KEY,
    exception_id           BIGINT      NOT NULL REFERENCES exception_queue(id),
    action_type            action_type NOT NULL,
    resolved_by            INTEGER     NOT NULL REFERENCES users(id),
    resolution_notes       TEXT,
    matched_transaction_id BIGINT      REFERENCES transactions(id),
    ai_suggested           BOOLEAN     NOT NULL DEFAULT FALSE,
    approved_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_res_exception ON resolution_actions(exception_id);
CREATE INDEX idx_res_resolver  ON resolution_actions(resolved_by);

-- =============================================================================
-- WORKFLOW  (human-in-the-loop, FR-08)
-- =============================================================================

CREATE TABLE approval_workflows (
    id             SERIAL PRIMARY KEY,
    exception_id   BIGINT          NOT NULL REFERENCES exception_queue(id),
    step_no        INTEGER         NOT NULL DEFAULT 1,
    approver_id    INTEGER         NOT NULL REFERENCES users(id),
    status         approval_status NOT NULL DEFAULT 'pending',
    decision_notes TEXT,
    decided_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_approval_exception ON approval_workflows(exception_id);
CREATE INDEX idx_approval_approver  ON approval_workflows(approver_id);
CREATE INDEX idx_approval_status    ON approval_workflows(status);

CREATE TABLE notifications (
    id                  BIGSERIAL PRIMARY KEY,
    recipient_id        INTEGER     NOT NULL REFERENCES users(id),
    notification_type   VARCHAR(64) NOT NULL,
    title               VARCHAR(512) NOT NULL,
    title_ar            VARCHAR(512) NOT NULL DEFAULT '',
    message             TEXT         NOT NULL,
    message_ar          TEXT         NOT NULL DEFAULT '',
    related_entity_type VARCHAR(64),
    related_entity_id   BIGINT,
    is_read             BOOLEAN      NOT NULL DEFAULT FALSE,
    sent_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    read_at             TIMESTAMPTZ
);

CREATE INDEX idx_notif_recipient ON notifications(recipient_id);
CREATE INDEX idx_notif_unread    ON notifications(recipient_id, is_read) WHERE is_read = FALSE;

-- =============================================================================
-- AUDIT LOG  (FR-09 — immutable, append-only)
-- =============================================================================

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    event_type  VARCHAR(64)  NOT NULL,
    entity_type VARCHAR(64)  NOT NULL,
    entity_id   BIGINT,
    user_id     INTEGER      REFERENCES users(id),
    action      VARCHAR(256) NOT NULL,
    old_value   JSONB,
    new_value   JSONB,
    ip_address  VARCHAR(64),
    session_id  VARCHAR(256),
    timestamp   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_entity    ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_user      ON audit_log(user_id);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_audit_event     ON audit_log(event_type);

-- Prevent any UPDATE or DELETE on audit_log (immutability per RFP TR-11)
CREATE OR REPLACE FUNCTION audit_log_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is immutable — UPDATE and DELETE are not permitted';
END;
$$;

CREATE TRIGGER trg_audit_no_update
BEFORE UPDATE ON audit_log
FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

CREATE TRIGGER trg_audit_no_delete
BEFORE DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

-- =============================================================================
-- KPI SNAPSHOTS  (FR-09)
-- =============================================================================

CREATE TABLE kpi_snapshots (
    id                          SERIAL PRIMARY KEY,
    snapshot_date               DATE        NOT NULL,
    run_id                      INTEGER     REFERENCES reconciliation_runs(id),
    auto_reconciled_pct         FLOAT,       -- target ≥90-95%
    matching_accuracy           FLOAT,       -- target ≥98%
    manual_effort_reduction_pct FLOAT,       -- target ≥60-70%
    time_to_close_days          FLOAT,       -- target reduction 5-7 days
    exception_count             INTEGER      NOT NULL DEFAULT 0,
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kpi_date ON kpi_snapshots(snapshot_date);
CREATE INDEX idx_kpi_run  ON kpi_snapshots(run_id);

-- =============================================================================
-- SEED — default roles  (Finance Ops, Treasury Ops, Supervisor, Admin)
-- =============================================================================

INSERT INTO roles (name, name_ar, permissions) VALUES
(
    'admin',
    'مسؤول النظام',
    '{"all": true}'
),
(
    'supervisor',
    'مشرف',
    '{"reconciliation": ["read","write","approve"], "exceptions": ["read","write","approve","escalate"], "reports": ["read"], "users": ["read"]}'
),
(
    'finance_ops',
    'عمليات مالية',
    '{"reconciliation": ["read","write"], "exceptions": ["read","write"], "reports": ["read"]}'
),
(
    'treasury_ops',
    'عمليات الخزينة',
    '{"reconciliation": ["read"], "exceptions": ["read","write"], "reports": ["read"]}'
);

-- =============================================================================
-- DONE
-- =============================================================================
