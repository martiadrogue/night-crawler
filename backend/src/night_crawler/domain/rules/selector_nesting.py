"""How selectors nest: parents before children, and nesting cycles."""


def order_parents_first(
    parent_by_key: dict[str, str | None],
) -> tuple[list[str], list[str]]:
    """Order selectors so each comes right before its own children.

    Depth-first preorder: a parent, its first child's subtree, then its
    next child's, keeping the given order among siblings. A parent that
    is not among the keys counts as none, so its selector is a root.

    Args:
        parent_by_key: Each selector's key mapped to its parent's key.

    Returns:
        The ordered keys, and the keys no root reaches (they nest under
        each other in a cycle), in the given order.
    """
    children_by_parent = _group_by_parent(parent_by_key)
    ordered: list[str] = []
    # Reversed so popping from the end visits siblings in order.
    pending = list(reversed(children_by_parent.get(None, [])))
    while pending:
        key = pending.pop()
        ordered.append(key)
        pending.extend(reversed(children_by_parent.get(key, [])))
    reached = set(ordered)
    return ordered, [key for key in parent_by_key if key not in reached]


def _group_by_parent(
    parent_by_key: dict[str, str | None],
) -> dict[str | None, list[str]]:
    """Group keys by parent; an unknown parent counts as none."""
    children_by_parent: dict[str | None, list[str]] = {}
    for key, parent in parent_by_key.items():
        known_parent = parent if parent in parent_by_key else None
        children_by_parent.setdefault(known_parent, []).append(key)
    return children_by_parent
