from bot import config
from bot.telegram.delivery import UPLOAD_BUDGET, _chunks


def test_chunks_hold_up_to_ten_items():
    assert [len(c) for c in _chunks(list(range(23)))] == [10, 10, 3]


def test_chunks_of_uploads_fit_the_request_limit():
    sizes = [20 * config.MB, 20 * config.MB, 20 * config.MB, 1 * config.MB]
    chunks = _chunks(["a", "b", "c", "d"], sizes)
    assert chunks == [["a", "b"], ["c", "d"]]
    assert all(sum(sizes["abcd".index(x)] for x in chunk) <= UPLOAD_BUDGET for chunk in chunks)


def test_an_oversized_item_still_goes_alone():
    assert _chunks(["a", "b"], [60 * config.MB, 1]) == [["a"], ["b"]]
