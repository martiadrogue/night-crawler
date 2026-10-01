import pytest


@pytest.mark.anyio
async def test_members_create_and_list_sources(client, act_as):
    act_as("member")

    created = await client.post("/api/sources", json={"name": "OpenTable"})
    listed = await client.get("/api/sources")

    assert 201 == created.status_code
    assert ["OpenTable"] == [item["name"] for item in listed.json()]


@pytest.mark.anyio
async def test_only_admins_edit_or_delete_sources(client, act_as):
    act_as("member")
    source_id = (await client.post("/api/sources", json={"name": "OpenTable"})).json()[
        "id"
    ]

    member_update = await client.patch(
        f"/api/sources/{source_id}", json={"name": "Open Table"}
    )
    member_delete = await client.delete(f"/api/sources/{source_id}")
    act_as("admin")
    admin_update = await client.patch(
        f"/api/sources/{source_id}", json={"name": "Open Table"}
    )
    admin_delete = await client.delete(f"/api/sources/{source_id}")

    assert 403 == member_update.status_code
    assert 403 == member_delete.status_code
    assert "Open Table" == admin_update.json()["name"]
    assert 204 == admin_delete.status_code
