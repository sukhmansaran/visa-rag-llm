"""M6.6 (D7): a user can get a copy of their data and delete their account from the app. Deletion needs the password
and the word DELETE, removes every row tied to the user, ends the session, and leaves other users untouched."""

import pytest
from sqlalchemy import func, select

from app.models.user import User
from app.services import accounts

PASSWORD = "testpass123"
API = "/api/v1/account"


async def signed_up(client, email):
    tokens = (await client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}, tokens


async def with_data(client, headers):
    """A profile, a tracked application and a chat message of the user's own."""
    await client.put("/api/v1/profile", headers=headers, json={"first_name": "Asha", "education_level": "bachelor"})
    await client.post("/api/v1/applications", headers=headers, json={"university_name": "UBC", "program_name": "MSc AI"})


async def user_id(db, email):
    return (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_export_holds_the_users_rows_and_never_the_password_hash(client, db_session):
    headers, _ = await signed_up(client, "export-me@example.com")
    await with_data(client, headers)
    other, _ = await signed_up(client, "export-other@example.com")
    await client.post("/api/v1/applications", headers=other, json={"university_name": "McGill", "program_name": "MSc"})

    export = (await client.get(f"{API}/export", headers=headers)).json()
    assert export["account"]["email"] == "export-me@example.com"
    assert "hashed_password" not in str(export) and "$2b$" not in str(export)
    assert export["tables"]["profiles"][0]["first_name"] == "Asha"
    assert [a["university_name"] for a in export["tables"]["application_trackers"]] == ["UBC"]  # not the other user's
    assert (await client.get(f"{API}/export")).status_code in (401, 403)


@pytest.mark.asyncio
async def test_deleting_removes_every_row_tied_to_the_user_and_ends_the_session(client, db_session):
    headers, tokens = await signed_up(client, "delete-me@example.com")
    await with_data(client, headers)
    other, _ = await signed_up(client, "keep-me@example.com")
    await with_data(client, other)
    uid = await user_id(db_session, "delete-me@example.com")
    assert await accounts.data_summary(db_session, uid)  # there is something to delete

    done = await client.post(f"{API}/delete", headers=headers, json={"password": PASSWORD, "confirm": "DELETE"})
    assert done.status_code == 200 and done.json()["deleted"] is True and done.json()["rows_removed"] >= 2

    assert await user_id(db_session, "delete-me@example.com") is None
    assert await accounts.data_summary(db_session, uid) == {}  # no table still references the user
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 404  # the old token finds no user
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"email": "delete-me@example.com", "password": PASSWORD})
            ).status_code == 401

    kept = await user_id(db_session, "keep-me@example.com")
    assert len(await accounts.data_summary(db_session, kept)) >= 2  # the other user's rows are all still there
    assert len((await client.get("/api/v1/applications", headers=other)).json()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [
    ({"password": "wrong-password-1", "confirm": "DELETE"}, 403),
    ({"password": PASSWORD, "confirm": "delete"}, 400),
    ({"password": PASSWORD, "confirm": ""}, 400),
    ({"password": PASSWORD}, 422),
    ({"confirm": "DELETE"}, 422),
])
async def test_without_the_password_and_the_word_nothing_is_deleted(client, db_session, body, status):
    email = f"careful-{status}-{len(str(body))}@example.com"
    headers, _ = await signed_up(client, email)
    await with_data(client, headers)
    assert (await client.post(f"{API}/delete", headers=headers, json=body)).status_code == status
    assert await user_id(db_session, email) is not None
    assert len((await client.get("/api/v1/applications", headers=headers)).json()) == 1


@pytest.mark.asyncio
async def test_nobody_else_can_delete_an_account_and_admins_use_the_script(client, db_session):
    headers, _ = await signed_up(client, "admin-self@example.com")
    assert (await client.post(f"{API}/delete", json={"password": PASSWORD, "confirm": "DELETE"})).status_code in (401, 403)

    user = (await db_session.execute(select(User).where(User.email == "admin-self@example.com"))).scalar_one()
    user.is_admin = True
    await db_session.commit()
    refused = await client.post(f"{API}/delete", headers=headers, json={"password": PASSWORD, "confirm": "DELETE"})
    assert refused.status_code == 409 and "delete_account.py" in refused.json()["detail"]
    assert (await db_session.execute(select(func.count()).select_from(User))).scalar() == 1
