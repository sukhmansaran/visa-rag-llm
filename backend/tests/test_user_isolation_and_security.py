"""
Security and Cross-User Isolation Test Suite (Production-Readiness Phase 1).

Validates:
1. Token validation: missing, invalid, expired, tampered, wrong type, inactive user.
2. Cross-user profile isolation: User A cannot read or mutate User B's profile.
3. Cross-user chat isolation: User A cannot read or hijack User B's conversations or session history.
4. Cross-user documents & SOP isolation: User A cannot read, edit, or delete User B's documents.
5. Cross-user watchlist isolation: User A cannot access or delete User B's watchlist.
6. Cross-user application tracking isolation: User A cannot access or delete User B's applications.
7. Cross-user visa risk assessment isolation: User A cannot access User B's visa risk summary.
"""

import pytest
from httpx import AsyncClient
from datetime import timedelta
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User
from app.models.profile import Profile
from app.models.user_document import UserDocument
from app.models.application import ApplicationTracker
from app.models.watchlist import Watchlist
from app.models.chat_message import ChatMessage


# ==============================================================================
# Helper fixtures / functions
# ==============================================================================

async def _register_and_login(client: AsyncClient, email: str, password: str = "SecurePass123!") -> dict:
    """Register a user and return email, password, user_id, and token."""
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": f"User {email}"},
    )
    assert response.status_code == 201, f"Signup failed: {response.text}"
    data = response.json()
    token = data["access_token"]

    # Get user id via /auth/me
    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    user_id = me_resp.json()["id"]

    return {
        "email": email,
        "password": password,
        "id": user_id,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


# ==============================================================================
# 1. Token Security & Lifecycle Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_missing_token_returns_403(client: AsyncClient):
    """Missing Authorization header must return 403 Forbidden under HTTPBearer."""
    endpoints = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/profile"),
        ("PUT", "/api/v1/profile"),
        ("GET", "/api/v1/chat/history"),
        ("POST", "/api/v1/chat/answer"),
        ("GET", "/api/v1/documents/"),
        ("GET", "/api/v1/watchlist"),
        ("GET", "/api/v1/applications"),
        ("GET", "/api/v1/visa-risk/1"),
    ]
    for method, path in endpoints:
        if method == "GET":
            resp = await client.get(path)
        elif method == "POST":
            resp = await client.post(path, json={})
        elif method == "PUT":
            resp = await client.put(path, json={})
        assert resp.status_code == 403, f"Expected 403 for {method} {path}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_auth_malformed_token_returns_401(client: AsyncClient):
    """Malformed or garbage bearer token must return 401 Unauthorized."""
    garbage_headers = {"Authorization": "Bearer not-a-valid-jwt-token"}
    resp = await client.get("/api/v1/auth/me", headers=garbage_headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_tampered_signature_returns_401(client: AsyncClient):
    """JWT with tampered signature or forged secret must return 401 Unauthorized."""
    user = await _register_and_login(client, "victim@test.com")
    # Forge token with a different secret key
    forged_token = jwt.encode(
        {"sub": str(user["id"]), "type": "access"},
        "wrong-secret-key-12345678901234567890",
        algorithm=settings.ALGORITHM,
    )
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_expired_token_returns_401(client: AsyncClient):
    """Expired token must return 401 Unauthorized."""
    user = await _register_and_login(client, "expired@test.com")
    # Token expired 1 hour ago
    expired_token = create_access_token(
        {"sub": str(user["id"])},
        expires_delta=timedelta(hours=-1),
    )
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_wrong_token_type_returns_401(client: AsyncClient):
    """Using a refresh token where an access token is expected must return 401 Unauthorized."""
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": "refreshtype@test.com", "password": "SecurePass123!"},
    )
    refresh_token = signup_resp.json()["refresh_token"]
    # Attempt to authenticate API call with refresh token
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_nonexistent_user_returns_404(client: AsyncClient):
    """Validly signed token for a non-existent user ID must return 404."""
    phantom_token = create_access_token({"sub": "999999"})
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {phantom_token}"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_auth_inactive_user_rejected(client: AsyncClient, db_session: AsyncSession):
    """Deactivated user account must be rejected with 403 Forbidden."""
    user = await _register_and_login(client, "deactivated@test.com")
    
    # Deactivate user in database
    result = await db_session.execute(select(User).where(User.id == user["id"]))
    db_user = result.scalar_one()
    db_user.is_active = False
    await db_session.commit()

    resp = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert resp.status_code == 403
    assert "Inactive" in resp.json()["detail"]


