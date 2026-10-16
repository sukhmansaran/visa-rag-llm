"""
SOP endpoint failures map to clear responses without leaking internal error text (2026-10-15 review, B4).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import AIServiceUnavailableError
from app.services.sop_generator import SOPGenerationError

BODY = {"university": "University of Toronto", "program": "MSc Computer Science"}


async def user_with_profile(client, email):
    token = (await client.post("/api/v1/auth/signup", json={"email": email, "password": "testpass123"})).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    await client.put("/api/v1/profile", json={"first_name": "A", "education_level": "bachelor", "field_of_study": "CS"},
                     headers=headers)
    return headers


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status,message", [
    (SOPGenerationError("draft too short (26 words)"), 502, "could not be completed"),
    (AIServiceUnavailableError("queue full", details={"reason": "queue_timeout"}), 503, "busy or unavailable"),
    (RuntimeError("psycopg.OperationalError: password authentication failed for user postgres"), 500, "Failed to generate"),
])
async def test_failures_are_clear_and_leak_nothing(client, error, status, message):
    headers = await user_with_profile(client, f"sop-{status}@example.com")
    with patch("app.api.v1.documents.generate_sop", new_callable=AsyncMock, side_effect=error):
        r = await client.post("/api/v1/documents/sop/generate", json=BODY, headers=headers)
    assert r.status_code == status
    assert message in r.json()["detail"]
    assert str(error) not in r.text and "psycopg" not in r.text  # internal details stay in the logs
