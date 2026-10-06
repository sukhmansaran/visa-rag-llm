"""
Test script for SOP generation functionality.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.sop_generator import generate_sop
from app.models.profile import Profile


async def test_sop_generation():
    """Test SOP generation with sample profiles."""
    
    print("=" * 80)
    print("SOP GENERATION TEST")
    print("=" * 80)
    
    # Test Case 1: Canada University - Computer Science
    print("\n\n📝 Test Case 1: Canada University - Computer Science Master's")
    print("-" * 80)
    
    profile_us = Profile(
        user_id=1,
        first_name="Priya",
        last_name="Sharma",
        education_level="bachelor",
        field_of_study="Computer Science",
        gpa=3.8,
        test_scores={
            "gre": {"verbal": 160, "quantitative": 168, "analytical": 4.5},
            "toefl": 108
        },
        work_experience=2
    )
    
    try:
        sop_us = await generate_sop(
            profile=profile_us,
            university="University of Toronto",
            program="Master of Science in Computer Science",
            additional_info="Interested in AI/ML research, particularly in natural language processing. Have published 2 papers in undergraduate research."
        )
        
        print(f"\n✅ Generated SOP ({len(sop_us.split())} words):\n")
        print(sop_us)
        print("\n" + "=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    
    # Test Case 2: Canada University - Business (commented out UK — Canada-only focus)
    print("\n\n📝 Test Case 2: Canada University - Business Master's")
    print("-" * 80)
    
    profile_uk = Profile(
        user_id=2,
        first_name="Raj",
        last_name="Patel",
        education_level="bachelor",
        field_of_study="Business Administration",
        gpa=3.6,
        test_scores={
            "ielts": 7.5
        },
        work_experience=3
    )
    
    try:
        sop_uk = await generate_sop(
            profile=profile_uk,
            university="McGill University",
            program="MSc in Management",
            additional_info="Currently working as a business analyst at a fintech startup. Want to transition into strategic consulting."
        )
        
        print(f"\n✅ Generated SOP ({len(sop_uk.split())} words):\n")
        print(sop_uk)
        print("\n" + "=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    
    # Test Case 3: Canada University - Engineering
    print("\n\n📝 Test Case 3: Canada University - Engineering PhD")
    print("-" * 80)
    
    profile_canada = Profile(
        user_id=3,
        first_name="Ahmed",
        last_name="Khan",
        education_level="master",
        field_of_study="Electrical Engineering",
        gpa=3.9,
        test_scores={
            "gre": {"verbal": 155, "quantitative": 170, "analytical": 4.0},
            "toefl": 102
        },
        work_experience=1
    )
    
    try:
        sop_canada = await generate_sop(
            profile=profile_canada,
            university="University of Toronto",
            program="PhD in Electrical and Computer Engineering",
            additional_info="Master's thesis on renewable energy systems. Want to work with Prof. Smith on smart grid optimization."
        )
        
        print(f"\n✅ Generated SOP ({len(sop_canada.split())} words):\n")
        print(sop_canada)
        print("\n" + "=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    
    # Test Case 4: Minimal Profile (commented out Australia — Canada-only focus)
    print("\n\n📝 Test Case 4: Minimal Profile (Testing Robustness)")
    print("-" * 80)
    
    profile_minimal = Profile(
        user_id=4,
        first_name="Student",
        last_name="Name",
        education_level="bachelor",
        field_of_study="Engineering"
    )
    
    try:
        sop_minimal = await generate_sop(
            profile=profile_minimal,
            university="University of Waterloo",
            program="Master of Engineering"
        )
        
        print(f"\n✅ Generated SOP ({len(sop_minimal.split())} words):\n")
        print(sop_minimal)
        print("\n" + "=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    
    print("\n\n✅ All tests completed!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_sop_generation())
