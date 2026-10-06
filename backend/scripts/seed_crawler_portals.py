"""
Seed script for default aggregator portals and seed URLs.

Seeds the 5 recommended starting portals:
  Studyportals (Tier 1), Hotcourses (Tier 1), UCAS (Tier 2),
  EduCanada (Tier 3), DAAD (Tier 5).
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import AsyncSessionLocal, init_db
from app.models.aggregator_portal import AggregatorPortal
from app.models.seed_url import SeedURL
from sqlalchemy import select

PORTALS = [
    {
        "name": "Studyportals",
        "tier": 1,
        "base_domains": [
            "mastersportal.com", "bachelorsportal.com",
            "phdportal.com", "shortcoursesportal.com",
        ],
        "category": "aggregator",
        "throttle_rps": 0.5,
        "requires_js": True,
        "seeds": [
            "https://www.mastersportal.com/search/master",
            "https://www.bachelorsportal.com/search/bachelor",
            "https://www.phdportal.com/search/phd",
        ],
    },
    {
        "name": "Hotcourses",
        "tier": 1,
        "base_domains": ["hotcoursesabroad.com"],
        "category": "aggregator",
        "throttle_rps": 0.5,
        "requires_js": False,
        "seeds": [
            "https://www.hotcoursesabroad.com/study/",
        ],
    },
    # Other countries' portals commented out — Canada-only focus
    # {
    #     "name": "UCAS",
    #     "tier": 2,
    #     "base_domains": ["ucas.com"],
    #     "category": "admissions_system",
    #     "throttle_rps": 1.0,
    #     "requires_js": True,
    #     "seeds": [
    #         "https://www.ucas.com/explore/search",
    #     ],
    # },
    {
        "name": "EduCanada",
        "tier": 3,
        "base_domains": ["educanada.ca"],
        "category": "government_portal",
        "throttle_rps": 1.0,
        "requires_js": False,
        "seeds": [
            "https://www.educanada.ca/programs-programmes/index.aspx",
        ],
    },
    # {
    #     "name": "DAAD",
    #     "tier": 5,
    #     "base_domains": ["daad.de"],
    #     "category": "country_portal",
    #     "throttle_rps": 1.0,
    #     "requires_js": True,
    #     "seeds": [
    #         "https://www.daad.de/en/study-and-research-in-germany/courses-of-study-in-germany/",
    #     ],
    # },
]


async def seed():
    await init_db()
    async with AsyncSessionLocal() as db:
        for portal_data in PORTALS:
            result = await db.execute(
                select(AggregatorPortal).where(
                    AggregatorPortal.name == portal_data["name"]
                )
            )
            portal = result.scalar_one_or_none()
            if not portal:
                portal = AggregatorPortal(
                    name=portal_data["name"],
                    tier=portal_data["tier"],
                    base_domains=portal_data["base_domains"],
                    category=portal_data["category"],
                    throttle_rps=portal_data["throttle_rps"],
                    requires_js=portal_data["requires_js"],
                )
                db.add(portal)
                await db.flush()
                print(f"Created portal: {portal.name} (Tier {portal.tier})")
            else:
                print(f"Portal already exists: {portal.name}")

            for seed_url in portal_data.get("seeds", []):
                existing = await db.execute(
                    select(SeedURL).where(SeedURL.url == seed_url)
                )
                if not existing.scalar_one_or_none():
                    seed = SeedURL(
                        portal_id=portal.id,
                        url=seed_url,
                        max_depth=3,
                        allowed_domains=portal_data["base_domains"],
                        crawl_schedule="weekly",
                    )
                    db.add(seed)
                    print(f"  Added seed: {seed_url}")

        await db.commit()
    print("Seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed())
