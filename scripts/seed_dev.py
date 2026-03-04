#!/usr/bin/env python3
"""
whISP Development Seed Script
Populates the database with realistic Bangladeshi test data.

Usage:
    python seed_dev.py                  # Seed data (skip if already exists)
    python seed_dev.py --reset          # TRUNCATE all tables, then seed
    python seed_dev.py --minimal        # Seed minimal data only
"""

import asyncio
import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
from passlib.hash import bcrypt

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://isp_user:isp_password@localhost:5432/isp_platform",
).replace("postgresql+asyncpg://", "postgresql://")

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

FRANCHISEES = [
    {
        "code": "DHK001",
        "name": "ঢাকা নেট সার্ভিসেস",
        "contact_person": "মোঃ আব্দুল করিম",
        "phone": "+8801711234567",
        "email": "dhaka@whisp.net",
        "subdomain": "dhaka",
        "address": "মিরপুর-১০, ঢাকা-১২১৬",
        "status": "active",
        "bandwidth_pool_mbps": 1000,
        "balance_amount": 50000.00,
        "credit_limit": 100000.00,
        "radius_secret": "dhk_radius_secret_2026",
    },
    {
        "code": "CTG001",
        "name": "চট্টগ্রাম ব্রডব্যান্ড",
        "contact_person": "মোঃ জসিম উদ্দিন",
        "phone": "+8801812345678",
        "email": "ctg@whisp.net",
        "subdomain": "ctg",
        "address": "আগ্রাবাদ, চট্টগ্রাম-৪১০০",
        "status": "active",
        "bandwidth_pool_mbps": 500,
        "balance_amount": 25000.00,
        "credit_limit": 50000.00,
        "radius_secret": "ctg_radius_secret_2026",
    },
    {
        "code": "SYL001",
        "name": "সিলেট ইন্টারনেট",
        "contact_person": "মিসেস ফারহানা আক্তার",
        "phone": "+8801912345678",
        "email": "sylhet@whisp.net",
        "subdomain": "sylhet",
        "address": "জিন্দাবাজার, সিলেট-৩১০০",
        "status": "active",
        "bandwidth_pool_mbps": 300,
        "balance_amount": 15000.00,
        "credit_limit": 30000.00,
        "radius_secret": "syl_radius_secret_2026",
    },
]

FRANCHISEE_USERS_TEMPLATE = [
    {"name": "প্রশাসক", "role": "admin", "email_prefix": "admin"},
    {"name": "সহকারী ম্যানেজার", "role": "support", "email_prefix": "support"},
]

PLANS = [
    {
        "name": "বেসিক",
        "speed_download_kbps": 5120,
        "speed_upload_kbps": 2048,
        "speed_throttle_kbps": 512,
        "data_cap_gb": 30,
        "validity_days": 30,
        "price": 350,
        "currency": "BDT",
        "ott_chorki": False,
        "ott_hoichoi": False,
        "ott_binge": False,
        "ott_toffee": False,
    },
    {
        "name": "স্ট্যান্ডার্ড",
        "speed_download_kbps": 10240,
        "speed_upload_kbps": 5120,
        "speed_throttle_kbps": 1024,
        "data_cap_gb": 60,
        "validity_days": 30,
        "price": 500,
        "currency": "BDT",
        "ott_chorki": True,
        "ott_hoichoi": False,
        "ott_binge": False,
        "ott_toffee": False,
    },
    {
        "name": "ফ্যামিলি প্লাস",
        "speed_download_kbps": 20480,
        "speed_upload_kbps": 10240,
        "speed_throttle_kbps": 2048,
        "data_cap_gb": 100,
        "validity_days": 30,
        "price": 600,
        "currency": "BDT",
        "ott_chorki": True,
        "ott_hoichoi": True,
        "ott_binge": False,
        "ott_toffee": False,
    },
    {
        "name": "প্রিমিয়াম",
        "speed_download_kbps": 51200,
        "speed_upload_kbps": 25600,
        "speed_throttle_kbps": 5120,
        "data_cap_gb": 200,
        "validity_days": 30,
        "price": 900,
        "currency": "BDT",
        "ott_chorki": True,
        "ott_hoichoi": True,
        "ott_binge": True,
        "ott_toffee": True,
    },
    {
        "name": "আনলিমিটেড",
        "speed_download_kbps": 102400,
        "speed_upload_kbps": 51200,
        "speed_throttle_kbps": 10240,
        "data_cap_gb": 0,
        "validity_days": 30,
        "price": 1500,
        "currency": "BDT",
        "ott_chorki": True,
        "ott_hoichoi": True,
        "ott_binge": True,
        "ott_toffee": True,
    },
]

