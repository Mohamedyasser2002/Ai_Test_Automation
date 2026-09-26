from src.models.state import upsert_by_id


def test_upsert_by_id_replaces_retry_result_without_mutating_input():
    previous = [{"test_id": "test-1", "status": "failed"}]
    retry = [{"test_id": "test-1", "status": "passed"}]

    merged = upsert_by_id(previous, retry)

    assert merged == [{"test_id": "test-1", "status": "passed"}]
    assert previous == [{"test_id": "test-1", "status": "failed"}]


def test_upsert_by_id_keeps_distinct_entries():
    previous = [{"id": "test-1"}]

    merged = upsert_by_id(previous, [{"id": "test-2"}])

    assert merged == [{"id": "test-1"}, {"id": "test-2"}]
