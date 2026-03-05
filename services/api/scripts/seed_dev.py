"""
Development seed script for whISP.

Creates:
  - 3 franchisees (Dhaka, Chittagong, Sylhet)
  - 5 plans (10 Mbps – 200 Mbps)
  - 100 subscribers spread across the franchisees

Run inside the api container:
    docker compose run --rm api python scripts/seed_dev.py
"""
import asyncio
import random
import secrets
import string
import sys
import os

# Ensure /app is on the path when run as `python scripts/seed_dev.py`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from passlib.context import CryptContext
from sqlalchemy import select, text

from app.database import AsyncSessionLocal, async_engine
from app.models import (
    Franchisee,
    FranchiseeUser,
    NASDevice,
    Plan,
    Subscriber,
)

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

FRANCHISEES = [
    {
        "name": "Dhaka Net Solutions",
        "slug": "dhaka-net",
        "code": "DHK",
        "contact_email": "admin@dhakanet.bd",
        "contact_phone": "01711000001",
        "address": "House 12, Road 5, Dhanmondi, Dhaka",
        "district": "Dhaka",
        "division": "Dhaka",
        "radius_secret": "dhaka_secret_01",
        "bandwidth_pool_mbps": 1000,
        "ip_pool_name": "dhaka-pool",
        "balance": 50000,
        "commission_rate": 15,
        "status": "active",
    },
    {
        "name": "Chittagong Fiber Link",
        "slug": "ctg-fiber",
        "code": "CTG",
        "contact_email": "admin@ctgfiber.bd",
        "contact_phone": "01811000002",
        "address": "Agrabad C/A, Chittagong",
        "district": "Chittagong",
        "division": "Chittagong",
        "radius_secret": "ctg_secret_02",
        "bandwidth_pool_mbps": 500,
        "ip_pool_name": "ctg-pool",
        "balance": 30000,
        "commission_rate": 12,
        "status": "active",
    },
    {
        "name": "Sylhet Connect",
        "slug": "sylhet-connect",
        "code": "SYL",
        "contact_email": "admin@sylhetconnect.bd",
        "contact_phone": "01911000003",
        "address": "Zindabazar, Sylhet",
        "district": "Sylhet",
        "division": "Sylhet",
        "radius_secret": "sylhet_secret_03",
        "bandwidth_pool_mbps": 200,
        "ip_pool_name": "sylhet-pool",
        "balance": 20000,
        "commission_rate": 10,
        "status": "active",
    },
]

PLANS = [
    {
        "name": "Starter 10 Mbps",
        "slug": "starter-10",
        "description": "Basic internet for home use",
        "download_kbps": 10240,
        "upload_kbps": 5120,
        "quota_gb": 50,
        "validity_days": 30,
        "price": 500,
        "radius_group": "plan_10mbps",
        "is_active": True,
        "is_public": True,
    },
    {
        "name": "Standard 25 Mbps",
        "slug": "standard-25",
        "description": "Great for streaming and browsing",
        "download_kbps": 25600,
        "upload_kbps": 12800,
        "quota_gb": 100,
        "validity_days": 30,
        "price": 800,
        "radius_group": "plan_25mbps",
        "is_active": True,
        "is_public": True,
    },
    {
        "name": "Premium 50 Mbps",
        "slug": "premium-50",
        "description": "High speed for families",
        "download_kbps": 51200,
        "upload_kbps": 25600,
        "quota_gb": 200,
        "validity_days": 30,
        "price": 1200,
        "radius_group": "plan_50mbps",
        "ott_entitlements": ["chorki"],
        "is_active": True,
        "is_public": True,
    },
    {
        "name": "Business 100 Mbps",
        "slug": "business-100",
        "description": "Dedicated business-grade connectivity",
        "download_kbps": 102400,
        "upload_kbps": 51200,
        "quota_gb": None,  # unlimited
        "validity_days": 30,
        "price": 2500,
        "radius_group": "plan_100mbps",
        "ott_entitlements": ["chorki", "hoichoi"],
        "is_active": True,
        "is_public": True,
    },
    {
        "name": "Enterprise 200 Mbps",
        "slug": "enterprise-200",
        "description": "Ultra-fast unlimited enterprise plan",
        "download_kbps": 204800,
        "upload_kbps": 102400,
        "quota_gb": None,
        "validity_days": 30,
        "price": 5000,
        "radius_group": "plan_200mbps",
        "ott_entitlements": ["chorki", "hoichoi"],
        "is_active": True,
        "is_public": True,
    },
]

