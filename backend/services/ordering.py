"""Ordenamiento para presentación."""

import re

_NUM_RE = re.compile(r"\d+")


def question_sort_key(q_id: str):
    """Orden natural de un `q_id`: primero las `cp`, luego las `p`, luego el resto."""
    if q_id.startswith("cp"):
        rank = 0
    elif q_id.startswith("p"):
        # TODO: Derived variables can start with p, but should have rank = 2
        rank = 1
    else:
        rank = 2
    nums = tuple(int(n) for n in _NUM_RE.findall(q_id))
    return (rank, nums, q_id)


def ordered_question_ids(all_ids: list[str]) -> list[str]:
    """Ordena los question_ids por `question_sort_key`."""
    return sorted(all_ids, key=question_sort_key)


def order_by_desired(items, get_label, desired):
    """Sort `items` so any item whose label appears in `desired` is placed in
    that exact order; everything else is appended alphabetically."""
    if not desired:
        return sorted(items, key=lambda it: get_label(it).lower())
    rank = {label: i for i, label in enumerate(desired)}
    return sorted(
        items,
        key=lambda it: (rank.get(get_label(it), 10_000), get_label(it).lower()),
    )
