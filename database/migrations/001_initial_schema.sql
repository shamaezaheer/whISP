-- =============================================================================
-- Migration: 001_initial_schema.sql
-- Description: Initial PostgreSQL + TimescaleDB schema for ISP management platform
-- Requires: PostgreSQL 15+, TimescaleDB 2.x, pgcrypto extension
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "timescaledb" CASCADE;
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
CREATE EXTENSION IF NOT EXISTS "citext";

-- ---------------------------------------------------------------------------
-- Helper function: auto-update updated_at column
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TABLE: franchisees
-- Top-level tenant entity. Each franchisee is an ISP reseller.
-- =============================================================================
CREATE TABLE franchisees (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    code                VARCHAR(20)     UNIQUE NOT NULL,
    name                VARCHAR(255)    NOT NULL,
    contact_person      VARCHAR(255),
    phone               VARCHAR(20),
    email               VARCHAR(255)    UNIQUE,
    subdomain           VARCHAR(100)    UNIQUE NOT NULL,
    address             TEXT,
    status              VARCHAR(20)     NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'active', 'suspended', 'terminated')),
    bandwidth_pool_mbps INTEGER         NOT NULL DEFAULT 100,
    balance_amount      DECIMAL(12,2)   NOT NULL DEFAULT 0.00,
    credit_limit        DECIMAL(12,2)   NOT NULL DEFAULT 50000.00,
    radius_secret       VARCHAR(255),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    approved_at         TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

CREATE INDEX idx_franchisees_status     ON franchisees (status)     WHERE deleted_at IS NULL;
CREATE INDEX idx_franchisees_subdomain  ON franchisees (subdomain)  WHERE deleted_at IS NULL;
CREATE INDEX idx_franchisees_code       ON franchisees (code);

CREATE TRIGGER trg_franchisees_updated_at
    BEFORE UPDATE ON franchisees
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMENT ON TABLE  franchisees IS 'ISP franchisee/reseller tenants. Each row represents a distinct ISP business operating under the platform.';
COMMENT ON COLUMN franchisees.code IS 'Short alphanumeric identifier used in RADIUS realm and billing references.';
COMMENT ON COLUMN franchisees.bandwidth_pool_mbps IS 'Total allocated bandwidth pool in Megabits per second for this franchisee.';
COMMENT ON COLUMN franchisees.balance_amount IS 'Current wallet/prepaid balance in platform currency (BDT).';
COMMENT ON COLUMN franchisees.credit_limit IS 'Maximum negative balance allowed before service suspension.';
COMMENT ON COLUMN franchisees.radius_secret IS 'Shared secret used for RADIUS authentication between NAS devices and the RADIUS server.';

