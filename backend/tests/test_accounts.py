"""
Account administration (M0.15): create or promote an admin who can then use admin endpoints, and export or
delete an account with everything it owns. Test database only.
"""

import pytest
from sqlalchemy import select

from app.models.chat_message import ChatMessage
from app.models.profile import Profile
from app.models.review import Review
from app.models.user import User
from app.models.user_document import UserDocument
from app.services import accounts
from app.services.accounts import AccountError

GOOD_PASSWORD = "correct-horse-battery-9"


async def make_user(db, email, password="$2b$12$" + "x" * 53, admin=False):
    user = User(email=email, hashed_password=password, is_admin=admin)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------- admins

@pytest.mark.asyncio
async def test_a_new_admin_can_log_in_and_use_admin_endpoints(client, db_session):
    user, outcome = await accounts.create_or_promote_admin(db_session, "Owner@Example.com", GOOD_PASSWORD)
    assert outcome == "created" and user.email == "owner@example.com" and user.is_admin
    assert user.hashed_password.startswith("$2") and GOOD_PASSWORD not in user.hashed_password

    login = await client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": GOOD_PASSWORD})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/v1/admin/traces", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_a_normal_user_is_refused_admin_endpoints(client):
    token = (await client.post("/api/v1/auth/signup", json={"email": "plain@example.com",
                                                             "password": "testpass123"})).json()["access_token"]
    response = await client.get("/api/v1/admin/traces", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_promoting_keeps_the_existing_password(db_session):
    existing = await make_user(db_session, "staff@example.com")
    old_hash = existing.hashed_password
    user, outcome = await accounts.create_or_promote_admin(db_session, "staff@example.com")
    assert outcome == "promoted" and user.is_admin and user.hashed_password == old_hash
    _, again = await accounts.create_or_promote_admin(db_session, "staff@example.com")
    assert again == "already_admin"


@pytest.mark.asyncio
@pytest.mark.parametrize("password,message", [
    ("short1!", "at least 12"),
    ("ownerownerowner1", "email name"),
    ("abcdefghijklmnop", "digits or symbols"),
])
async def test_weak_admin_passwords_are_refused(db_session, password, message):
    with pytest.raises(AccountError, match=message):
        await accounts.create_or_promote_admin(db_session, "owner@example.com", password)
    assert (await db_session.execute(select(User))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_new_admin_needs_a_password(db_session):
    with pytest.raises(AccountError, match="needs a password"):
        await accounts.create_or_promote_admin(db_session, "new@example.com")


@pytest.mark.asyncio
async def test_accounts_with_non_bcrypt_passwords_are_found(db_session):
    await make_user(db_session, "demo@pendu.app", password="demo-plain-text")
    await make_user(db_session, "real@example.com")
    assert await accounts.accounts_without_bcrypt(db_session) == ["demo@pendu.app"]


# ---------------------------------------------------------------- export and delete

@pytest.mark.asyncio
async def test_every_reference_to_users_is_known():
    refs = {f"{t.name}.{c.name}": owned for t, c, owned in accounts.user_references()}
    assert refs["chat_messages.user_id"] is True and refs["profiles.user_id"] is True
    assert refs["reviews.reviewer_id"] is False and refs["user_documents.reviewed_by"] is False  # someone else's row


@pytest.mark.asyncio
async def test_export_has_the_users_data_but_not_the_password_hash(db_session):
    user = await make_user(db_session, "demo@pendu.app")
    db_session.add_all([ChatMessage(user_id=user.id, role="user", content="Hello"), Profile(user_id=user.id)])
    await db_session.commit()

    export = await accounts.export_user_data(db_session, user)
    assert "hashed_password" not in export["account"] and export["account"]["email"] == "demo@pendu.app"
    assert [m["content"] for m in export["tables"]["chat_messages"]] == ["Hello"]
    assert len(export["tables"]["profiles"]) == 1


@pytest.mark.asyncio
async def test_delete_removes_owned_data_and_clears_references_in_other_peoples_rows(db_session, tmp_path):
    demo = await make_user(db_session, "demo@pendu.app")
    other = await make_user(db_session, "other@example.com")
    db_session.add_all([ChatMessage(user_id=demo.id, role="user", content="Hello"), Profile(user_id=demo.id),
                        ChatMessage(user_id=other.id, role="user", content="Keep me")])
    other_doc = UserDocument(user_id=other.id, document_type="sop", content="Other's SOP", reviewed_by=demo.id)
    db_session.add(other_doc)
    await db_session.commit()
    db_session.add(Review(user_id=other.id, document_id=other_doc.id, reviewer_id=demo.id))
    await db_session.commit()
    (tmp_path / str(demo.id)).mkdir()
    (tmp_path / str(demo.id) / "passport.pdf").write_bytes(b"%PDF")

    affected = await accounts.delete_user(db_session, demo, tmp_path)

    assert affected["chat_messages.user_id"] == 1 and affected["profiles.user_id"] == 1
    assert affected["reviews.reviewer_id (cleared)"] == 1 and affected["user_documents.reviewed_by (cleared)"] == 1
    assert not (tmp_path / str(demo.id)).exists()
    emails = (await db_session.execute(select(User.email))).scalars().all()
    assert emails == ["other@example.com"]
    kept = (await db_session.execute(select(ChatMessage.content))).scalars().all()
    assert kept == ["Keep me"]
    review = (await db_session.execute(select(Review))).scalar_one()
    assert review.user_id == other.id and review.reviewer_id is None  # other person's row kept, reference cleared


@pytest.mark.asyncio
async def test_summary_counts_what_would_go(db_session):
    demo = await make_user(db_session, "demo@pendu.app")
    db_session.add_all([ChatMessage(user_id=demo.id, role="user", content=str(i)) for i in range(3)])
    await db_session.commit()
    assert await accounts.data_summary(db_session, demo.id) == {"chat_messages.user_id": 3}
