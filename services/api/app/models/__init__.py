"""
SQLAlchemy ORM models for whISP.

All models share a common Base with:
  - id          UUID primary key (server-side gen)
  - created_at  timestamp with timezone
  - updated_at  timestamp with timezone (auto-updated via onupdate)
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Mixin helpers
# ---------------------------------------------------------------------------
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


# ---------------------------------------------------------------------------
# Franchisee
# ---------------------------------------------------------------------------
class Franchisee(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "franchisees"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    code: Mapped[Optional[str]] = mapped_column(String(20))
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20))
    address: Mapped[Optional[str]] = mapped_column(Text)
    district: Mapped[Optional[str]] = mapped_column(String(100))
    division: Mapped[Optional[str]] = mapped_column(String(100))

    # RADIUS / network
    radius_secret: Mapped[Optional[str]] = mapped_column(String(128))
    bandwidth_pool_mbps: Mapped[int] = mapped_column(Integer, default=100)
    ip_pool_name: Mapped[Optional[str]] = mapped_column(String(100))

    # Billing
    balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    commission_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    # Status
    status: Mapped[str] = mapped_column(
        Enum("pending", "active", "suspended", "terminated", name="franchisee_status"),
        default="pending",
        nullable=False,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))

    # Metadata / settings stored as JSONB
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Relationships
    users: Mapped[list["FranchiseeUser"]] = relationship(
        "FranchiseeUser", back_populates="franchisee", lazy="select"
    )
    subscribers: Mapped[list["Subscriber"]] = relationship(
        "Subscriber", back_populates="franchisee", lazy="select"
    )
    nas_devices: Mapped[list["NASDevice"]] = relationship(
        "NASDevice", back_populates="franchisee", lazy="select"
    )


# ---------------------------------------------------------------------------
# FranchiseeUser  (CMS login for franchisee staff)
# ---------------------------------------------------------------------------
class FranchiseeUser(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "franchisee_users"
    __table_args__ = (UniqueConstraint("email", name="uq_franchisee_users_email"),)

    franchisee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("franchisees.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("owner", "manager", "support", name="franchisee_user_role"),
        default="support",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    franchisee: Mapped["Franchisee"] = relationship(
        "Franchisee", back_populates="users"
    )


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
class Plan(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Speeds (kbps)
    download_kbps: Mapped[int] = mapped_column(Integer, nullable=False)
    upload_kbps: Mapped[int] = mapped_column(Integer, nullable=False)

    # Quota
    quota_gb: Mapped[Optional[int]] = mapped_column(Integer)  # NULL = unlimited
    validity_days: Mapped[int] = mapped_column(Integer, default=30)

    # Pricing (BDT)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BDT")

    # FreeRADIUS group name (used in radgroupreply / radusergroup)
    radius_group: Mapped[str] = mapped_column(String(100), nullable=False)

    # Framed IP pool name
    ip_pool: Mapped[Optional[str]] = mapped_column(String(100))

    # OTT entitlements included
    ott_entitlements: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)

    # Scoped to franchisee (NULL = platform-wide)
    franchisee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("franchisees.id", ondelete="SET NULL")
    )

    subscribers: Mapped[list["Subscriber"]] = relationship(
        "Subscriber", back_populates="plan", lazy="select"
    )


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------
class Subscriber(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "subscribers"
    __table_args__ = (
        UniqueConstraint("username", name="uq_subscribers_username"),
        UniqueConstraint("email", name="uq_subscribers_email"),
    )

    franchisee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("franchisees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL")
    )

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    nid: Mapped[Optional[str]] = mapped_column(String(50))  # National ID (encrypted)
    address: Mapped[Optional[str]] = mapped_column(Text)

    # PPPoE credentials
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Cleartext PPPoE password is stored encrypted for RADIUS sync
    pppoe_password_enc: Mapped[Optional[str]] = mapped_column(String(512))

    # Subscription state
    status: Mapped[str] = mapped_column(
        Enum(
            "active",
            "suspended",
            "expired",
            "pending",
            "terminated",
            name="subscriber_status",
        ),
        default="pending",
        nullable=False,
    )
    plan_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    quota_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    # Portal login
    portal_password_hash: Mapped[Optional[str]] = mapped_column(String(255))

    # Auto-debit
    bkash_agreement_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Metadata
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    franchisee: Mapped["Franchisee"] = relationship(
        "Franchisee", back_populates="subscribers"
    )
    plan: Mapped[Optional["Plan"]] = relationship("Plan", back_populates="subscribers")
    payments: Mapped[list["PaymentTransaction"]] = relationship(
        "PaymentTransaction", back_populates="subscriber", lazy="select"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="subscriber", lazy="select"
    )
    ott_entitlements: Mapped[list["OTTEntitlement"]] = relationship(
        "OTTEntitlement", back_populates="subscriber", lazy="select"
    )
    tickets: Mapped[list["SupportTicket"]] = relationship(
        "SupportTicket", back_populates="subscriber", lazy="select"
    )


# ---------------------------------------------------------------------------
# NASDevice
# ---------------------------------------------------------------------------
class NASDevice(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "nas_devices"

    franchisee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("franchisees.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    nas_type: Mapped[str] = mapped_column(String(50), default="mikrotik")
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    coa_port: Mapped[int] = mapped_column(Integer, default=3799)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Last seen / health
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_coa_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    franchisee: Mapped["Franchisee"] = relationship(
        "Franchisee", back_populates="nas_devices"
    )
    coa_commands: Mapped[list["CoACommand"]] = relationship(
        "CoACommand", back_populates="nas_device", lazy="select"
    )


# ---------------------------------------------------------------------------
# PaymentTransaction
# ---------------------------------------------------------------------------
class PaymentTransaction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "payment_transactions"

    subscriber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscribers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL")
    )

    # External payment identifiers
    gateway: Mapped[str] = mapped_column(
        Enum("bkash", "nagad", "sslcommerz", "manual", name="payment_gateway"),
        nullable=False,
    )
    gateway_payment_id: Mapped[Optional[str]] = mapped_column(String(255))
    gateway_transaction_id: Mapped[Optional[str]] = mapped_column(String(255))
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BDT")

    status: Mapped[str] = mapped_column(
        Enum(
            "initiated",
            "pending",
            "completed",
            "failed",
            "cancelled",
            "refunded",
            name="payment_status",
        ),
        default="initiated",
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Raw gateway response stored for audit
    gateway_response: Mapped[Optional[dict]] = mapped_column(JSONB)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    subscriber: Mapped["Subscriber"] = relationship(
        "Subscriber", back_populates="payments"
    )


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------
class Notification(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    subscriber_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscribers.id", ondelete="CASCADE")
    )
    franchisee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("franchisees.id", ondelete="CASCADE")
    )

    channel: Mapped[str] = mapped_column(
        Enum("sms", "email", "push", "in_app", name="notification_channel"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        Enum("pending", "sent", "failed", name="notification_status"),
        default="pending",
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)

    # For in_app – read tracking
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    subscriber: Mapped[Optional["Subscriber"]] = relationship(
        "Subscriber", back_populates="notifications"
    )


# ---------------------------------------------------------------------------
# CoACommand  (audit / log of CoA packets sent)
# ---------------------------------------------------------------------------
class CoACommand(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "coa_commands"

    nas_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nas_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscriber_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscribers.id", ondelete="SET NULL")
    )

    command_type: Mapped[str] = mapped_column(
        Enum("disconnect", "coa", "rate_limit", name="coa_command_type"),
        nullable=False,
    )
    attributes: Mapped[Optional[dict]] = mapped_column(JSONB)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    response: Mapped[Optional[dict]] = mapped_column(JSONB)
    error: Mapped[Optional[str]] = mapped_column(Text)

    nas_device: Mapped["NASDevice"] = relationship(
        "NASDevice", back_populates="coa_commands"
    )


# ---------------------------------------------------------------------------
# SupportTicket
# ---------------------------------------------------------------------------
class SupportTicket(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "support_tickets"

    subscriber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscribers.id", ondelete="CASCADE"),
        nullable=False,
    )
    franchisee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("franchisees.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("franchisee_users.id", ondelete="SET NULL")
    )

    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[str] = mapped_column(
        Enum(
            "billing",
            "connectivity",
            "speed",
            "installation",
            "other",
            name="ticket_category",
        ),
        default="other",
    )
    priority: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", "critical", name="ticket_priority"),
        default="medium",
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "open",
            "in_progress",
            "pending_customer",
            "resolved",
            "closed",
            name="ticket_status",
        ),
        default="open",
    )

    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)

    # Conversation thread stored as JSONB list of messages
    messages: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    subscriber: Mapped["Subscriber"] = relationship(
        "Subscriber", back_populates="tickets"
    )


# ---------------------------------------------------------------------------
# OTTEntitlement
# ---------------------------------------------------------------------------
class OTTEntitlement(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ott_entitlements"

    subscriber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscribers.id", ondelete="CASCADE"),
        nullable=False,
    )
    partner: Mapped[str] = mapped_column(
        Enum("chorki", "hoichoi", name="ott_partner"), nullable=False
    )

    # Partner-side identifiers
    partner_user_id: Mapped[Optional[str]] = mapped_column(String(255))
    partner_subscription_id: Mapped[Optional[str]] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(
        Enum("active", "revoked", "expired", name="ott_status"), default="active"
    )
    provisioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Raw partner API response
    partner_response: Mapped[Optional[dict]] = mapped_column(JSONB)

    subscriber: Mapped["Subscriber"] = relationship(
        "Subscriber", back_populates="ott_entitlements"
    )


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------
class AuditLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    # Actor
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(
        Enum("admin", "franchisee", "subscriber", "system", name="actor_type"),
        nullable=False,
    )
    actor_email: Mapped[Optional[str]] = mapped_column(String(255))

    # Action
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(100))
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))

    # Context
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    request_id: Mapped[Optional[str]] = mapped_column(String(36))

    # Before/after snapshot
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB)
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Success / failure
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
__all__ = [
    "Base",
    "Franchisee",
    "FranchiseeUser",
    "Plan",
    "Subscriber",
    "NASDevice",
    "PaymentTransaction",
    "Notification",
    "CoACommand",
    "SupportTicket",
    "OTTEntitlement",
    "AuditLog",
]
