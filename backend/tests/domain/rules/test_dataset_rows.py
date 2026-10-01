from night_crawler.domain.model.value_objects import Harvest
from night_crawler.domain.rules.dataset_rows import build_csv, project_rows


def test_rows_keep_only_the_crawlers_fields():
    harvest = Harvest(
        rows=[{"item_id": "p1", "name": "Casa", "categories": ["bar"], "token": "t"}],
        array_titles=frozenset(),
    )

    rows = project_rows(harvest, ["item_id", "name", "categories"])

    assert [{"item_id": "p1", "name": "Casa", "categories": ["bar"]}] == rows


def test_rows_missing_a_required_field_are_kept_for_validation():
    harvest = Harvest(
        rows=[{"item_id": "p1"}, {"item_id": "p2", "name": "Nou"}],
        array_titles=frozenset({"name"}),
    )

    rows = project_rows(harvest, ["item_id", "name"])

    assert [{"item_id": "p1", "name": None}, {"item_id": "p2", "name": "Nou"}] == rows


def test_csv_follows_the_field_order_and_json_encodes_lists():
    csv_text = build_csv(
        ["item_id", "name", "categories"],
        [{"item_id": "p1", "name": 'Bar "Nou"', "categories": ["bar", "cafe"]}],
    )

    assert (
        'item_id,name,categories\r\np1,"Bar ""Nou""","[""bar"", ""cafe""]"\r\n'
        == csv_text
    )


def test_missing_values_are_empty_cells():
    assert "item_id,name\r\np1,\r\n" == build_csv(
        ["item_id", "name"], [{"item_id": "p1", "name": None}]
    )


def test_a_menu_row_keeps_the_item_id_its_selectors_harvested():
    harvest = Harvest(
        rows=[{"item_id": "v1", "venue_item_id": "v1", "name": "Soup"}],
        array_titles=frozenset(),
    )

    rows = project_rows(harvest, ["item_id", "venue_item_id", "name"])

    assert [{"item_id": "v1", "venue_item_id": "v1", "name": "Soup"}] == rows


def test_a_missing_item_id_is_never_filled_from_another_field():
    harvest = Harvest(
        rows=[{"venue_item_id": "v1", "name": "Soup"}], array_titles=frozenset()
    )

    rows = project_rows(harvest, ["item_id", "venue_item_id", "name"])

    assert [{"item_id": None, "venue_item_id": "v1", "name": "Soup"}] == rows


def test_text_is_written_as_is_and_objects_as_json():
    csv_text = build_csv(
        ["item_id", "about", "location"],
        [{"item_id": "p1", "about": "x", "location": {"lat": 1}}],
    )

    assert 'item_id,about,location\r\np1,x,"{""lat"": 1}"\r\n' == csv_text
