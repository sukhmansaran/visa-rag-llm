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
    
    assert response.status_code == 401  # No Authorization header (FastAPI >= 0.11x HTTPBearer returns 401)


@pytest.mark.asyncio
@pytest.mark.parametrize("weak", ["short1", "allletterspassword", "1234567890123", "aaaaaaaaaa1"])
async def test_signup_rejects_weak_passwords(client: AsyncClient, weak):
    """A4: minimum password policy."""
    response = await client.post("/api/v1/auth/signup", json={"email": "weak@example.com", "password": weak})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_is_case_insensitive_on_email(client: AsyncClient):
    await client.post("/api/v1/auth/signup", json={"email": "Case@Example.com", "password": "testpass123"})
    response = await client.post("/api/v1/auth/login", json={"email": "CASE@example.COM", "password": "testpass123"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_refresh_token_is_single_use(client: AsyncClient):
    """A3: a refresh token is revoked once used; replaying it is rejected."""
    signup = await client.post("/api/v1/auth/signup", json={"email": "rotate@example.com", "password": "testpass123"})
    original = signup.json()["refresh_token"]

    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert first.status_code == 200
    rotated = first.json()["refresh_token"]
    assert rotated != original

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401

    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": rotated})).status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client: AsyncClient):
    signup = await client.post("/api/v1/auth/signup", json={"email": "logout@example.com", "password": "testpass123"})
    tokens = signup.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    out = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers)
    assert out.status_code == 204
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
