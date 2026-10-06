import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_signup(client: AsyncClient):
    """Test user signup."""
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient):
    """Test signup with duplicate email."""
    # First signup
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    
    # Duplicate signup
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    """Test user login."""
    # Signup first
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    
    # Login
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    """Test login with invalid credentials."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "wrongpass"},
    )
    
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user(client: AsyncClient):
    """Test getting current user info."""
    # Signup
    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = signup_response.json()["access_token"]
    
    # Get user info
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["is_active"] is True
    assert data["is_admin"] is False


@pytest.mark.asyncio
async def test_get_current_user_unauthorized(client: AsyncClient):
    """Test getting user info without token."""
    response = await client.get("/api/v1/auth/me")
    
    assert response.status_code == 403  # No Authorization header
