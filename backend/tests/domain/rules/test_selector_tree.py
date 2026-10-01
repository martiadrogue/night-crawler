from night_crawler.domain.model.value_objects import Harvest
from night_crawler.domain.rules.selector_tree import (
    flatten_harvest,
    merge_context_value,
    resolve_context_key,
    split_harvest_by_fields,
)


def test_titles_under_an_iterator_become_lists():
    assert "place_id[]" == resolve_context_key("place_id", True)
    assert "token" == resolve_context_key("token", False)


def test_flattening_turns_loop_titles_into_lists_and_others_into_scalars():
    harvest = Harvest(
        rows=[{"id": "p1", "token": "t"}, {"id": "p2", "token": "t"}],
        array_titles=frozenset({"id"}),
    )

    assert {"id[]": ["p1", "p2"], "token": "t"} == flatten_harvest(harvest)


def test_an_empty_harvest_flattens_to_nothing():
    assert {} == flatten_harvest(Harvest(rows=[{}], array_titles=frozenset()))


def test_crawler_fields_go_to_the_dataset_and_the_rest_to_the_context():
    context_items, dataset_items = split_harvest_by_fields(
        {"name[]": ["A", "B"], "place_id[]": ["1", "2"], "token": "t"},
        {"name", "item_id"},
    )

    assert {"place_id[]": ["1", "2"], "token": "t"} == context_items
    assert {"name[]": ["A", "B"]} == dataset_items


def test_a_first_harvest_replaces_what_the_run_inherited():
    assert ["new"] == merge_context_value(["old"], ["new"], True, True)
    assert "new" == merge_context_value("old", "new", False, True)


def test_later_harvests_extend_lists_and_misses_never_erase():
    assert ["1", "2", "3"] == merge_context_value(["1"], ["2", "3"], True, False)
    assert ["1"] == merge_context_value(["1"], [], True, True)
    assert "old" == merge_context_value("old", None, False, True)