BD_FIRST_NAMES = [
    "মোঃ রহিম", "মোঃ করিম", "মোঃ জসিম", "মোঃ বশির", "মোঃ নজরুল",
    "মোঃ আলমগীর", "মোঃ শফিকুল", "মোঃ হাবিবুর", "মোঃ মনিরুল", "মোঃ সাইফুল",
    "রাহেলা বেগম", "সুমাইয়া খানম", "ফারহানা আক্তার", "তাসলিমা বেগম", "নাসরিন সুলতানা",
    "রুবি আক্তার", "শাহিদা বেগম", "মর্জিনা বেগম", "রোকেয়া খানম", "সালমা বেগম",
    "আরিফ হোসেন", "রাফিউল ইসলাম", "তানভীর আহমেদ", "শাকিল মাহমুদ", "নাফিস উদ্দিন",
    "ইমরান হোসেন", "মাহফুজ রহমান", "সাজিদ আলী", "ওয়াসিম আকরাম", "ফারুক হোসেন",
    "দিলরুবা বেগম", "আঞ্জুমান আরা", "কোহিনুর আক্তার", "মাহমুদা খানম", "লতিফা বেগম",
    "সাবিনা ইয়াসমিন", "হাসিনা বেগম", "আমেনা খাতুন", "রওশন আরা", "বেলি বেগম",
    "শামসুল হক", "আব্দুল মান্নান", "লুৎফর রহমান", "মোস্তাফিজুর", "আজিজুর রহমান",
    "মুকুল চন্দ্র", "পার্থ সারথি", "নীলিমা রানী", "সুচিত্রা দাস", "মিনতি বালা",
]

GATEWAYS = ["bkash", "nagad", "sslcommerz"]
STATUSES = ["completed", "completed", "completed", "failed", "pending"]

NOW = datetime.now(timezone.utc)


def random_phone():
    prefixes = ["017", "018", "019", "015", "016"]
    prefix = random.choice(prefixes)
    suffix = "".join([str(random.randint(0, 9)) for _ in range(8)])
    return f"+880{prefix[1:]}{suffix}"


def random_pppoe_username(franchisee_code: str, idx: int) -> str:
    return f"{franchisee_code.lower()}_user{idx:04d}"


async def reset_tables(conn: asyncpg.Connection):
    print("  Truncating all tables...")
    tables = [
        "notifications",
        "payment_transactions",
        "radcheck",
        "radreply",
        "radusergroup",
        "radgroupcheck",
        "radgroupreply",
        "nas_devices",
        "subscribers",
        "plans",
        "franchisee_users",
        "franchisees",
    ]
    for table in tables:
        try:
            await conn.execute(f"TRUNCATE TABLE {table} CASCADE")
        except Exception as e:
            print(f"    Warning: could not truncate {table}: {e}")
    print("  Done truncating.")


async def seed_franchisees(conn: asyncpg.Connection) -> list[dict]:
    print("🏢 Seeding franchisees...")
    result = []
    for f in FRANCHISEES:
        row = await conn.fetchrow(
            """
            INSERT INTO franchisees
                (id, code, name, contact_person, phone, email, subdomain, address,
                 status, bandwidth_pool_mbps, balance_amount, credit_limit,
                 radius_secret, created_at, updated_at)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8,
                 $9, $10, $11, $12,
                 $13, $14, $14)
            ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    updated_at = EXCLUDED.updated_at
            RETURNING id, code, name
            """,
            str(uuid.uuid4()),
            f["code"], f["name"], f["contact_person"], f["phone"], f["email"],
            f["subdomain"], f["address"],
            f["status"], f["bandwidth_pool_mbps"], f["balance_amount"], f["credit_limit"],
            f["radius_secret"], NOW,
        )
        result.append({"id": str(row["id"]), "code": row["code"], "name": row["name"]})
        print(f"  + {row['name']} ({row['code']})")
    return result


