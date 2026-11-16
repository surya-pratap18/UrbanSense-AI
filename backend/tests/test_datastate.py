from datetime import datetime, timedelta, timezone

from app.core.datastate import DataState, classify

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def ago(m):
    return NOW - timedelta(minutes=m)


def test_unavailable_when_never_seen():
    assert classify(None, 15, NOW) == DataState.UNAVAILABLE


def test_live_within_grace():
    assert classify(ago(20), 15, NOW) == DataState.LIVE      # 20 <= 22.5


def test_delayed():
    assert classify(ago(60), 15, NOW) == DataState.DELAYED   # 22.5 < 60 <= 90


def test_stale_is_never_live():
    assert classify(ago(300), 15, NOW) == DataState.HISTORICAL


def test_simulated_always_wins():
    assert classify(ago(1), 15, NOW, simulated=True) == DataState.SIMULATED


def test_manual_source_without_cadence_is_historical():
    assert classify(ago(1), None, NOW) == DataState.HISTORICAL


def test_naive_datetime_treated_as_utc():
    assert classify(datetime(2026, 11, 14, 11, 50), 15, NOW) == DataState.LIVE
