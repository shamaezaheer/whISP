"""Initial tables

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB, UUID
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # ------------------------------------------------------------------
    # Enum types  (DO block swallows duplicate_object if already created
    #              by docker-entrypoint-initdb.d init scripts)
    # ------------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE franchisee_status AS ENUM ('pending','active','suspended','terminated');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE franchisee_user_role AS ENUM ('owner','manager','support');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE subscriber_status AS ENUM ('active','suspended','expired','pending','terminated');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE payment_gateway AS ENUM ('bkash','nagad','sslcommerz','manual');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE payment_status AS ENUM ('initiated','pending','completed','failed','cancelled','refunded');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE notification_channel AS ENUM ('sms','email','push','in_app');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE notification_status AS ENUM ('pending','sent','failed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE coa_command_type AS ENUM ('disconnect','coa','rate_limit');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE ticket_category AS ENUM ('billing','connectivity','speed','installation','other');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE ticket_priority AS ENUM ('low','medium','high','critical');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE ticket_status AS ENUM ('open','in_progress','pending_customer','resolved','closed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE ott_partner AS ENUM ('chorki','hoichoi');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE ott_status AS ENUM ('active','revoked','expired');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE actor_type AS ENUM ('admin','franchisee','subscriber','system');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ------------------------------------------------------------------
    # updated_at trigger function
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trigger_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ------------------------------------------------------------------
    # franchisees
    # ------------------------------------------------------------------
    op.create_table(
        "franchisees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("contact_phone", sa.String(20)),
        sa.Column("address", sa.Text),
        sa.Column("district", sa.String(100)),
        sa.Column("division", sa.String(100)),
        sa.Column("radius_secret", sa.String(128)),
        sa.Column("bandwidth_pool_mbps", sa.Integer, nullable=False, server_default="100"),
        sa.Column("ip_pool_name", sa.String(100)),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("commission_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("status", PG_ENUM(name="franchisee_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", UUID(as_uuid=True)),
        sa.Column("settings", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE TRIGGER trg_franchisees_updated_at BEFORE UPDATE ON franchisees FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()"
    )

    # ------------------------------------------------------------------
    # franchisee_users
    # ------------------------------------------------------------------
    op.create_table(
        "franchisee_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("franchisee_id", UUID(as_uuid=True), sa.ForeignKey("franchisees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("phone", sa.String(20)),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", PG_ENUM(name="franchisee_user_role", create_type=False), nullable=False, server_default="support"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE TRIGGER trg_franchisee_users_updated_at BEFORE UPDATE ON franchisee_users FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()"
    )

    # ------------------------------------------------------------------
    # plans
    # ------------------------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("download_kbps", sa.Integer, nullable=False),
        sa.Column("upload_kbps", sa.Integer, nullable=False),
        sa.Column("quota_gb", sa.Integer),
        sa.Column("validity_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BDT"),
        sa.Column("radius_group", sa.String(100), nullable=False),
        sa.Column("ip_pool", sa.String(100)),
        sa.Column("ott_entitlements", JSONB),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_public", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("franchisee_id", UUID(as_uuid=True), sa.ForeignKey("franchisees.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE TRIGGER trg_plans_updated_at BEFORE UPDATE ON plans FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()"
    )

    # ------------------------------------------------------------------
    # subscribers
    # ------------------------------------------------------------------
    op.create_table(
        "subscribers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("franchisee_id", UUID(as_uuid=True), sa.ForeignKey("franchisees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("phone", sa.String(20)),
        sa.Column("nid", sa.String(50)),
        sa.Column("address", sa.Text),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("pppoe_password_enc", sa.String(512)),
        sa.Column("status", PG_ENUM(name="subscriber_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True)),
        sa.Column("quota_used_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("portal_password_hash", sa.String(255)),
        sa.Column("bkash_agreement_id", sa.String(100)),
        sa.Column("custom_fields", JSONB),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_subscribers_status", "subscribers", ["status"])
    op.create_index("idx_subscribers_franchisee", "subscribers", ["franchisee_id"])
    op.create_index("idx_subscribers_plan_expires", "subscribers", ["plan_expires_at"])
    op.execute(
        "CREATE TRIGGER trg_subscribers_updated_at BEFORE UPDATE ON subscribers FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()"
    )

    # ------------------------------------------------------------------
    # nas_devices
    # ------------------------------------------------------------------
    op.create_table(
        "nas_devices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("franchisee_id", UUID(as_uuid=True), sa.ForeignKey("franchisees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("nas_type", sa.String(50), nullable=False, server_default="mikrotik"),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("coa_port", sa.Integer, nullable=False, server_default="3799"),
        sa.Column("description", sa.Text),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_coa_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE TRIGGER trg_nas_devices_updated_at BEFORE UPDATE ON nas_devices FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()"
    )

    # ------------------------------------------------------------------
    # payment_transactions
    # ------------------------------------------------------------------
    op.create_table(
        "payment_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subscriber_id", UUID(as_uuid=True), sa.ForeignKey("subscribers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column("gateway", PG_ENUM(name="payment_gateway", create_type=False), nullable=False),
        sa.Column("gateway_payment_id", sa.String(255)),
        sa.Column("gateway_transaction_id", sa.String(255)),
        sa.Column("invoice_number", sa.String(100), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BDT"),
        sa.Column("status", PG_ENUM(name="payment_status", create_type=False), nullable=False, server_default="initiated"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("gateway_response", JSONB),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_payments_subscriber", "payment_transactions", ["subscriber_id"])
    op.create_index("idx_payments_status", "payment_transactions", ["status"])
    op.execute(
        "CREATE TRIGGER trg_payment_transactions_updated_at BEFORE UPDATE ON payment_transactions FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()"
    )

    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subscriber_id", UUID(as_uuid=True), sa.ForeignKey("subscribers.id", ondelete="CASCADE")),
        sa.Column("franchisee_id", UUID(as_uuid=True), sa.ForeignKey("franchisees.id", ondelete="CASCADE")),
        sa.Column("channel", PG_ENUM(name="notification_channel", create_type=False), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", PG_ENUM(name="notification_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_notifications_subscriber", "notifications", ["subscriber_id"])
    op.create_index("idx_notifications_status", "notifications", ["status"])

    # ------------------------------------------------------------------
    # coa_commands
    # ------------------------------------------------------------------
    op.create_table(
        "coa_commands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("nas_device_id", UUID(as_uuid=True), sa.ForeignKey("nas_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscriber_id", UUID(as_uuid=True), sa.ForeignKey("subscribers.id", ondelete="SET NULL")),
        sa.Column("command_type", PG_ENUM(name="coa_command_type", create_type=False), nullable=False),
        sa.Column("attributes", JSONB),
        sa.Column("success", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("response", JSONB),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # ------------------------------------------------------------------
    # support_tickets
    # ------------------------------------------------------------------
    op.create_table(
        "support_tickets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subscriber_id", UUID(as_uuid=True), sa.ForeignKey("subscribers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("franchisee_id", UUID(as_uuid=True), sa.ForeignKey("franchisees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_to", UUID(as_uuid=True), sa.ForeignKey("franchisee_users.id", ondelete="SET NULL")),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", PG_ENUM(name="ticket_category", create_type=False), nullable=False, server_default="other"),
        sa.Column("priority", PG_ENUM(name="ticket_priority", create_type=False), nullable=False, server_default="medium"),
        sa.Column("status", PG_ENUM(name="ticket_status", create_type=False), nullable=False, server_default="open"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_notes", sa.Text),
        sa.Column("messages", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_tickets_franchisee_status", "support_tickets", ["franchisee_id", "status"])
    op.execute(
        "CREATE TRIGGER trg_support_tickets_updated_at BEFORE UPDATE ON support_tickets FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()"
    )

    # ------------------------------------------------------------------
    # ott_entitlements
    # ------------------------------------------------------------------
    op.create_table(
        "ott_entitlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subscriber_id", UUID(as_uuid=True), sa.ForeignKey("subscribers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("partner", PG_ENUM(name="ott_partner", create_type=False), nullable=False),
        sa.Column("partner_user_id", sa.String(255)),
        sa.Column("partner_subscription_id", sa.String(255)),
        sa.Column("status", PG_ENUM(name="ott_status", create_type=False), nullable=False, server_default="active"),
        sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("partner_response", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_ott_entitlements_subscriber", "ott_entitlements", ["subscriber_id"])

    # ------------------------------------------------------------------
    # audit_logs
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_id", UUID(as_uuid=True)),
        sa.Column("actor_type", PG_ENUM(name="actor_type", create_type=False), nullable=False),
        sa.Column("actor_email", sa.String(255)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100)),
        sa.Column("resource_id", UUID(as_uuid=True)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.Text),
        sa.Column("request_id", sa.String(36)),
        sa.Column("old_values", JSONB),
        sa.Column("new_values", JSONB),
        sa.Column("success", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_audit_logs_actor", "audit_logs", ["actor_id", "actor_type"])
    op.create_index("idx_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("idx_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("ott_entitlements")
    op.drop_table("support_tickets")
    op.drop_table("coa_commands")
    op.drop_table("notifications")
    op.drop_table("payment_transactions")
    op.drop_table("nas_devices")
    op.drop_table("subscribers")
    op.drop_table("plans")
    op.drop_table("franchisee_users")
    op.drop_table("franchisees")

    for enum in [
        "actor_type", "ott_status", "ott_partner",
        "ticket_status", "ticket_priority", "ticket_category",
        "coa_command_type", "notification_status", "notification_channel",
        "payment_status", "payment_gateway", "subscriber_status",
        "franchisee_user_role", "franchisee_status",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum}")
