"""Seed script to populate tourist visa and travel data."""

import asyncio
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.models.tourist_visa_info import TouristVisaInfo
from app.models.tourist_destination import TouristDestination
from app.models.travel_cost import TravelCost


async def seed_data():
    """Seed sample tourist visa and travel data."""
    
    async with AsyncSessionLocal() as db:
        print("🌍 Seeding tourist visa and travel data...")
        
        # Sample countries — Canada-only focus
        countries = ["Canada"]
        # countries = ["USA", "UK", "Canada", "Australia", "France", "Japan", "Thailand"]
        
        # Seed tourist visa info
        print("\n📋 Adding tourist visa information...")
        visa_data = [
            # Other countries commented out — Canada-only focus
            # {
            #     "country": "USA",
            #     "visa_required": True,
            #     "visa_types": ["B-1/B-2 Tourist", "ESTA (Visa Waiver)"],
            #     "processing_time": "3-5 weeks",
            #     "validity_period": "Up to 10 years (multiple entry)",
            #     "visa_fee_usd": Decimal("185.00"),
            #     "requirements": [
            #         "Valid passport (6 months validity)",
            #         "DS-160 form",
            #         "Visa fee payment receipt",
            #         "Passport-size photo",
            #         "Proof of financial means",
            #         "Travel itinerary",
            #         "Proof of ties to home country"
            #     ],
            #     "application_process": [
            #         {"step": 1, "description": "Complete DS-160 form online"},
            #         {"step": 2, "description": "Pay visa application fee"},
            #         {"step": 3, "description": "Schedule visa interview"},
            #         {"step": 4, "description": "Attend interview at US Embassy"},
            #         {"step": 5, "description": "Wait for visa processing"}
            #     ],
            #     "interview_required": True,
            #     "online_application": True,
            #     "official_website": "https://travel.state.gov"
            # },
            # {
            #     "country": "UK",
            #     "visa_required": True,
            #     "visa_types": ["Standard Visitor Visa"],
            #     "processing_time": "3 weeks",
            #     "validity_period": "6 months",
            #     "visa_fee_usd": Decimal("115.00"),
            #     "requirements": [
            #         "Valid passport",
            #         "Proof of accommodation",
            #         "Travel itinerary",
            #         "Bank statements (last 6 months)",
            #         "Employment letter",
            #         "Return flight tickets"
            #     ],
            #     "application_process": [
            #         {"step": 1, "description": "Apply online on gov.uk"},
            #         {"step": 2, "description": "Pay visa fee"},
            #         {"step": 3, "description": "Book biometrics appointment"},
            #         {"step": 4, "description": "Attend biometrics appointment"},
            #         {"step": 5, "description": "Wait for decision"}
            #     ],
            #     "interview_required": False,
            #     "online_application": True,
            #     "official_website": "https://www.gov.uk/standard-visitor-visa"
            # },
            # {
            #     "country": "Thailand",
            #     "visa_required": False,
            #     "visa_types": ["Visa Exemption (30 days)", "Tourist Visa (60 days)"],
            #     "processing_time": "3-5 business days",
            #     "validity_period": "60 days (single entry)",
            #     "visa_fee_usd": Decimal("40.00"),
            #     "requirements": [
            #         "Valid passport (6 months validity)",
            #         "Passport photo",
            #         "Proof of accommodation",
            #         "Return flight ticket",
            #         "Bank statement"
            #     ],
            #     "application_process": [
            #         {"step": 1, "description": "Apply at Thai Embassy or online (e-Visa)"},
            #         {"step": 2, "description": "Submit required documents"},
            #         {"step": 3, "description": "Pay visa fee"},
            #         {"step": 4, "description": "Wait for approval"}
            #     ],
            #     "interview_required": False,
            #     "online_application": True,
            #     "official_website": "https://www.thaiembassy.com"
            # }
            {
                "country": "Canada",
                "visa_required": True,
                "visa_types": ["Visitor Visa (TRV)", "eTA (Electronic Travel Authorization)"],
                "processing_time": "2-4 weeks",
                "validity_period": "Up to 10 years (multiple entry)",
                "visa_fee_usd": Decimal("100.00"),
                "requirements": [
                    "Valid passport (6 months validity)",
                    "Completed application form",
                    "Passport-size photos",
                    "Proof of financial means",
                    "Travel itinerary",
                    "Proof of ties to home country",
                    "Letter of invitation (if applicable)"
                ],
                "application_process": [
                    {"step": 1, "description": "Apply online via IRCC portal"},
                    {"step": 2, "description": "Pay application fee"},
                    {"step": 3, "description": "Submit biometrics"},
                    {"step": 4, "description": "Wait for processing"},
                    {"step": 5, "description": "Receive visa decision"}
                ],
                "interview_required": False,
                "online_application": True,
                "official_website": "https://www.canada.ca/en/immigration-refugees-citizenship.html"
            }
        ]
        
        for data in visa_data:
            visa_info = TouristVisaInfo(**data)
            db.add(visa_info)
        
        await db.commit()
        print(f"✓ Added {len(visa_data)} tourist visa records")
        
        # Seed tourist destinations — Canada-only focus
        print("\n🏛️ Adding tourist destinations...")
        destinations = [
            {
                "country": "Canada",
                "city": "Toronto",
                "name": "CN Tower",
                "description": "Iconic Toronto landmark and communications tower with observation deck",
                "category": "landmark",
                "rating": Decimal("4.7"),
                "estimated_time": "2-3 hours",
                "entry_fee_usd": Decimal("30.00"),
                "best_time_to_visit": "May to October",
                "image_url": "https://example.com/cn-tower.jpg",
                "coordinates": {"lat": 43.6426, "lng": -79.3871}
            },
            {
                "country": "Canada",
                "city": "Vancouver",
                "name": "Stanley Park",
                "description": "Urban park with scenic seawall, totem poles, and nature trails",
                "category": "park",
                "rating": Decimal("4.8"),
                "estimated_time": "3-5 hours",
                "entry_fee_usd": Decimal("0.00"),
                "best_time_to_visit": "June to September",
                "image_url": "https://example.com/stanley-park.jpg",
                "coordinates": {"lat": 49.3043, "lng": -123.1443}
            },
            {
                "country": "Canada",
                "city": "Montreal",
                "name": "Old Montreal",
                "description": "Historic district with cobblestone streets and 17th-century architecture",
                "category": "landmark",
                "rating": Decimal("4.6"),
                "estimated_time": "3-4 hours",
                "entry_fee_usd": Decimal("0.00"),
                "best_time_to_visit": "May to October",
                "image_url": "https://example.com/old-montreal.jpg",
                "coordinates": {"lat": 45.5079, "lng": -73.5540}
            },
            {
                "country": "Canada",
                "city": "Niagara Falls",
                "name": "Niagara Falls",
                "description": "World-famous waterfalls on the Ontario-New York border",
                "category": "landmark",
                "rating": Decimal("4.9"),
                "estimated_time": "4-6 hours",
                "entry_fee_usd": Decimal("0.00"),
                "best_time_to_visit": "June to August",
                "image_url": "https://example.com/niagara-falls.jpg",
                "coordinates": {"lat": 43.0896, "lng": -79.0849}
            },
            # Other countries commented out — Canada-only focus
            # {
            #     "country": "USA",
            #     "city": "New York",
            #     "name": "Statue of Liberty",
            #     "description": "Iconic symbol of freedom and democracy",
            #     "category": "landmark",
            #     "rating": Decimal("4.8"),
            #     "estimated_time": "2-3 hours",
            #     "entry_fee_usd": Decimal("24.00"),
            #     "best_time_to_visit": "April to June, September to November",
            #     "image_url": "https://example.com/statue-of-liberty.jpg",
            #     "coordinates": {"lat": 40.6892, "lng": -74.0445}
            # },
            # {
            #     "country": "USA",
            #     "city": "New York",
            #     "name": "Central Park",
            #     "description": "Urban park in Manhattan",
            #     "category": "park",
            #     "rating": Decimal("4.7"),
            #     "estimated_time": "2-4 hours",
            #     "entry_fee_usd": Decimal("0.00"),
            #     "best_time_to_visit": "Spring and Fall",
            #     "image_url": "https://example.com/central-park.jpg",
            #     "coordinates": {"lat": 40.7829, "lng": -73.9654}
            # },
            # {
            #     "country": "UK",
            #     "city": "London",
            #     "name": "Tower of London",
            #     "description": "Historic castle and UNESCO World Heritage Site",
            #     "category": "landmark",
            #     "rating": Decimal("4.6"),
            #     "estimated_time": "3-4 hours",
            #     "entry_fee_usd": Decimal("35.00"),
            #     "best_time_to_visit": "May to September",
            #     "image_url": "https://example.com/tower-of-london.jpg",
            #     "coordinates": {"lat": 51.5081, "lng": -0.0759}
            # },
            # {
            #     "country": "Thailand",
            #     "city": "Bangkok",
            #     "name": "Grand Palace",
            #     "description": "Former royal residence and iconic Bangkok landmark",
            #     "category": "landmark",
            #     "rating": Decimal("4.5"),
            #     "estimated_time": "2-3 hours",
            #     "entry_fee_usd": Decimal("15.00"),
            #     "best_time_to_visit": "November to February",
            #     "image_url": "https://example.com/grand-palace.jpg",
            #     "coordinates": {"lat": 13.7500, "lng": 100.4917}
            # }
        ]
        
        for dest in destinations:
            destination = TouristDestination(**dest)
            db.add(destination)
        
        await db.commit()
        print(f"✓ Added {len(destinations)} tourist destinations")
        
        # Seed travel costs — Canada-only focus
        print("\n💰 Adding travel cost data...")
        costs = [
            # Canada costs
            {"country": "Canada", "city": "Toronto", "category": "flight", "item_name": "Round trip flight", 
             "cost_usd_min": Decimal("350"), "cost_usd_max": Decimal("1000"), "cost_usd_avg": Decimal("600"), 
             "unit": "per person", "season": "off-peak"},
            {"country": "Canada", "city": "Toronto", "category": "hotel", "item_name": "Budget hotel", 
             "cost_usd_min": Decimal("70"), "cost_usd_max": Decimal("130"), "cost_usd_avg": Decimal("95"), 
             "unit": "per night", "notes": "budget"},
            {"country": "Canada", "city": "Toronto", "category": "hotel", "item_name": "Mid-range hotel", 
             "cost_usd_min": Decimal("130"), "cost_usd_max": Decimal("250"), "cost_usd_avg": Decimal("180"), 
             "unit": "per night", "notes": "mid-range"},
            {"country": "Canada", "city": "Toronto", "category": "food", "item_name": "Daily meals", 
             "cost_usd_min": Decimal("25"), "cost_usd_max": Decimal("70"), "cost_usd_avg": Decimal("45"), 
             "unit": "per day per person"},
            {"country": "Canada", "city": "Toronto", "category": "transport", "item_name": "TTC/taxi", 
             "cost_usd_min": Decimal("8"), "cost_usd_max": Decimal("25"), "cost_usd_avg": Decimal("15"), 
             "unit": "per day"},
            {"country": "Canada", "city": "Toronto", "category": "activities", "item_name": "Attractions/tours", 
             "cost_usd_min": Decimal("15"), "cost_usd_max": Decimal("80"), "cost_usd_avg": Decimal("40"), 
             "unit": "per day per person"},
            {"country": "Canada", "city": "Vancouver", "category": "flight", "item_name": "Round trip flight", 
             "cost_usd_min": Decimal("400"), "cost_usd_max": Decimal("1100"), "cost_usd_avg": Decimal("650"), 
             "unit": "per person", "season": "off-peak"},
            {"country": "Canada", "city": "Vancouver", "category": "hotel", "item_name": "Budget hotel", 
             "cost_usd_min": Decimal("80"), "cost_usd_max": Decimal("140"), "cost_usd_avg": Decimal("100"), 
             "unit": "per night", "notes": "budget"},
            {"country": "Canada", "city": "Vancouver", "category": "food", "item_name": "Daily meals", 
             "cost_usd_min": Decimal("25"), "cost_usd_max": Decimal("65"), "cost_usd_avg": Decimal("40"), 
             "unit": "per day per person"},
            {"country": "Canada", "city": "Montreal", "category": "flight", "item_name": "Round trip flight", 
             "cost_usd_min": Decimal("300"), "cost_usd_max": Decimal("900"), "cost_usd_avg": Decimal("550"), 
             "unit": "per person", "season": "off-peak"},
            {"country": "Canada", "city": "Montreal", "category": "hotel", "item_name": "Budget hotel", 
             "cost_usd_min": Decimal("60"), "cost_usd_max": Decimal("120"), "cost_usd_avg": Decimal("85"), 
             "unit": "per night", "notes": "budget"},
            {"country": "Canada", "city": "Montreal", "category": "food", "item_name": "Daily meals", 
             "cost_usd_min": Decimal("20"), "cost_usd_max": Decimal("55"), "cost_usd_avg": Decimal("35"), 
             "unit": "per day per person"},
            
            # Other countries commented out — Canada-only focus
            # # USA costs
            # {"country": "USA", "city": "New York", "category": "flight", "item_name": "Round trip flight", 
            #  "cost_usd_min": Decimal("400"), "cost_usd_max": Decimal("1200"), "cost_usd_avg": Decimal("700"), 
            #  "unit": "per person", "season": "off-peak"},
            # {"country": "USA", "city": "New York", "category": "hotel", "item_name": "Budget hotel", 
            #  "cost_usd_min": Decimal("80"), "cost_usd_max": Decimal("150"), "cost_usd_avg": Decimal("110"), 
            #  "unit": "per night", "notes": "budget"},
            # {"country": "USA", "city": "New York", "category": "hotel", "item_name": "Mid-range hotel", 
            #  "cost_usd_min": Decimal("150"), "cost_usd_max": Decimal("300"), "cost_usd_avg": Decimal("200"), 
            #  "unit": "per night", "notes": "mid-range"},
            # {"country": "USA", "city": "New York", "category": "food", "item_name": "Daily meals", 
            #  "cost_usd_min": Decimal("30"), "cost_usd_max": Decimal("80"), "cost_usd_avg": Decimal("50"), 
            #  "unit": "per day per person"},
            # {"country": "USA", "city": "New York", "category": "transport", "item_name": "Metro/taxi", 
            #  "cost_usd_min": Decimal("10"), "cost_usd_max": Decimal("30"), "cost_usd_avg": Decimal("20"), 
            #  "unit": "per day"},
            # {"country": "USA", "city": "New York", "category": "activities", "item_name": "Attractions/tours", 
            #  "cost_usd_min": Decimal("20"), "cost_usd_max": Decimal("100"), "cost_usd_avg": Decimal("50"), 
            #  "unit": "per day per person"},
            # 
            # # UK costs
            # {"country": "UK", "city": "London", "category": "flight", "item_name": "Round trip flight", 
            #  "cost_usd_min": Decimal("300"), "cost_usd_max": Decimal("900"), "cost_usd_avg": Decimal("550"), 
            #  "unit": "per person", "season": "off-peak"},
            # {"country": "UK", "city": "London", "category": "hotel", "item_name": "Budget hotel", 
            #  "cost_usd_min": Decimal("60"), "cost_usd_max": Decimal("120"), "cost_usd_avg": Decimal("85"), 
            #  "unit": "per night", "notes": "budget"},
            # {"country": "UK", "city": "London", "category": "food", "item_name": "Daily meals", 
            #  "cost_usd_min": Decimal("25"), "cost_usd_max": Decimal("60"), "cost_usd_avg": Decimal("40"), 
            #  "unit": "per day per person"},
            # 
            # # Thailand costs
            # {"country": "Thailand", "city": "Bangkok", "category": "flight", "item_name": "Round trip flight", 
            #  "cost_usd_min": Decimal("400"), "cost_usd_max": Decimal("1000"), "cost_usd_avg": Decimal("650"), 
            #  "unit": "per person", "season": "off-peak"},
            # {"country": "Thailand", "city": "Bangkok", "category": "hotel", "item_name": "Budget hotel", 
            #  "cost_usd_min": Decimal("15"), "cost_usd_max": Decimal("40"), "cost_usd_avg": Decimal("25"), 
            #  "unit": "per night", "notes": "budget"},
            # {"country": "Thailand", "city": "Bangkok", "category": "food", "item_name": "Daily meals", 
            #  "cost_usd_min": Decimal("10"), "cost_usd_max": Decimal("30"), "cost_usd_avg": Decimal("15"), 
            #  "unit": "per day per person"},
            # {"country": "Thailand", "city": "Bangkok", "category": "transport", "item_name": "Tuk-tuk/taxi", 
            #  "cost_usd_min": Decimal("5"), "cost_usd_max": Decimal("15"), "cost_usd_avg": Decimal("10"), 
            #  "unit": "per day"},
        ]
        
        for cost_data in costs:
            cost = TravelCost(**cost_data)
            db.add(cost)
        
        await db.commit()
        print(f"✓ Added {len(costs)} travel cost records")
        
        print("\n✅ Seeding completed successfully!")
        print("\nYou can now:")
        print("  - Query tourist visa info: GET /api/v1/tourist-visa/{country}")
        print("  - Browse destinations: GET /api/v1/travel/destinations/{country}")
        print("  - Estimate costs: POST /api/v1/travel-costs/estimate")


if __name__ == "__main__":
    asyncio.run(seed_data())
