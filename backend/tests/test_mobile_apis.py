import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_profile(client: AsyncClient):
    """Test getting user profile."""
    # Signup
    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = signup_response.json()["access_token"]
    
    # Get profile (should create empty one)
    response = await client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "first_name" in data


@pytest.mark.asyncio
async def test_update_profile(client: AsyncClient):
    """Test updating profile."""
    # Signup
    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = signup_response.json()["access_token"]
    
    # Update profile
    response = await client.put(
        "/api/v1/profile",
        json={
            "first_name": "John",
            "last_name": "Doe",
            "education_level": "bachelor",
            "field_of_study": "Computer Science",
            "gpa": 3.8,
            "target_countries": {"countries": ["Canada"]},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "John"
    assert data["education_level"] == "bachelor"


@pytest.mark.asyncio
async def test_generate_sop(client: AsyncClient):
    """Test SOP generation."""
    # Signup and create profile
    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = signup_response.json()["access_token"]
    
    await client.put(
        "/api/v1/profile",
        json={
            "first_name": "John",
            "education_level": "bachelor",
            "field_of_study": "CS",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    
    # Generate SOP
    response = await client.post(
        "/api/v1/documents/sop/generate",
        json={
            "university": "University of Toronto",
            "program": "MSc Computer Science",
        },
        headers={" Authorization": f"Bearer {token}"},
    )
    
    assert response.status_code == 201
    data = response.json()
    assert "content" in data
    assert data["document_type"] == "sop"


@pytest.mark.asyncio
async def test_watchlist(client: AsyncClient):
    """Test watchlist operations."""
    # Signup
    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = signup_response.json()["access_token"]
    
    # Add to watchlist
    response = await client.post(
        "/api/v1/watchlist",
        json={
            "watched_type": "university",
            "watched_value": "University of Toronto",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["watched_value"] == "University of Toronto"
    
    # Get watchlist
    response = await client.get(
        "/api/v1/watchlist",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
