"""
Seed initial sources for web scraping.
Includes embassy websites and top universities.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.source import Source


# Canada-only focus (other countries commented out)
EMBASSY_SOURCES = [
    # Other countries commented out — Canada-only focus
    # # United States
    # {
    #     "url": "https://travel.state.gov/content/travel/en/us-visas/study.html",
    #     "name": "US Student Visa - Official",
    #     "country": "USA",
    #     "source_type": "embassy",
    #     "priority": 1,
    #     "scrape_frequency": 168  # Weekly
    # },
    # {
    #     "url": "https://www.uscis.gov/working-in-the-united-states/students-and-exchange-visitors",
    #     "name": "USCIS Student Information",
    #     "country": "USA",
    #     "source_type": "official",
    #     "priority": 1,
    #     "scrape_frequency": 168
    # },
    #
    # # United Kingdom
    # {
    #     "url": "https://www.gov.uk/student-visa",
    #     "name": "UK Student Visa - Official",
    #     "country": "UK",
    #     "source_type": "embassy",
    #     "priority": 1,
    #     "scrape_frequency": 168
    # },
    # {
    #     "url": "https://www.gov.uk/guidance/immigration-rules/immigration-rules-appendix-student",
    #     "name": "UK Student Immigration Rules",
    #     "country": "UK",
    #     "source_type": "official",
    #     "priority": 2,
    #     "scrape_frequency": 336  # Bi-weekly
    # },
    
    # Canada
    {
        "url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html",
        "name": "Study in Canada - Official",
        "country": "Canada",
        "source_type": "embassy",
        "priority": 1,
        "scrape_frequency": 168
    },
    {
        "url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/study-permit.html",
        "name": "Canada Study Permit",
        "country": "Canada",
        "source_type": "official",
        "priority": 1,
        "scrape_frequency": 168
    },
    
    # Other countries commented out — Canada-only focus
    # # Australia
    # {
    #     "url": "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500",
    #     "name": "Australia Student Visa (500)",
    #     "country": "Australia",
    #     "source_type": "embassy",
    #     "priority": 1,
    #     "scrape_frequency": 168
    # },
    #
    # # Germany
    # {
    #     "url": "https://www.auswaertiges-amt.de/en/visa-service/buergerservice/faq/-/606852",
    #     "name": "Germany Student Visa",
    #     "country": "Germany",
    #     "source_type": "embassy",
    #     "priority": 2,
    #     "scrape_frequency": 168
    # },
    #
    # # France
    # {
    #     "url": "https://france-visas.gouv.fr/en/web/france-visas/student-visa",
    #     "name": "France Student Visa",
    #     "country": "France",
    #     "source_type": "embassy",
    #     "priority": 2,
    #     "scrape_frequency": 168
    # },
    #
    # # Netherlands
    # {
    #     "url": "https://ind.nl/en/study/pages/study-at-university.aspx",
    #     "name": "Netherlands Study Visa",
    #     "country": "Netherlands",
    #     "source_type": "embassy",
    #     "priority": 2,
    #     "scrape_frequency": 168
    # },
    #
    # # New Zealand
    # {
    #     "url": "https://www.immigration.govt.nz/new-zealand-visas/apply-for-a-visa/about-visa/student-visa",
    #     "name": "New Zealand Student Visa",
    #     "country": "New Zealand",
    #     "source_type": "embassy",
    #     "priority": 2,
    #     "scrape_frequency": 168
    # },
    #
    # # Ireland
    # {
    #     "url": "https://www.irishimmigration.ie/coming-to-study-in-ireland/",
    #     "name": "Ireland Student Visa",
    #     "country": "Ireland",
    #     "source_type": "embassy",
    #     "priority": 2,
    #     "scrape_frequency": 168
    # },
    #
    # # Singapore
    # {
    #     "url": "https://www.ica.gov.sg/enter-transit-depart/entering-singapore/visa_requirements",
    #     "name": "Singapore Student Pass",
    #     "country": "Singapore",
    #     "source_type": "embassy",
    #     "priority": 2,
    #     "scrape_frequency": 168
    # },
    #
    # # Japan
    # {
    #     "url": "https://www.mofa.go.jp/j_info/visit/visa/index.html",
    #     "name": "Japan Student Visa",
    #     "country": "Japan",
    #     "source_type": "embassy",
    #     "priority": 3,
    #     "scrape_frequency": 336
    # },
    #
    # # South Korea
    # {
    #     "url": "https://www.visa.go.kr/openPage.do?MENU_ID=10101",
    #     "name": "South Korea Student Visa",
    #     "country": "South Korea",
    #     "source_type": "embassy",
    #     "priority": 3,
    #     "scrape_frequency": 336
    # },
]


# Canadian Universities (other countries commented out — Canada-only focus)
UNIVERSITY_SOURCES = [
    # Other countries commented out — Canada-only focus
    # # US Universities
    # {
    #     "url": "https://admission.stanford.edu/apply/international/index.html",
    #     "name": "Stanford University - International Admissions",
    #     "country": "USA",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://mitadmissions.org/apply/international/",
    #     "name": "MIT - International Admissions",
    #     "country": "USA",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://college.harvard.edu/admissions/apply/international-applicants",
    #     "name": "Harvard - International Applicants",
    #     "country": "USA",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://admissions.berkeley.edu/international-students",
    #     "name": "UC Berkeley - International Students",
    #     "country": "USA",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://www.caltech.edu/admissions/international-students",
    #     "name": "Caltech - International Students",
    #     "country": "USA",
    #     "source_type": "university",
    #     "priority": 2,
    #     "scrape_frequency": 336
    # },
    #
    # # UK Universities
    # {
    #     "url": "https://www.ox.ac.uk/admissions/undergraduate/applying-to-oxford/international-students",
    #     "name": "Oxford - International Students",
    #     "country": "UK",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://www.undergraduate.study.cam.ac.uk/international-students",
    #     "name": "Cambridge - International Students",
    #     "country": "UK",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://www.imperial.ac.uk/study/international-students/",
    #     "name": "Imperial College London - International",
    #     "country": "UK",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://www.ucl.ac.uk/prospective-students/international",
    #     "name": "UCL - International Students",
    #     "country": "UK",
    #     "source_type": "university",
    #     "priority": 2,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://www.lse.ac.uk/study-at-lse/international-students",
    #     "name": "LSE - International Students",
    #     "country": "UK",
    #     "source_type": "university",
    #     "priority": 2,
    #     "scrape_frequency": 336
    # },
    
    # Canadian Universities
    {
        "url": "https://future.utoronto.ca/apply/international-students/",
        "name": "University of Toronto - International",
        "country": "Canada",
        "source_type": "university",
        "priority": 1,
        "scrape_frequency": 336
    },
    {
        "url": "https://www.mcgill.ca/applying/requirements/international",
        "name": "McGill University - International",
        "country": "Canada",
        "source_type": "university",
        "priority": 1,
        "scrape_frequency": 336
    },
    {
        "url": "https://you.ubc.ca/applying-ubc/international/",
        "name": "UBC - International Students",
        "country": "Canada",
        "source_type": "university",
        "priority": 1,
        "scrape_frequency": 336
    },
    
    # Other countries commented out — Canada-only focus
    # # Australian Universities
    # {
    #     "url": "https://study.unimelb.edu.au/how-to-apply/international-applications",
    #     "name": "University of Melbourne - International",
    #     "country": "Australia",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://www.sydney.edu.au/study/how-to-apply/international-students.html",
    #     "name": "University of Sydney - International",
    #     "country": "Australia",
    #     "source_type": "university",
    #     "priority": 1,
    #     "scrape_frequency": 336
    # },
    # {
    #     "url": "https://www.anu.edu.au/study/apply/international-applications",
    #     "name": "ANU - International Applications",
    #     "country": "Australia",
    #     "source_type": "university",
    #     "priority": 2,
    #     "scrape_frequency": 336
    # },
]


async def seed_sources():
    """Seed initial sources for scraping."""
    
    async with AsyncSessionLocal() as db:
        print("🌱 Seeding sources...")
        print("=" * 80)
        
        all_sources = EMBASSY_SOURCES + UNIVERSITY_SOURCES
        created_count = 0
        skipped_count = 0
        
        for source_data in all_sources:
            # Check if source already exists
            result = await db.execute(
                select(Source).where(Source.url == source_data["url"])
            )
            existing_source = result.scalar_one_or_none()
            
            if existing_source:
                print(f"⏭️  Skipping: {source_data['name']} (already exists)")
                skipped_count += 1
                continue
            
            # Create new source
            source = Source(**source_data)
            db.add(source)
            created_count += 1
            print(f"✅ Added: {source_data['name']}")
        
        await db.commit()
        
        print("\n" + "=" * 80)
        print(f"🎉 Seeding complete!")
        print(f"   Created: {created_count} sources")
        print(f"   Skipped: {skipped_count} sources (already exist)")
        print(f"   Total: {len(all_sources)} sources")
        print("=" * 80)
        
        # Summary by type
        print("\n📊 Summary by Type:")
        embassy_count = len([s for s in all_sources if s["source_type"] == "embassy"])
        official_count = len([s for s in all_sources if s["source_type"] == "official"])
        university_count = len([s for s in all_sources if s["source_type"] == "university"])
        
        print(f"   Embassy Sites: {embassy_count}")
        print(f"   Official Sites: {official_count}")
        print(f"   Universities: {university_count}")
        
        # Summary by country
        print("\n🌍 Summary by Country:")
        countries = {}
        for source in all_sources:
            country = source["country"]
            countries[country] = countries.get(country, 0) + 1
        
        for country, count in sorted(countries.items(), key=lambda x: x[1], reverse=True):
            print(f"   {country}: {count} sources")


if __name__ == "__main__":
    asyncio.run(seed_sources())