-- =============================================================================
-- TABLE: franchisee_users
-- Staff/admin users who belong to a franchisee.
-- =============================================================================
CREATE TABLE franchisee_users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    franchisee_id   UUID        NOT NULL REFERENCES franchisees (id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    phone           VARCHAR(20),
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'admin'
                        CHECK (role IN ('owner', 'admin', 'staff', 'readonly')),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_login      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_franchisee_users_franchisee_id ON franchisee_users (franchisee_id);
CREATE INDEX idx_franchisee_users_email         ON franchisee_users (email);
CREATE INDEX idx_franchisee_users_is_active     ON franchisee_users (franchisee_id, is_active);

CREATE TRIGGER trg_franchisee_users_updated_at
    BEFORE UPDATE ON franchisee_users
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMENT ON TABLE  franchisee_users IS 'Operator and staff accounts associated with a franchisee. Controls access to the franchisee dashboard.';
COMMENT ON COLUMN franchisee_users.role IS 'owner=full control including billing; admin=full operational; staff=day-to-day ops; readonly=view only.';

-- =============================================================================
-- TABLE: plans
-- Internet subscription plans. NULL franchisee_id = global/platform plan.
-- =============================================================================
CREATE TABLE plans (
    id                      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    franchisee_id           UUID            REFERENCES franchisees (id) ON DELETE CASCADE,
    name                    VARCHAR(255)    NOT NULL,
    name_bn                 VARCHAR(255),
    description             TEXT,
    speed_download_kbps     INTEGER         NOT NULL CHECK (speed_download_kbps > 0),
    speed_upload_kbps       INTEGER         NOT NULL CHECK (speed_upload_kbps > 0),
    speed_throttle_kbps     INTEGER         NOT NULL DEFAULT 512 CHECK (speed_throttle_kbps > 0),
    data_cap_gb             INTEGER         CHECK (data_cap_gb > 0),
    validity_days           INTEGER         NOT NULL DEFAULT 30 CHECK (validity_days > 0),
    price                   DECIMAL(10,2)   NOT NULL CHECK (price >= 0),
    currency                VARCHAR(3)      NOT NULL DEFAULT 'BDT',
    ott_chorki              BOOLEAN         NOT NULL DEFAULT FALSE,
    ott_hoichoi             BOOLEAN         NOT NULL DEFAULT FALSE,
    ott_binge               BOOLEAN         NOT NULL DEFAULT FALSE,
    ott_toffee              BOOLEAN         NOT NULL DEFAULT FALSE,
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_plans_franchisee_id    ON plans (franchisee_id) WHERE is_active = TRUE;
CREATE INDEX idx_plans_is_active        ON plans (is_active);
-- Global plans (NULL franchisee_id) index for platform-wide lookups
CREATE INDEX idx_plans_global           ON plans (id) WHERE franchisee_id IS NULL AND is_active = TRUE;

CREATE TRIGGER trg_plans_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMENT ON TABLE  plans IS 'Internet subscription plan definitions. Plans with NULL franchisee_id are platform-global and available to all franchisees.';
COMMENT ON COLUMN plans.speed_throttle_kbps IS 'Speed applied after data_cap_gb is exhausted (fair-use throttle).';
COMMENT ON COLUMN plans.data_cap_gb IS 'Monthly data allowance in GB. NULL means unlimited.';

-- =============================================================================
-- TABLE: subscribers
-- End-user subscribers managed by a franchisee.
-- =============================================================================
CREATE TABLE subscribers (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    franchisee_id       UUID        NOT NULL REFERENCES franchisees (id) ON DELETE RESTRICT,
    plan_id             UUID        REFERENCES plans (id) ON DELETE SET NULL,
    username            VARCHAR(255) UNIQUE NOT NULL,
    password_hash       VARCHAR(255) NOT NULL,
    pppoe_username      VARCHAR(255) UNIQUE NOT NULL,
    pppoe_password      VARCHAR(255) NOT NULL,
    name                VARCHAR(255) NOT NULL,
    phone               VARCHAR(20) UNIQUE,
    email               VARCHAR(255),
    nid_number          VARCHAR(50),
    address             TEXT,
    status              VARCHAR(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'terminated', 'pending')),
    ip_address          INET,
    plan_expires_at     TIMESTAMPTZ,
    data_used_bytes     BIGINT      NOT NULL DEFAULT 0 CHECK (data_used_bytes >= 0),
    data_cap_bytes      BIGINT      CHECK (data_cap_bytes > 0),
    bkash_agreement_id  VARCHAR(255),
    nagad_account       VARCHAR(20),
    fcm_token           VARCHAR(500),
    quota_reset_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_subscribers_franchisee_id  ON subscribers (franchisee_id);
CREATE INDEX idx_subscribers_plan_id        ON subscribers (plan_id);
CREATE INDEX idx_subscribers_status         ON subscribers (franchisee_id, status);
CREATE INDEX idx_subscribers_pppoe_username ON subscribers (pppoe_username);
CREATE INDEX idx_subscribers_plan_expires   ON subscribers (plan_expires_at) WHERE status = 'active';
CREATE INDEX idx_subscribers_ip_address     ON subscribers (ip_address) WHERE ip_address IS NOT NULL;

CREATE TRIGGER trg_subscribers_updated_at
    BEFORE UPDATE ON subscribers
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMENT ON TABLE  subscribers IS 'End-user internet subscribers. Each subscriber belongs to exactly one franchisee.';
COMMENT ON COLUMN subscribers.pppoe_username IS 'PPPoE/RADIUS authentication username sent by CPE/router.';
COMMENT ON COLUMN subscribers.pppoe_password IS 'PPPoE/RADIUS authentication password (stored encrypted at application layer).';
COMMENT ON COLUMN subscribers.data_used_bytes IS 'Cumulative bytes consumed in current billing cycle. Reset on quota_reset_at.';
COMMENT ON COLUMN subscribers.data_cap_bytes IS 'Byte equivalent of plan data_cap_gb; copied from plan at provisioning time.';
COMMENT ON COLUMN subscribers.bkash_agreement_id IS 'bKash tokenized payment agreement ID for auto-renewal.';

-- =============================================================================
-- TABLE: nas_devices
-- Network Access Servers (routers/AP controllers) that authenticate via RADIUS.
-- =============================================================================
CREATE TABLE nas_devices (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    franchisee_id   UUID        NOT NULL REFERENCES franchisees (id) ON DELETE CASCADE,
    nasname         VARCHAR(255) NOT NULL,
    shortname       VARCHAR(50),
    type            VARCHAR(50) NOT NULL DEFAULT 'mikrotik'
                        CHECK (type IN ('mikrotik', 'cisco', 'juniper', 'ubiquiti', 'huawei', 'other')),
    ports           INTEGER     NOT NULL DEFAULT 1812,
    secret          VARCHAR(255) NOT NULL,
    server          VARCHAR(255),
    community       VARCHAR(255) NOT NULL DEFAULT 'public',
    description     TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_seen       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_nas_devices_franchisee_id  ON nas_devices (franchisee_id);
CREATE INDEX idx_nas_devices_nasname        ON nas_devices (nasname);
CREATE INDEX idx_nas_devices_is_active      ON nas_devices (franchisee_id, is_active);

COMMENT ON TABLE  nas_devices IS 'RADIUS Network Access Server inventory. Maps physical routers/APs to franchisees for CoA and accounting.';
COMMENT ON COLUMN nas_devices.nasname IS 'IP address or hostname of the NAS device as registered in FreeRADIUS nas table.';
COMMENT ON COLUMN nas_devices.community IS 'SNMP community string for bandwidth monitoring via SNMP polling.';

-- =============================================================================
-- RADIUS TABLES
-- Schema compatible with FreeRADIUS rlm_sql module.
-- These use SERIAL (integer) PKs to match FreeRADIUS expectations.
-- =============================================================================

-- radcheck: per-user check items (Auth conditions)
CREATE TABLE radcheck (
    id          SERIAL          PRIMARY KEY,
    username    VARCHAR(64)     NOT NULL DEFAULT '',
    attribute   VARCHAR(64)     NOT NULL DEFAULT '',
    op          VARCHAR(2)      NOT NULL DEFAULT ':=',
    value       VARCHAR(253)    NOT NULL DEFAULT ''
);

CREATE INDEX idx_radcheck_username ON radcheck (username);

COMMENT ON TABLE  radcheck IS 'FreeRADIUS per-user check attributes. Controls authentication and authorization conditions.';
COMMENT ON COLUMN radcheck.op IS 'RADIUS operator: := (assign), == (equals), >= (gte), <= (lte), =~ (regex), !* (not present).';

-- radreply: per-user reply items (attributes sent back to NAS after auth)
CREATE TABLE radreply (
    id          SERIAL          PRIMARY KEY,
    username    VARCHAR(64)     NOT NULL DEFAULT '',
    attribute   VARCHAR(64)     NOT NULL DEFAULT '',
    op          VARCHAR(2)      NOT NULL DEFAULT '=',
    value       VARCHAR(253)    NOT NULL DEFAULT ''
);

CREATE INDEX idx_radreply_username ON radreply (username);

COMMENT ON TABLE  radreply IS 'FreeRADIUS per-user reply attributes returned to NAS post-authentication (e.g., IP assignment, rate-limit policies).';

-- radgroupcheck: group-level check items
CREATE TABLE radgroupcheck (
    id          SERIAL          PRIMARY KEY,
    groupname   VARCHAR(64)     NOT NULL DEFAULT '',
    attribute   VARCHAR(64)     NOT NULL DEFAULT '',
    op          VARCHAR(2)      NOT NULL DEFAULT ':=',
    value       VARCHAR(253)    NOT NULL DEFAULT ''
);

CREATE INDEX idx_radgroupcheck_groupname ON radgroupcheck (groupname);

COMMENT ON TABLE radgroupcheck IS 'FreeRADIUS group-level check attributes. Used for plan-based policy groups.';

-- radgroupreply: group-level reply items
CREATE TABLE radgroupreply (
    id          SERIAL          PRIMARY KEY,
    groupname   VARCHAR(64)     NOT NULL DEFAULT '',
    attribute   VARCHAR(64)     NOT NULL DEFAULT '',
    op          VARCHAR(2)      NOT NULL DEFAULT '=',
    value       VARCHAR(253)    NOT NULL DEFAULT ''
);

CREATE INDEX idx_radgroupreply_groupname ON radgroupreply (groupname);

COMMENT ON TABLE radgroupreply IS 'FreeRADIUS group-level reply attributes. Typically holds Mikrotik-Rate-Limit and Session-Timeout per plan group.';

-- radusergroup: maps users to groups
CREATE TABLE radusergroup (
    id          SERIAL          PRIMARY KEY,
    username    VARCHAR(64)     NOT NULL DEFAULT '',
    groupname   VARCHAR(64)     NOT NULL DEFAULT '',
    priority    INTEGER         NOT NULL DEFAULT 1
);

CREATE INDEX idx_radusergroup_username  ON radusergroup (username);
CREATE INDEX idx_radusergroup_groupname ON radusergroup (groupname);
CREATE UNIQUE INDEX idx_radusergroup_user_group ON radusergroup (username, groupname);

COMMENT ON TABLE radusergroup IS 'FreeRADIUS user-to-group membership. Priority determines which group attributes take precedence.';

-- =============================================================================
-- TABLE: radacct (TimescaleDB Hypertable)
-- RADIUS accounting records. Partitioned monthly by acctstarttime.
-- =============================================================================
CREATE TABLE radacct (
    radacctid               BIGSERIAL,
    acctsessionid           VARCHAR(64),
    acctuniqueid            VARCHAR(32)     UNIQUE,
    username                VARCHAR(64),
    realm                   VARCHAR(64),
    nasipaddress            INET,
    nasportid               VARCHAR(50),
    nasporttype             VARCHAR(32),
    acctstarttime           TIMESTAMPTZ     NOT NULL,
    acctupdatetime          TIMESTAMPTZ,
    acctstoptime            TIMESTAMPTZ,
    acctinterval            INTEGER,
    acctsessiontime         INTEGER,
    acctauthentic           VARCHAR(32),
    connectinfo_start       VARCHAR(50),
    connectinfo_stop        VARCHAR(50),
    acctinputoctets         BIGINT          NOT NULL DEFAULT 0,
    acctoutputoctets        BIGINT          NOT NULL DEFAULT 0,
    calledstationid         VARCHAR(50),
    callingstationid        VARCHAR(50),
    acctterminatecause      VARCHAR(32),
    servicetype             VARCHAR(32),
    framedprotocol          VARCHAR(32),
    framedipaddress         INET,
    framedipv6address       VARCHAR(50),
    framedipv6prefix        VARCHAR(50),
    framedinterfaceid       VARCHAR(50),
    delegatedipv6prefix     VARCHAR(50),
    acctstartdelay          INTEGER,
    acctstopdelay           INTEGER,
    xascendsessionsvrkey    VARCHAR(10)
);

-- TimescaleDB hypertable: partition by acctstarttime, monthly chunks
SELECT create_hypertable(
    'radacct',
    'acctstarttime',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists       => TRUE
);

-- Compression policy: compress chunks older than 3 months
SELECT add_compression_policy('radacct', INTERVAL '3 months', if_not_exists => TRUE);

-- Retention policy: drop chunks older than 24 months (adjust per compliance needs)
SELECT add_retention_policy('radacct', INTERVAL '24 months', if_not_exists => TRUE);

CREATE INDEX idx_radacct_username        ON radacct (username,        acctstarttime DESC);
CREATE INDEX idx_radacct_nasipaddress    ON radacct (nasipaddress,    acctstarttime DESC);
CREATE INDEX idx_radacct_acctstoptime    ON radacct (acctstoptime)    WHERE acctstoptime IS NULL;
CREATE INDEX idx_radacct_framedipaddress ON radacct (framedipaddress, acctstarttime DESC);
CREATE INDEX idx_radacct_callingstationid ON radacct (callingstationid, acctstarttime DESC);

COMMENT ON TABLE  radacct IS 'FreeRADIUS accounting records. TimescaleDB hypertable partitioned monthly. Stores per-session bandwidth and duration data.';
COMMENT ON COLUMN radacct.acctinputoctets IS 'Bytes received by the NAS from the subscriber (subscriber upload).';
COMMENT ON COLUMN radacct.acctoutputoctets IS 'Bytes sent by the NAS to the subscriber (subscriber download).';

-- =============================================================================
-- TABLE: usage_stats (TimescaleDB Hypertable)
-- High-frequency per-subscriber bandwidth metrics for dashboards and alerting.
-- =============================================================================
CREATE TABLE usage_stats (
    time            TIMESTAMPTZ     NOT NULL,
    subscriber_id   UUID            REFERENCES subscribers (id) ON DELETE CASCADE,
    franchisee_id   UUID            REFERENCES franchisees (id) ON DELETE CASCADE,
    bytes_in        BIGINT          NOT NULL DEFAULT 0,
    bytes_out       BIGINT          NOT NULL DEFAULT 0,
    session_id      VARCHAR(64)
);

-- TimescaleDB hypertable: partition by time, daily chunks for fine-grained metrics
SELECT create_hypertable(
    'usage_stats',
    'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- Compression: compress chunks older than 7 days
SELECT add_compression_policy('usage_stats', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention: drop raw stats older than 90 days (aggregates survive in continuous agg)
SELECT add_retention_policy('usage_stats', INTERVAL '90 days', if_not_exists => TRUE);

CREATE INDEX idx_usage_stats_subscriber ON usage_stats (subscriber_id, time DESC);
CREATE INDEX idx_usage_stats_franchisee ON usage_stats (franchisee_id, time DESC);
CREATE INDEX idx_usage_stats_session    ON usage_stats (session_id, time DESC);

COMMENT ON TABLE usage_stats IS 'High-frequency per-session bandwidth samples. Populated by radius-consumer service from Kafka accounting stream.';

-- ---------------------------------------------------------------------------
-- Continuous Aggregate: hourly rollup of usage_stats
-- Materialised view that TimescaleDB refreshes automatically.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW usage_stats_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time)     AS bucket,
    subscriber_id,
    franchisee_id,
    SUM(bytes_in)                   AS total_bytes_in,
    SUM(bytes_out)                  AS total_bytes_out,
    COUNT(DISTINCT session_id)      AS session_count
FROM usage_stats
GROUP BY bucket, subscriber_id, franchisee_id
WITH NO DATA;

-- Continuous aggregate refresh policy: materialise data with 1h lag, refresh every 30 min
SELECT add_continuous_aggregate_policy(
    'usage_stats_hourly',
    start_offset    => INTERVAL '3 hours',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists   => TRUE
);

-- ---------------------------------------------------------------------------
-- Continuous Aggregate: daily rollup of usage_stats
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW usage_stats_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time)      AS bucket,
    subscriber_id,
    franchisee_id,
    SUM(bytes_in)                   AS total_bytes_in,
    SUM(bytes_out)                  AS total_bytes_out,
    COUNT(DISTINCT session_id)      AS session_count
FROM usage_stats
GROUP BY bucket, subscriber_id, franchisee_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'usage_stats_daily',
    start_offset    => INTERVAL '2 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE
);

-- =============================================================================
-- TABLE: payment_transactions
-- Records of all payment attempts across all gateways.
-- =============================================================================
CREATE TABLE payment_transactions (
    id                      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    subscriber_id           UUID            REFERENCES subscribers (id) ON DELETE SET NULL,
    franchisee_id           UUID            REFERENCES franchisees (id) ON DELETE RESTRICT,
    plan_id                 UUID            REFERENCES plans (id) ON DELETE SET NULL,
    amount                  DECIMAL(10,2)   NOT NULL CHECK (amount > 0),
    currency                VARCHAR(3)      NOT NULL DEFAULT 'BDT',
    gateway                 VARCHAR(20)     NOT NULL
                                CHECK (gateway IN ('bkash', 'nagad', 'sslcommerz', 'cash', 'credit')),
    gateway_transaction_id  VARCHAR(255),
    gateway_response        JSONB,
    status                  VARCHAR(20)     NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'success', 'failed', 'refunded')),
    payment_for             VARCHAR(20)     NOT NULL DEFAULT 'plan_renewal'
                                CHECK (payment_for IN ('plan_renewal', 'balance_topup', 'activation', 'late_fee')),
    period_start            TIMESTAMPTZ,
    period_end              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payment_txns_subscriber_id     ON payment_transactions (subscriber_id, created_at DESC);
CREATE INDEX idx_payment_txns_franchisee_id     ON payment_transactions (franchisee_id, created_at DESC);
CREATE INDEX idx_payment_txns_status            ON payment_transactions (status, gateway);
CREATE INDEX idx_payment_txns_gateway_txn_id    ON payment_transactions (gateway_transaction_id) WHERE gateway_transaction_id IS NOT NULL;
CREATE INDEX idx_payment_txns_created_at        ON payment_transactions (created_at DESC);

CREATE TRIGGER trg_payment_transactions_updated_at
    BEFORE UPDATE ON payment_transactions
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMENT ON TABLE  payment_transactions IS 'Immutable-style ledger of payment attempts and results across all gateways. Never physically delete rows.';
COMMENT ON COLUMN payment_transactions.gateway_response IS 'Raw JSON response from payment gateway; stored for reconciliation and dispute resolution.';

-- =============================================================================
-- TABLE: notifications
-- Outbound notification log (SMS, push, email).
-- =============================================================================
CREATE TABLE notifications (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subscriber_id   UUID        REFERENCES subscribers (id) ON DELETE CASCADE,
    franchisee_id   UUID        REFERENCES franchisees (id) ON DELETE CASCADE,
    type            VARCHAR(50),
    message         TEXT,
    message_bn      TEXT,
    channel         VARCHAR(20) NOT NULL DEFAULT 'sms'
                        CHECK (channel IN ('sms', 'push', 'email')),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    attempts        INTEGER     NOT NULL DEFAULT 0,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notifications_subscriber_id    ON notifications (subscriber_id, created_at DESC);
CREATE INDEX idx_notifications_franchisee_id    ON notifications (franchisee_id, created_at DESC);
CREATE INDEX idx_notifications_status           ON notifications (status, channel) WHERE status = 'pending';
CREATE INDEX idx_notifications_created_at       ON notifications (created_at DESC);

COMMENT ON TABLE  notifications IS 'Outbound notification delivery log. Populated by notification service; supports retry tracking via attempts counter.';
COMMENT ON COLUMN notifications.type IS 'Logical event type: expiry_warning, quota_warning, payment_success, payment_failed, account_suspended, etc.';
COMMENT ON COLUMN notifications.message_bn IS 'Bengali localised version of the notification message for subscriber-facing channels.';

-- =============================================================================
-- TABLE: coa_commands
-- Change of Authorization commands dispatched to NAS devices via RADIUS CoA/DM.
-- =============================================================================
CREATE TABLE coa_commands (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    nas_id          UUID        REFERENCES nas_devices (id) ON DELETE SET NULL,
    subscriber_id   UUID        REFERENCES subscribers (id) ON DELETE CASCADE,
    command_type    VARCHAR(20) NOT NULL
                        CHECK (command_type IN ('disconnect', 'rate-limit', 'coa')),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sent', 'success', 'failed')),
    attributes      JSONB,
    response        JSONB,
    attempts        INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at     TIMESTAMPTZ
);

CREATE INDEX idx_coa_commands_subscriber_id ON coa_commands (subscriber_id, created_at DESC);
CREATE INDEX idx_coa_commands_nas_id        ON coa_commands (nas_id);
CREATE INDEX idx_coa_commands_status        ON coa_commands (status) WHERE status = 'pending';
CREATE INDEX idx_coa_commands_created_at    ON coa_commands (created_at DESC);

COMMENT ON TABLE  coa_commands IS 'Queue and audit log for RADIUS CoA (Change of Authorization) and Disconnect-Message commands sent to NAS devices.';
COMMENT ON COLUMN coa_commands.attributes IS 'RADIUS AVPs to be sent in the CoA request, e.g. {"Mikrotik-Rate-Limit": "10M/10M"}.';
COMMENT ON COLUMN coa_commands.response IS 'Raw response from NAS device after CoA delivery attempt.';

-- =============================================================================
-- TABLE: support_tickets
-- Customer support ticket tracking per franchisee.
-- =============================================================================
CREATE TABLE support_tickets (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    franchisee_id   UUID        REFERENCES franchisees (id) ON DELETE CASCADE,
    subscriber_id   UUID        REFERENCES subscribers (id) ON DELETE SET NULL,
    subject         VARCHAR(500) NOT NULL,
    description     TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    priority        VARCHAR(20) NOT NULL DEFAULT 'medium'
                        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX idx_support_tickets_franchisee_id  ON support_tickets (franchisee_id, created_at DESC);
CREATE INDEX idx_support_tickets_subscriber_id  ON support_tickets (subscriber_id);
CREATE INDEX idx_support_tickets_status         ON support_tickets (franchisee_id, status, priority);

CREATE TRIGGER trg_support_tickets_updated_at
    BEFORE UPDATE ON support_tickets
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMENT ON TABLE support_tickets IS 'Customer support and fault management tickets. Scoped per franchisee with subscriber linkage.';

-- =============================================================================
-- TABLE: ott_entitlements
-- OTT (streaming) platform provisioning records for subscribers.
-- =============================================================================
CREATE TABLE ott_entitlements (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subscriber_id       UUID        NOT NULL REFERENCES subscribers (id) ON DELETE CASCADE,
    partner             VARCHAR(50) NOT NULL
                            CHECK (partner IN ('chorki', 'hoichoi', 'binge', 'toffee', 'bioscope')),
    external_account_id VARCHAR(255),
    status              VARCHAR(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'revoked', 'pending')),
    provisioned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at          TIMESTAMPTZ
);

CREATE INDEX idx_ott_entitlements_subscriber_id ON ott_entitlements (subscriber_id);
CREATE INDEX idx_ott_entitlements_partner        ON ott_entitlements (partner, status);
CREATE UNIQUE INDEX idx_ott_entitlements_unique  ON ott_entitlements (subscriber_id, partner)
    WHERE status IN ('active', 'pending');

COMMENT ON TABLE  ott_entitlements IS 'OTT streaming platform entitlement records. Created/revoked by ott-provisioner service when plan changes occur.';
COMMENT ON COLUMN ott_entitlements.external_account_id IS 'Account or subscription ID assigned by the OTT partner API for this subscriber.';

-- =============================================================================
-- TABLE: audit_logs
-- Immutable audit trail for all significant platform actions.
-- Partitioned monthly as a native PostgreSQL range-partitioned table.
-- =============================================================================
CREATE TABLE audit_logs (
    id              UUID        NOT NULL DEFAULT gen_random_uuid(),
    actor_type      VARCHAR(20)
                        CHECK (actor_type IN ('franchisee_user', 'subscriber', 'system', 'platform_admin')),
    actor_id        UUID,
    action          VARCHAR(255) NOT NULL,
    resource_type   VARCHAR(100),
    resource_id     UUID,
    details         JSONB,
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Create monthly partitions for the next 2 years (2024-01 through 2025-12)
-- In production, use pg_partman or a cron job to create future partitions automatically.
CREATE TABLE audit_logs_2024_01 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE audit_logs_2024_02 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
CREATE TABLE audit_logs_2024_03 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
CREATE TABLE audit_logs_2024_04 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE audit_logs_2024_05 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE audit_logs_2024_06 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
CREATE TABLE audit_logs_2024_07 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-07-01') TO ('2024-08-01');
CREATE TABLE audit_logs_2024_08 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-08-01') TO ('2024-09-01');
CREATE TABLE audit_logs_2024_09 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-09-01') TO ('2024-10-01');
CREATE TABLE audit_logs_2024_10 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-10-01') TO ('2024-11-01');
CREATE TABLE audit_logs_2024_11 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');
CREATE TABLE audit_logs_2024_12 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');
CREATE TABLE audit_logs_2025_01 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE audit_logs_2025_02 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE audit_logs_2025_03 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
CREATE TABLE audit_logs_2025_04 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
CREATE TABLE audit_logs_2025_05 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
CREATE TABLE audit_logs_2025_06 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
CREATE TABLE audit_logs_2025_07 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE audit_logs_2025_08 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE audit_logs_2025_09 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE audit_logs_2025_10 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE audit_logs_2025_11 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE audit_logs_2025_12 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
CREATE TABLE audit_logs_2026_01 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE audit_logs_2026_02 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE audit_logs_2026_03 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT;

CREATE INDEX idx_audit_logs_actor        ON audit_logs (actor_id, created_at DESC);
CREATE INDEX idx_audit_logs_resource     ON audit_logs (resource_type, resource_id, created_at DESC);
CREATE INDEX idx_audit_logs_action       ON audit_logs (action, created_at DESC);
CREATE INDEX idx_audit_logs_created_at   ON audit_logs (created_at DESC);

COMMENT ON TABLE  audit_logs IS 'Append-only audit trail. Partitioned monthly for efficient purging and query performance. Never UPDATE or DELETE rows.';
COMMENT ON COLUMN audit_logs.actor_type IS 'Type of entity performing the action.';
COMMENT ON COLUMN audit_logs.details IS 'Contextual JSON payload: before/after state diffs, request metadata, etc.';

-- =============================================================================
-- ROW-LEVEL SECURITY (RLS)
-- Franchise isolation: users can only see/modify rows belonging to their franchisee.
-- The application must SET app.current_franchisee_id = '<uuid>' on each connection.
-- =============================================================================

-- Enable RLS on multi-tenant tables
ALTER TABLE subscribers      ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans            ENABLE ROW LEVEL SECURITY;
ALTER TABLE nas_devices      ENABLE ROW LEVEL SECURITY;
ALTER TABLE support_tickets  ENABLE ROW LEVEL SECURITY;
ALTER TABLE ott_entitlements ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- subscribers RLS
-- ---------------------------------------------------------------------------
CREATE POLICY franchisee_isolation_select ON subscribers
    FOR SELECT
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_insert ON subscribers
    FOR INSERT
    WITH CHECK (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_update ON subscribers
    FOR UPDATE
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    )
    WITH CHECK (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_delete ON subscribers
    FOR DELETE
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

-- ---------------------------------------------------------------------------
-- plans RLS (also allows global plans with NULL franchisee_id to be visible)
-- ---------------------------------------------------------------------------
CREATE POLICY franchisee_isolation_select ON plans
    FOR SELECT
    USING (
        franchisee_id IS NULL
        OR franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_insert ON plans
    FOR INSERT
    WITH CHECK (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_update ON plans
    FOR UPDATE
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    )
    WITH CHECK (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_delete ON plans
    FOR DELETE
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

-- ---------------------------------------------------------------------------
-- nas_devices RLS
-- ---------------------------------------------------------------------------
CREATE POLICY franchisee_isolation_select ON nas_devices
    FOR SELECT
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_insert ON nas_devices
    FOR INSERT
    WITH CHECK (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_update ON nas_devices
    FOR UPDATE
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    )
    WITH CHECK (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_delete ON nas_devices
    FOR DELETE
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

-- ---------------------------------------------------------------------------
-- support_tickets RLS
-- ---------------------------------------------------------------------------
CREATE POLICY franchisee_isolation_select ON support_tickets
    FOR SELECT
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_insert ON support_tickets
    FOR INSERT
    WITH CHECK (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_update ON support_tickets
    FOR UPDATE
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    )
    WITH CHECK (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

CREATE POLICY franchisee_isolation_delete ON support_tickets
    FOR DELETE
    USING (
        franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        OR current_setting('app.is_platform_admin', TRUE) = 'true'
    );

-- ---------------------------------------------------------------------------
-- ott_entitlements RLS (join through subscribers)
-- ---------------------------------------------------------------------------
CREATE POLICY franchisee_isolation_select ON ott_entitlements
    FOR SELECT
    USING (
        current_setting('app.is_platform_admin', TRUE) = 'true'
        OR EXISTS (
            SELECT 1 FROM subscribers s
            WHERE s.id = ott_entitlements.subscriber_id
              AND s.franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        )
    );

CREATE POLICY franchisee_isolation_insert ON ott_entitlements
    FOR INSERT
    WITH CHECK (
        current_setting('app.is_platform_admin', TRUE) = 'true'
        OR EXISTS (
            SELECT 1 FROM subscribers s
            WHERE s.id = ott_entitlements.subscriber_id
              AND s.franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        )
    );

CREATE POLICY franchisee_isolation_update ON ott_entitlements
    FOR UPDATE
    USING (
        current_setting('app.is_platform_admin', TRUE) = 'true'
        OR EXISTS (
            SELECT 1 FROM subscribers s
            WHERE s.id = ott_entitlements.subscriber_id
              AND s.franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        )
    );

CREATE POLICY franchisee_isolation_delete ON ott_entitlements
    FOR DELETE
    USING (
        current_setting('app.is_platform_admin', TRUE) = 'true'
        OR EXISTS (
            SELECT 1 FROM subscribers s
            WHERE s.id = ott_entitlements.subscriber_id
              AND s.franchisee_id = NULLIF(current_setting('app.current_franchisee_id', TRUE), '')::UUID
        )
    );

-- =============================================================================
-- DATABASE ROLES & GRANTS
-- =============================================================================

-- Application role: used by API and microservices
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'isp_app') THEN
        CREATE ROLE isp_app LOGIN;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE isp_platform TO isp_app;
GRANT USAGE   ON SCHEMA  public       TO isp_app;

-- Table-level grants
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    franchisees, franchisee_users, plans, subscribers, nas_devices,
    radcheck, radreply, radgroupcheck, radgroupreply, radusergroup,
    radacct, usage_stats, payment_transactions, notifications,
    coa_commands, support_tickets, ott_entitlements, audit_logs
TO isp_app;

-- Sequence grants (for SERIAL columns)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO isp_app;

-- Read-only role: used by analytics/reporting tools
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'isp_readonly') THEN
        CREATE ROLE isp_readonly LOGIN;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE isp_platform TO isp_readonly;
GRANT USAGE   ON SCHEMA  public       TO isp_readonly;
GRANT SELECT  ON ALL TABLES IN SCHEMA public TO isp_readonly;
GRANT SELECT  ON usage_stats_hourly   TO isp_readonly;
GRANT SELECT  ON usage_stats_daily    TO isp_readonly;

-- =============================================================================
-- SEED DATA: platform-global default plans
-- =============================================================================
INSERT INTO plans (
    id,
    franchisee_id,
    name,
    name_bn,
    description,
    speed_download_kbps,
    speed_upload_kbps,
    speed_throttle_kbps,
    data_cap_gb,
    validity_days,
    price,
    currency,
    is_active
) VALUES
(
    gen_random_uuid(), NULL,
    'Starter 5Mbps', 'স্টার্টার ৫এমবিপিএস',
    'Entry-level plan for light internet users. Suitable for browsing and social media.',
    5120, 2048, 512, 30, 30, 400.00, 'BDT', TRUE
),
(
    gen_random_uuid(), NULL,
    'Home 10Mbps', 'হোম ১০এমবিপিএস',
    'Standard home broadband plan with comfortable data for HD streaming.',
    10240, 5120, 512, 100, 30, 700.00, 'BDT', TRUE
),
(
    gen_random_uuid(), NULL,
    'Home 20Mbps', 'হোম ২০এমবিপিএস',
    'High-speed home plan for families. Includes Chorki and Hoichoi OTT access.',
    20480, 10240, 1024, 200, 30, 1200.00, 'BDT', TRUE
),
(
    gen_random_uuid(), NULL,
    'Business 50Mbps', 'বিজনেস ৫০এমবিপিএস',
    'Business-grade connection with priority bandwidth and dedicated support.',
    51200, 25600, 2048, NULL, 30, 3000.00, 'BDT', TRUE
),
(
    gen_random_uuid(), NULL,
    'Enterprise 100Mbps', 'এন্টারপ্রাইজ ১০০এমবিপিএস',
    'Unlimited enterprise connectivity with SLA-backed uptime guarantee.',
    102400, 51200, 4096, NULL, 30, 6000.00, 'BDT', TRUE
);

-- =============================================================================
-- SCHEMA VERSION TRACKING
-- =============================================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(50) PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description TEXT
);

INSERT INTO schema_migrations (version, description)
VALUES ('001', 'Initial schema: franchisees, subscribers, RADIUS tables, TimescaleDB hypertables, RLS policies');

COMMIT;