# ==============================================================================
# 2. Cross-User Profile Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_user_profile_isolation(client: AsyncClient):
    """User B cannot read or overwrite User A's profile."""
    user_a = await _register_and_login(client, "profile_a@test.com")
    user_b = await _register_and_login(client, "profile_b@test.com")

    # User A updates profile
    update_a = await client.put(
        "/api/v1/profile",
        json={"first_name": "Alice", "last_name": "Smith", "field_of_study": "Robotics"},
        headers=user_a["headers"],
    )
    assert update_a.status_code == 200

    # User B updates profile
    update_b = await client.put(
        "/api/v1/profile",
        json={"first_name": "Bob", "last_name": "Jones", "field_of_study": "Economics"},
        headers=user_b["headers"],
    )
    assert update_b.status_code == 200

    # User A reads profile -> receives Alice
    profile_a = await client.get("/api/v1/profile", headers=user_a["headers"])
    assert profile_a.json()["first_name"] == "Alice"
    assert profile_a.json()["field_of_study"] == "Robotics"

    # User B reads profile -> receives Bob
    profile_b = await client.get("/api/v1/profile", headers=user_b["headers"])
    assert profile_b.json()["first_name"] == "Bob"
    assert profile_b.json()["field_of_study"] == "Economics"


# ==============================================================================
# 3. Cross-User Chat History Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_user_chat_history_isolation(client: AsyncClient, db_session: AsyncSession):
    """User B cannot see User A's chat messages in history."""
    user_a = await _register_and_login(client, "chata@test.com")
    user_b = await _register_and_login(client, "chatb@test.com")

    # Direct database insertion for deterministic chat isolation testing
    msg_a = ChatMessage(
        user_id=user_a["id"],
        role="user",
        content="Secret query from User A: What are my Canada visa deadlines?",
        session_id="session-user-a-123",
    )
    db_session.add(msg_a)
    await db_session.commit()

    # User A retrieves history -> sees message
    history_a = await client.get("/api/v1/chat/history", headers=user_a["headers"])
    assert history_a.status_code == 200
    messages_a = history_a.json()["messages"]
    assert any("Secret query from User A" in m["content"] for m in messages_a)

    # User B retrieves history -> cannot see User A's message
    history_b = await client.get("/api/v1/chat/history", headers=user_b["headers"])
    assert history_b.status_code == 200
    messages_b = history_b.json()["messages"]
    assert not any("Secret query from User A" in m["content"] for m in messages_b)


# ==============================================================================
# 4. Cross-User Documents & SOP Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_user_document_isolation(client: AsyncClient, db_session: AsyncSession):
    """User B cannot read, modify, list, or delete User A's documents."""
    user_a = await _register_and_login(client, "doc_a@test.com")
    user_b = await _register_and_login(client, "doc_b@test.com")

    # Create document owned by User A
    doc_a = UserDocument(
        user_id=user_a["id"],
        document_type="sop",
        content="Confidential SOP draft for University of Toronto",
        version=1,
    )
    db_session.add(doc_a)
    await db_session.commit()
    await db_session.refresh(doc_a)

    doc_id = doc_a.id

    # 1. User B tries to read User A's SOP -> 404
    read_resp = await client.get(f"/api/v1/documents/sop/{doc_id}", headers=user_b["headers"])
    assert read_resp.status_code == 404

    # 2. User B tries to modify User A's SOP -> 404
    update_resp = await client.put(
        f"/api/v1/documents/sop/{doc_id}",
        json={"content": "Maliciously overwritten content"},
        headers=user_b["headers"],
    )
    assert update_resp.status_code == 404

    # 3. User B lists documents -> User A's doc must not appear
    list_resp = await client.get("/api/v1/documents/", headers=user_b["headers"])
    assert list_resp.status_code == 200
    doc_ids_b = [d["id"] for d in list_resp.json()]
    assert doc_id not in doc_ids_b

    # 4. User B tries to delete User A's document -> 404
    delete_resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=user_b["headers"])
    assert delete_resp.status_code == 404

    # 5. User A can still access their document intact
    a_resp = await client.get(f"/api/v1/documents/sop/{doc_id}", headers=user_a["headers"])
    assert a_resp.status_code == 200
    assert a_resp.json()["content"] == "Confidential SOP draft for University of Toronto"


