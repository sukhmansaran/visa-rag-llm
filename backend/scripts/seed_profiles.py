"""
Seed sample user profiles for testing.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.profile import Profile
from app.core.security import get_password_hash


async def seed_profiles():
    """Seed sample users with profiles."""
    
    async with AsyncSessionLocal() as db:
        print("🌱 Seeding sample user profiles...")
        
        # Sample users with profiles
        users_data = [
            {
                "email": "priya.sharma@example.com",
                "password": "test123",
                "full_name": "Priya Sharma",
                "profile": {
                    "first_name": "Priya",
                    "last_name": "Sharma",
                    "education_level": "bachelor",
                    "field_of_study": "Computer Science",
                    "gpa": 3.8,
                    "test_scores": {
                        "gre": {"verbal": 160, "quantitative": 168, "analytical": 4.5},
                        "toefl": 108
                    },
                    "work_experience": 2,
                    "target_countries": ["Canada"],
                    "target_universities": ["University of Toronto", "McGill University"]
                }
            },
            {
                "email": "raj.patel@example.com",
                "password": "test123",
                "full_name": "Raj Patel",
                "profile": {
                    "first_name": "Raj",
                    "last_name": "Patel",
                    "education_level": "bachelor",
                    "field_of_study": "Business Administration",
                    "gpa": 3.6,
                    "test_scores": {
                        "ielts": 7.5,
                        "gmat": 720
                    },
                    "work_experience": 3,
                    "target_countries": ["Canada"],
                    "target_universities": ["McGill University", "University of Toronto"]
                }
            },
            {
                "email": "ahmed.khan@example.com",
                "password": "test123",
                "full_name": "Ahmed Khan",
                "profile": {
                    "first_name": "Ahmed",
                    "last_name": "Khan",
                    "education_level": "master",
                    "field_of_study": "Electrical Engineering",
                    "gpa": 3.9,
                    "test_scores": {
                        "gre": {"verbal": 155, "quantitative": 170, "analytical": 4.0},
                        "toefl": 102
                    },
                    "work_experience": 1,
                    "target_countries": ["Canada"],
                    "target_universities": ["University of Toronto", "UBC"]
                }
            },
            {
                "email": "maria.garcia@example.com",
                "password": "test123",
                "full_name": "Maria Garcia",
                "profile": {
                    "first_name": "Maria",
                    "last_name": "Garcia",
                    "education_level": "bachelor",
                    "field_of_study": "Psychology",
                    "gpa": 3.7,
                    "test_scores": {
                        "gre": {"verbal": 165, "quantitative": 158, "analytical": 5.0},
                        "toefl": 110
                    },
                    "work_experience": 0,
                    "target_countries": ["Canada"],
                    "target_universities": ["McGill University", "University of Waterloo"]
                }
            },
            {
                "email": "test.user@example.com",
                "password": "test123",
                "full_name": "Test User",
                "profile": {
                    "first_name": "Test",
                    "last_name": "User",
                    "education_level": "bachelor",
                    "field_of_study": "Engineering",
                    "gpa": 3.5,
                    "test_scores": {},
                    "work_experience": 0,
                    "target_countries": ["Canada"],
                    "target_universities": ["University of Alberta"]
                }
            }
        ]
        
        created_count = 0
        
        for user_data in users_data:
            # Check if user already exists
            result = await db.execute(
                select(User).where(User.email == user_data["email"])
            )
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                print(f"⏭️  User {user_data['email']} already exists, skipping...")
                continue
            
            # Create user
            user = User(
                email=user_data["email"],
                full_name=user_data["full_name"],
                hashed_password=get_password_hash(user_data["password"]),
                is_active=True,
            )
            db.add(user)
            await db.flush()  # Get user ID
            
            # Create profile
            profile_data = user_data["profile"]
            profile = Profile(
                user_id=user.id,
                first_name=profile_data["first_name"],
                last_name=profile_data["last_name"],
                education_level=profile_data["education_level"],
                field_of_study=profile_data["field_of_study"],
                gpa=profile_data["gpa"],
                test_scores=profile_data["test_scores"],
                work_experience=profile_data["work_experience"],
                target_countries=profile_data.get("target_countries"),
                target_universities=profile_data.get("target_universities"),
            )
            db.add(profile)
            
            created_count += 1
            print(f"✅ Created user: {user_data['email']} with profile")
        
        await db.commit()
        
        print(f"\n🎉 Successfully created {created_count} users with profiles!")
        print("\nTest credentials:")
        print("  Email: priya.sharma@example.com | Password: test123")
        print("  Email: raj.patel@example.com | Password: test123")
        print("  Email: ahmed.khan@example.com | Password: test123")
        print("  Email: maria.garcia@example.com | Password: test123")
        print("  Email: test.user@example.com | Password: test123")


if __name__ == "__main__":
    asyncio.run(seed_profiles())
