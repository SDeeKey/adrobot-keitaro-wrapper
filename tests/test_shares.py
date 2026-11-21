from copy import deepcopy

import pytest

from app.shares import ShareError, distribute


def offers(count):
    return [{"offer_id": i, "share": 0, "pinned": False, "removed": False} for i in range(count)]


@pytest.mark.parametrize("count", range(1, 31))
def test_integer_shares_sum_to_100(count):
    rows = offers(count)
    result = distribute(rows)
    assert sum(row["share"] for row in result) == 100
    assert max(row["share"] for row in result) - min(row["share"] for row in result) <= 1
    assert rows == offers(count)  # input is not modified


def test_pins_and_removed_offers():
    rows = offers(4)
    rows[0].update(share=71, pinned=True)
    rows[3].update(removed=True, share=20, pinned=True)
    result = distribute(rows)
    assert [r["share"] for r in result] == [71, 15, 14, 0]
    assert result[0]["pinned"] is True
    assert result[3]["pinned"] is False


@pytest.mark.parametrize("rows", [[], [{"share": 100, "removed": True}],
    [{"share": 60, "pinned": True}, {"share": 50, "pinned": True}],
    [{"share": 70, "pinned": True}], [{"share": -1}], [{"share": 1.5}], [{"share": True}],
])
def test_invalid_distribution(rows):
    original = deepcopy(rows)
    with pytest.raises(ShareError):
        distribute(rows)
    assert rows == original
