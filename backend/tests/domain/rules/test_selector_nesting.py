from night_crawler.domain.rules.selector_nesting import order_parents_first


def test_order_parents_first_walks_each_subtree_in_turn():
    parent_by_key = {"leaf": "list", "list": None, "other": None, "deep": "leaf"}

    ordered, cyclic = order_parents_first(parent_by_key)

    assert ["list", "leaf", "deep", "other"] == ordered
    assert [] == cyclic


def test_order_parents_first_treats_an_unknown_parent_as_none():
    ordered, cyclic = order_parents_first({"orphan": "gone"})

    assert ["orphan"] == ordered
    assert [] == cyclic


def test_order_parents_first_reports_a_cycle():
    parent_by_key = {"root": None, "a": "b", "b": "a", "self": "self"}

    ordered, cyclic = order_parents_first(parent_by_key)

    assert ["root"] == ordered
    assert ["a", "b", "self"] == cyclic
