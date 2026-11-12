"""M6.4: the application tracker page works on real rows; the API refuses values the page can't show."""

import pytest

URL = "/api/v1/applications"


async def signed_in(client, email):
    token = (await client.post("/api/v1/auth/signup", json={"email": email, "password": "testpass123"})).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_add_list_update_and_delete(client):
    headers = await signed_in(client, "tracker-a@example.com")
    assert (await client.get(URL, headers=headers)).json() == []
    later = await client.post(URL, headers=headers, json={
        "university_name": "McGill University", "program_name": "MSc Data Science", "deadline": "2027-03-01T00:00:00"})
    sooner = await client.post(URL, headers=headers, json={
        "university_name": "University of Toronto", "program_name": "MSc CS", "deadline": "2027-01-15T00:00:00"})
    undated = await client.post(URL, headers=headers, json={"university_name": "UBC", "program_name": "MSc AI"})
    assert [r.status_code for r in (later, sooner, undated)] == [201, 201, 201] and undated.json()["status"] == "planning"
    names = [a["university_name"] for a in (await client.get(URL, headers=headers)).json()]
    assert names == ["University of Toronto", "McGill University", "UBC"]  # nearest deadline first, undated last

    changed = await client.patch(f"{URL}/{sooner.json()['id']}", headers=headers, json={"status": "submitted"})
    assert changed.status_code == 200 and changed.json()["status"] == "submitted"
    assert changed.json()["program_name"] == "MSc CS"  # other fields are left alone
    assert (await client.delete(f"{URL}/{undated.json()['id']}", headers=headers)).status_code == 204
    assert len((await client.get(URL, headers=headers)).json()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"university_name": "UBC", "program_name": "MSc AI", "status": "approved!!"},  # not a stage the page knows
    {"university_name": "", "program_name": "MSc AI"},
    {"university_name": "U" * 201, "program_name": "MSc AI"},
    {"university_name": "UBC", "program_name": "MSc AI", "notes": "n" * 2001},
])
async def test_values_the_page_cannot_show_are_refused(client, body):
    headers = await signed_in(client, f"tracker-{abs(hash(str(body))) % 10**8}@example.com")
    assert (await client.post(URL, headers=headers, json=body)).status_code == 422
    assert (await client.get(URL, headers=headers)).json() == []


@pytest.mark.asyncio
async def test_an_update_cannot_set_an_unknown_stage(client):
    headers = await signed_in(client, "tracker-b@example.com")
    row = (await client.post(URL, headers=headers, json={"university_name": "UBC", "program_name": "MSc AI"})).json()
    assert (await client.patch(f"{URL}/{row['id']}", headers=headers, json={"status": "done"})).status_code == 422
    assert (await client.get(f"{URL}/{row['id']}", headers=headers)).json()["status"] == "planning"


@pytest.mark.asyncio
async def test_the_sop_page_can_list_drafts_without_a_redirect(client):
    # the frontend proxy strips a trailing slash, so /documents must answer directly (a redirect would loop)
    headers = await signed_in(client, "tracker-docs@example.com")
    for path in ("/api/v1/documents?document_type=sop", "/api/v1/documents/?document_type=sop"):
        r = await client.get(path, headers=headers)
        assert r.status_code == 200 and r.json() == []
