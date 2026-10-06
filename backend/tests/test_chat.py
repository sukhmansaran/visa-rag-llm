import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_answer_no_auth(client: AsyncClient):
    """Test chat endpoint without authentication."""
    response = await client.post(
        "/api/v1/chat/answer",
        json={"query": "What is a student visa?"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_chat_answer_with_auth(client: AsyncClient):
    """Test chat endpoint with authentication."""
    # Signup first
    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = signup_response.json()["access_token"]
    
    # Chat query
    response = await client.post(
        "/api/v1/chat/answer",
        json={
            "query": "What documents do I need for Canada student visa?",
            "country": "Canada",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Validate response structure
    assert "advice_text" in data
    assert "sources" in data
    assert "confidence" in data
    assert "escalate" in data
    assert isinstance(data["sources"], list)
    assert isinstance(data["confidence"], (int, float))
    assert isinstance(data["escalate"], bool)


@pytest.mark.asyncio
async def test_chat_history(client: AsyncClient):
    """Test chat history retrieval."""
    # Signup
    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = signup_response.json()["access_token"]
    
    # Send a message
    await client.post(
        "/api/v1/chat/answer",
        json={"query": "Test query"},
        headers={"Authorization": f"Bearer {token}"},
    )
    
    # Get history
    response = await client.get(
        "/api/v1/chat/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "messages" in data
    assert "total" in data
    assert len(data["messages"]) >= 2  # User + assistant messages
    
    # Check message structure
    msg = data["messages"][0]
    assert "role" in msg
    assert "content" in msg
    assert msg["role"] in ["user", "assistant"]


@pytest.mark.asyncio
async def test_chat_with_country_filter(client: AsyncClient):
    """Test chat with country filtering."""
    # Signup
    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = signup_response.json()["access_token"]
    
    # Query with country
    response = await client.post(
        "/api/v1/chat/answer",
        json={
            "query": "Student visa requirements",
            "country": "Canada",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should have metadata about country filter
    if "metadata" in data:
        assert isinstance(data["metadata"], dict)
