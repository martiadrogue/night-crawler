import pytest

HOTELS = {
    "name": "hotels",
    "fields": [
        {"name": "item_id", "is_required": True, "is_unique": True},
        {"name": "name", "type": "string", "pattern": "\\S"},
    ],
}


@pytest.mark.anyio
async def test_members_create_and_list_datasets(client, act_as):
    act_as("member")

    created = await client.post("/api/datasets", json=HOTELS)
    listed = await client.get("/api/datasets")

    assert 201 == created.status_code
    assert ["hotels"] == [item["name"] for item in listed.json()]


@pytest.mark.anyio
async def test_only_admins_edit_or_delete_datasets(client, act_as):
    act_as("member")
    dataset_id = (await client.post("/api/datasets", json=HOTELS)).json()["id"]

    member_update = await client.patch(
        f"/api/datasets/{dataset_id}", json={"name": "lodging"}
    )
    member_delete = await client.delete(f"/api/datasets/{dataset_id}")
    act_as("admin")
    admin_update = await client.patch(
        f"/api/datasets/{dataset_id}", json={"name": "lodging"}
    )
    admin_delete = await client.delete(f"/api/datasets/{dataset_id}")

    assert 403 == member_update.status_code
    assert 403 == member_delete.status_code
    assert "lodging" == admin_update.json()["name"]
    assert 204 == admin_delete.status_code


@pytest.mark.anyio
async def test_a_dataset_field_has_rules_and_defaults(client, act_as):
    act_as("member")

    created = (await client.post("/api/datasets", json=HOTELS)).json()

    assert {
        "name": "name",
        "type": "string",
        "is_required": False,
        "is_unique": False,
        "pattern": "\\S",
    } == created["fields"][1]
    assert "json_columns" not in created
    assert "item_id_from" not in created
