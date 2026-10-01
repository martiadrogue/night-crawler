from night_crawler.domain.rules.context_entries import (
    context_to_entries,
    entries_to_context,
    to_primitive,
)


def test_list_keys_become_one_entry_per_element_with_its_position():
    entries = context_to_entries({"parish[]": ["Canillo", "Encamp"], "token": "t"})

    assert [
        ("parish[]", 0, "Canillo"),
        ("parish[]", 1, "Encamp"),
        ("token", None, "t"),
    ] == entries


def test_entries_rebuild_the_context_in_position_order():
    context = entries_to_context(
        [("parish[]", 1, "Encamp"), ("token", None, "t"), ("parish[]", 0, "Canillo")]
    )

    assert {"parish[]": ["Canillo", "Encamp"], "token": "t"} == context


def test_an_empty_list_key_keeps_no_entries():
    assert [] == context_to_entries({"parish[]": []})


def test_objects_and_lists_are_stored_as_json_text():
    assert '{"lat": 42.5}' == to_primitive({"lat": 42.5})
    assert '["bar", "cafe"]' == to_primitive(["bar", "cafe"])
    assert 7 == to_primitive(7)
    assert None is to_primitive(None)