BD_FIRST_NAMES = [
    "Rahim", "Karim", "Jamal", "Farhan", "Sakib", "Imran", "Arif", "Rakib",
    "Sumon", "Limon", "Nasir", "Bashir", "Zahir", "Mahfuz", "Rashed",
    "Fatima", "Nasrin", "Sumaiya", "Rahela", "Shirina", "Mitu", "Lima",
    "Tania", "Nusrat", "Sadia", "Lamia", "Ripa", "Mona", "Puja", "Rina",
]
BD_LAST_NAMES = [
    "Ahmed", "Hossain", "Islam", "Khan", "Rahman", "Begum", "Akter",
    "Molla", "Sarkar", "Das", "Roy", "Chowdhury", "Talukder", "Miah",
    "Sheikh", "Bhuiyan", "Nabi", "Uddin", "Ali", "Siddique",
]


def _rand_phone() -> str:
    prefix = random.choice(["017", "018", "019", "016", "015"])
    return prefix + "".join(random.choices(string.digits, k=8))


def _rand_username(first: str, last: str, n: int) -> str:
    return f"{first.lower()}.{last.lower()}{n:03d}"


def _rand_password(length: int = 10) -> str:
    return secrets.token_urlsafe(length)


# ---------------------------------------------------------------------------
# Main seed routine
# ---------------------------------------------------------------------------

async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # Check if already seeded
        result = await db.execute(select(Franchisee).limit(1))
        if result.scalar_one_or_none():
            print("Database already seeded — skipping.")
            return

        print("Seeding franchisees …")
        franchisee_objs: list[Franchisee] = []
        for i, fdata in enumerate(FRANCHISEES):
            f = Franchisee(**fdata)
            db.add(f)
            franchisee_objs.append(f)

        await db.flush()  # get IDs

        print("Seeding franchisee owner users …")
        for f in franchisee_objs:
            owner_pw = _rand_password()
            user = FranchiseeUser(
                franchisee_id=f.id,
                name=f"Owner of {f.name}",
                email=f"owner@{f.slug}.bd",
                phone=_rand_phone(),
                password_hash=pwd_ctx.hash(owner_pw),
                role="owner",
                is_active=True,
            )
            db.add(user)
            print(f"  {f.name}: owner email=owner@{f.slug}.bd  password={owner_pw}")

        print("Seeding NAS devices …")
        for idx, f in enumerate(franchisee_objs):
            nas = NASDevice(
                franchisee_id=f.id,
                name=f"{f.district} Main Router",
                ip_address=f"192.168.{idx + 1}.1",
                nas_type="mikrotik",
                secret=f.radius_secret or "changeme",
                coa_port=3799,
                description=f"Primary MikroTik for {f.name}",
                is_active=True,
            )
            db.add(nas)

        print("Seeding plans …")
        plan_objs: list[Plan] = []
        for pdata in PLANS:
            p = Plan(**pdata)
            db.add(p)
            plan_objs.append(p)

        await db.flush()

        print("Seeding 100 subscribers …")
        for n in range(1, 101):
            first = random.choice(BD_FIRST_NAMES)
            last = random.choice(BD_LAST_NAMES)
            username = _rand_username(first, last, n)
            pppoe_pw = _rand_password(8)
            portal_pw = _rand_password(8)
            franchisee = random.choice(franchisee_objs)
            plan = random.choice(plan_objs)

            sub = Subscriber(
                franchisee_id=franchisee.id,
                plan_id=plan.id,
                name=f"{first} {last}",
                email=f"{username}@example.bd",
                phone=_rand_phone(),
                username=username,
                password_hash=pwd_ctx.hash(portal_pw),
                pppoe_password_enc=pppoe_pw,  # plain for dev; encrypted in prod
                portal_password_hash=pwd_ctx.hash(portal_pw),
                status=random.choice(["active", "active", "active", "suspended", "expired"]),
                quota_used_bytes=random.randint(0, plan.download_kbps * 1024 * 10),
            )
            db.add(sub)

        await db.commit()

    # Summary
    async with AsyncSessionLocal() as db:
        f_count = (await db.execute(text("SELECT COUNT(*) FROM franchisees"))).scalar()
        p_count = (await db.execute(text("SELECT COUNT(*) FROM plans"))).scalar()
        s_count = (await db.execute(text("SELECT COUNT(*) FROM subscribers"))).scalar()

    print(f"\n✓ Seeding complete:")
    print(f"  Franchisees : {f_count}")
    print(f"  Plans       : {p_count}")
    print(f"  Subscribers : {s_count}")


if __name__ == "__main__":
    asyncio.run(seed())