async def seed_franchisee_users(conn: asyncpg.Connection, franchisees: list[dict]):
    print("🧑‍💼 Seeding franchisee users...")
    count = 0
    for fr in franchisees:
        for i, tmpl in enumerate(FRANCHISEE_USERS_TEMPLATE):
            email = f"{tmpl['email_prefix']}@{fr['code'].lower()}.whisp.net"
            pw_hash = bcrypt.hash("Password@123")
            await conn.execute(
                """
                INSERT INTO franchisee_users
                    (id, franchisee_id, name, email, phone, password_hash, role,
                     is_active, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8, $8)
                ON CONFLICT (email) DO NOTHING
                """,
                str(uuid.uuid4()),
                uuid.UUID(fr["id"]),
                f"{tmpl['name']} - {fr['name'][:8]}",
                email,
                random_phone(),
                pw_hash,
                tmpl["role"],
                NOW,
            )
            count += 1
    print(f"  + {count} franchisee users created")


async def seed_plans(conn: asyncpg.Connection) -> list[dict]:
    print("📦 Seeding plans...")
    result = []
    for p in PLANS:
        row = await conn.fetchrow(
            """
            INSERT INTO plans
                (id, name, speed_download_kbps, speed_upload_kbps, speed_throttle_kbps,
                 data_cap_gb, validity_days, price, currency,
                 ott_chorki, ott_hoichoi, ott_binge, ott_toffee,
                 is_active, created_at, updated_at)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                 $10, $11, $12, $13,
                 true, $14, $14)
            ON CONFLICT DO NOTHING
            RETURNING id, name, price
            """,
            str(uuid.uuid4()),
            p["name"], p["speed_download_kbps"], p["speed_upload_kbps"], p["speed_throttle_kbps"],
            p["data_cap_gb"], p["validity_days"], p["price"], p["currency"],
            p["ott_chorki"], p["ott_hoichoi"], p["ott_binge"], p["ott_toffee"],
            NOW,
        )
        if row:
            result.append({"id": str(row["id"]), "name": row["name"], "price": row["price"]})
            print(f"  + {row['name']} (৳{row['price']})")
    # If plans already existed, fetch them
    if not result:
        rows = await conn.fetch("SELECT id, name, price FROM plans WHERE is_active = true ORDER BY price")
        result = [{"id": str(r["id"]), "name": r["name"], "price": r["price"]} for r in rows]
    return result


async def seed_subscribers(
    conn: asyncpg.Connection,
    franchisees: list[dict],
    plans: list[dict],
    count: int = 50,
) -> list[dict]:
    print(f"👥 Seeding {count} subscribers...")
    result = []
    names = random.sample(BD_FIRST_NAMES * 2, count)

    for i in range(count):
        franchisee = franchisees[i % len(franchisees)]
        plan = random.choice(plans)
        name = names[i]
        phone = random_phone()
        email = f"user{i+1:03d}@{franchisee['code'].lower()}.example.com"
        pppoe_username = random_pppoe_username(franchisee["code"], i + 1)
        pppoe_password = f"P@ss{random.randint(1000, 9999)}"
        username = pppoe_username
        pw_hash = bcrypt.hash("subscriber@123")
        status = random.choices(["active", "active", "active", "suspended", "expired"], k=1)[0]

        expires_delta = timedelta(days=random.randint(-5, 30))
        plan_expires_at = NOW + expires_delta

        data_cap_bytes = (plan.get("data_cap_gb", 0) or 0) * 1_073_741_824
        if data_cap_bytes > 0:
            usage_pct = random.uniform(0.05, 0.95)
            data_used_bytes = int(data_cap_bytes * usage_pct)
        else:
            data_used_bytes = random.randint(1_073_741_824, 107_374_182_400)

        row = await conn.fetchrow(
            """
            INSERT INTO subscribers
                (id, franchisee_id, plan_id, username, password_hash,
                 pppoe_username, pppoe_password,
                 name, phone, email, address, status,
                 plan_expires_at, data_used_bytes, data_cap_bytes,
                 quota_reset_at, created_at, updated_at)
            VALUES
                ($1, $2, $3, $4, $5,
                 $6, $7,
                 $8, $9, $10, $11, $12,
                 $13, $14, $15,
                 $16, $17, $17)
            ON CONFLICT (username) DO NOTHING
            RETURNING id, pppoe_username
            """,
            str(uuid.uuid4()),
            uuid.UUID(franchisee["id"]),
            uuid.UUID(plan["id"]),
            username,
            pw_hash,
            pppoe_username,
            pppoe_password,
            name,
            phone,
            email,
            f"এলাকা-{i+1}, {franchisee['name'][:10]}",
            status,
            plan_expires_at,
            data_used_bytes,
            data_cap_bytes if data_cap_bytes > 0 else None,
            NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            NOW,
        )
        if row:
            result.append({
                "id": str(row["id"]),
                "pppoe_username": row["pppoe_username"],
                "pppoe_password": pppoe_password,
                "plan_id": plan["id"],
                "franchisee_id": franchisee["id"],
            })

    print(f"  + {len(result)} subscribers created")
    return result