# ==============================================================================
# 5. Cross-User Watchlist Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_user_watchlist_isolation(client: AsyncClient):
    """User B cannot view or remove items from User A's watchlist."""
    user_a = await _register_and_login(client, "watch_a@test.com")
    user_b = await _register_and_login(client, "watch_b@test.com")

    # User A adds item to watchlist
    add_resp = await client.post(
        "/api/v1/watchlist",
        json={"watched_type": "university", "watched_value": "McGill University"},
        headers=user_a["headers"],
    )
    assert add_resp.status_code == 201
    item_id = add_resp.json()["id"]

    # User B gets watchlist -> must be empty
    list_b = await client.get("/api/v1/watchlist", headers=user_b["headers"])
    assert list_b.status_code == 200
    assert len(list_b.json()) == 0

    # User B tries to delete User A's watchlist item -> 404
    del_resp = await client.delete(f"/api/v1/watchlist/{item_id}", headers=user_b["headers"])
    assert del_resp.status_code == 404

    # User A's item remains intact
    list_a = await client.get("/api/v1/watchlist", headers=user_a["headers"])
    assert len(list_a.json()) == 1


# ==============================================================================
# 6. Cross-User Application Tracking Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_user_application_tracking_isolation(client: AsyncClient):
    """User B cannot view, modify, or delete User A's applications."""
    user_a = await _register_and_login(client, "app_a@test.com")
    user_b = await _register_and_login(client, "app_b@test.com")

    # User A creates an application
    create_resp = await client.post(
        "/api/v1/applications",
        json={
            "university_name": "University of British Columbia",
            "program_name": "Computer Science",
            "status": "applied",
        },
        headers=user_a["headers"],
    )
    assert create_resp.status_code == 201
    app_id = create_resp.json()["id"]

    # User B tries to fetch User A's application -> 404
    get_resp = await client.get(f"/api/v1/applications/{app_id}", headers=user_b["headers"])
    assert get_resp.status_code == 404

    # User B tries to patch User A's application -> 404
    patch_resp = await client.patch(
        f"/api/v1/applications/{app_id}",
        json={"status": "rejected"},
        headers=user_b["headers"],
    )
    assert patch_resp.status_code == 404

    # User B tries to delete User A's application -> 404
    del_resp = await client.delete(f"/api/v1/applications/{app_id}", headers=user_b["headers"])
    assert del_resp.status_code == 404

    # User B listing applications -> empty
    list_b = await client.get("/api/v1/applications", headers=user_b["headers"])
    assert list_b.status_code == 200
    assert len(list_b.json()) == 0


# ==============================================================================
# 7. Cross-User Visa Risk Assessment Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_user_visa_risk_isolation(client: AsyncClient, db_session: AsyncSession):
    """User B cannot view User A's visa risk summary."""
    user_a = await _register_and_login(client, "risk_a@test.com")
    user_b = await _register_and_login(client, "risk_b@test.com")

    # Create profile for User A
    profile_a = Profile(
        user_id=user_a["id"],
        first_name="Alice",
        education_level="bachelor",
        gpa=3.8,
        work_experience=2,
    )
    db_session.add(profile_a)
    await db_session.commit()
    await db_session.refresh(profile_a)

    profile_id_a = profile_a.id

    # User A can view their visa risk summary
    risk_a = await client.get(f"/api/v1/visa-risk/{profile_id_a}", headers=user_a["headers"])
    assert risk_a.status_code == 200
    assert "overall_risk" in risk_a.json()

    # User B tries to view User A's visa risk summary -> 403 Forbidden
    risk_b = await client.get(f"/api/v1/visa-risk/{profile_id_a}", headers=user_b["headers"])
    assert risk_b.status_code == 403
    assert "Not authorized" in risk_b.json()["detail"]