async def seed_radcheck_radreply(conn: asyncpg.Connection, subscribers: list[dict]):
    print("📡 Seeding radcheck/radreply entries...")
    count = 0
    for sub in subscribers:
        await conn.execute(
            """
            INSERT INTO radcheck (username, attribute, op, value)
            VALUES ($1, 'Cleartext-Password', ':=', $2)
            ON CONFLICT DO NOTHING
            """,
            sub["pppoe_username"],
            sub["pppoe_password"],
        )
        # Fetch plan speed for rate limit
        plan_row = await conn.fetchrow(
            "SELECT speed_download_kbps, speed_upload_kbps, speed_throttle_kbps FROM plans WHERE id = $1",
            uuid.UUID(sub["plan_id"]),
        )
        if plan_row:
            dl = plan_row["speed_download_kbps"]
            ul = plan_row["speed_upload_kbps"]
            th = plan_row["speed_throttle_kbps"]
            rate_limit = f"{ul}k/{dl}k {th}k/{th}k"
            await conn.execute(
                """
                INSERT INTO radreply (username, attribute, op, value)
                VALUES ($1, 'Mikrotik-Rate-Limit', '=', $2)
                ON CONFLICT DO NOTHING
                """,
                sub["pppoe_username"],
                rate_limit,
            )
        count += 1
    print(f"  + {count} radcheck + radreply entries")


async def seed_nas_devices(conn: asyncpg.Connection, franchisees: list[dict]):
    print("🖥️  Seeding NAS devices...")
    nas_list = [
        {
            "nasname": "10.10.1.1",
            "shortname": "dhk-mikrotik-01",
            "type": "mikrotik",
            "ports": 1812,
            "secret": "dhk_radius_secret_2026",
            "server": "",
            "community": "public",
            "description": "ঢাকা - মিরপুর MikroTik CCR2004",
        },
        {
            "nasname": "10.20.1.1",
            "shortname": "ctg-mikrotik-01",
            "type": "mikrotik",
            "ports": 1812,
            "secret": "ctg_radius_secret_2026",
            "server": "",
            "community": "public",
            "description": "চট্টগ্রাম - আগ্রাবাদ MikroTik RB4011",
        },
        {
            "nasname": "10.30.1.1",
            "shortname": "syl-mikrotik-01",
            "type": "mikrotik",
            "ports": 1812,
            "secret": "syl_radius_secret_2026",
            "server": "",
            "community": "public",
            "description": "সিলেট - জিন্দাবাজার MikroTik hEX",
        },
    ]
    for i, nas in enumerate(nas_list):
        franchisee = franchisees[i % len(franchisees)]
        await conn.execute(
            """
            INSERT INTO nas_devices
                (id, nasname, shortname, type, ports, secret, server,
                 community, description, franchisee_id, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11)
            ON CONFLICT (nasname) DO NOTHING
            """,
            str(uuid.uuid4()),
            nas["nasname"], nas["shortname"], nas["type"], nas["ports"],
            nas["secret"], nas["server"], nas["community"], nas["description"],
            uuid.UUID(franchisee["id"]),
            NOW,
        )
        print(f"  + {nas['shortname']} ({nas['nasname']})")


async def seed_payment_transactions(
    conn: asyncpg.Connection,
    subscribers: list[dict],
    plans: list[dict],
    count: int = 100,
):
    print(f"💳 Seeding {count} payment transactions...")
    created = 0
    for i in range(count):
        sub = random.choice(subscribers)
        plan = random.choice(plans)
        gateway = random.choice(GATEWAYS)
        status = random.choice(STATUSES)
        days_ago = random.randint(0, 180)
        tx_time = NOW - timedelta(days=days_ago, hours=random.randint(0, 23))
        tx_ref = f"TX{tx_time.strftime('%Y%m%d')}{random.randint(100000, 999999)}"

        await conn.execute(
            """
            INSERT INTO payment_transactions
                (id, subscriber_id, plan_id, amount, currency, gateway,
                 gateway_transaction_id, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'BDT', $5, $6, $7, $8, $8)
            ON CONFLICT DO NOTHING
            """,
            str(uuid.uuid4()),
            uuid.UUID(sub["id"]),
            uuid.UUID(plan["id"]),
            plan["price"],
            gateway,
            tx_ref,
            status,
            tx_time,
        )
        created += 1
    print(f"  + {created} payment transactions")


async def seed_notifications(conn: asyncpg.Connection, subscribers: list[dict], count: int = 20):
    print(f"🔔 Seeding {count} notifications...")
    messages = [
        ("পেমেন্ট সফল", "আপনার পেমেন্ট সফলভাবে গ্রহণ করা হয়েছে।"),
        ("প্যাকেজ নবায়ন", "আপনার ইন্টারনেট প্যাকেজ সফলভাবে নবায়ন হয়েছে।"),
        ("ডেটা সীমা সতর্কতা", "আপনার ডেটার ৮০% ব্যবহার হয়ে গেছে।"),
        ("মেয়াদ শেষের সতর্কতা", "আপনার প্যাকেজের মেয়াদ ৩ দিনে শেষ হবে।"),
        ("সংযোগ পুনরুদ্ধার", "আপনার ইন্টারনেট সংযোগ পুনরুদ্ধার হয়েছে।"),
        ("সিস্টেম রক্ষণাবেক্ষণ", "আগামীকাল রাত ২টায় সংক্ষিপ্ত রক্ষণাবেক্ষণ হবে।"),
        ("অ্যাকাউন্ট স্থগিত", "আপনার অ্যাকাউন্ট স্থগিত করা হয়েছে। পেমেন্ট করুন।"),
    ]
    for i in range(count):
        sub = random.choice(subscribers)
        title, body = random.choice(messages)
        days_ago = random.randint(0, 30)
        notif_time = NOW - timedelta(days=days_ago, hours=random.randint(0, 23))
        await conn.execute(
            """
            INSERT INTO notifications
                (id, subscriber_id, title, body, channel, is_read, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT DO NOTHING
            """,
            str(uuid.uuid4()),
            uuid.UUID(sub["id"]),
            title,
            body,
            random.choice(["sms", "push", "in_app"]),
            random.choice([True, False]),
            notif_time,
        )
    print(f"  + {count} notifications")


def print_summary(franchisees: list[dict]):
    print()
    print("=" * 60)
    print("  whISP Seed Complete - Login Credentials")
    print("=" * 60)
    print()
    print("  FRANCHISEE CMS USERS (all passwords: Password@123)")
    print()
    for fr in franchisees:
        code = fr["code"].lower()
        print(f"  {fr['name']}")
        print(f"    Admin:   admin@{code}.whisp.net")
        print(f"    Support: support@{code}.whisp.net")
        print()
    print("  SUBSCRIBER PORTAL")
    print("  Usernames: dhk001_user0001 .. ctg001_user0002 .. etc.")
    print("  Password:  subscriber@123")
    print()
    print("  API Docs:       http://localhost:8000/docs")
    print("  Franchisee CMS: http://localhost:3000")
    print("  User Portal:    http://localhost:3001")
    print("=" * 60)


async def main(args):
    print()
    print("whISP Development Seed Script")
    print(f"Connecting to: {DATABASE_URL.split('@')[-1]}")
    print()

    try:
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}", file=sys.stderr)
        print("Make sure PostgreSQL is running and DATABASE_URL is correct.", file=sys.stderr)
        sys.exit(1)

    try:
        if args.reset:
            print("⚠️  --reset flag set. Truncating all tables...")
            await reset_tables(conn)
            print()

        franchisees = await seed_franchisees(conn)
        await seed_franchisee_users(conn, franchisees)
        plans = await seed_plans(conn)

        sub_count = 10 if args.minimal else 50
        subscribers = await seed_subscribers(conn, franchisees, plans, count=sub_count)

        await seed_radcheck_radreply(conn, subscribers)
        await seed_nas_devices(conn, franchisees)

        if not args.minimal:
            await seed_payment_transactions(conn, subscribers, plans, count=100)
            await seed_notifications(conn, subscribers, count=20)

        print_summary(franchisees)

    except Exception as e:
        print(f"\nERROR during seeding: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the whISP development database")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="TRUNCATE all tables before seeding (destructive!)",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Seed minimal data (10 subscribers, no payments/notifications)",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
