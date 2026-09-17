"""The daily scheduler and the artifact fingerprint that guards a persisted model."""

from datetime import UTC, datetime, time

import pytest

from wp6_data.shared.artifacts import FINGERPRINT_LENGTH, fingerprint
from wp6_data.shared.scheduling import parse_daily_time, seconds_until

HOUR = 3600


class TestParseDailyTime:
    def test_unset_means_no_schedule(self):
        """Scheduling is a deployment concern: a dev machine left running
        overnight must not quietly start retraining models."""
        assert parse_daily_time("") is None
        assert parse_daily_time("   ") is None

    def test_a_time_of_day_is_read_as_utc(self):
        parsed = parse_daily_time("03:30")

        assert parsed == time(3, 30, tzinfo=UTC)

    def test_an_hour_alone_is_enough(self):
        assert parse_daily_time("3") == time(3, 0, tzinfo=UTC)

    def test_nonsense_disables_rather_than_crashes(self):
        """A typo in a Helm value must not take down startup."""
        assert parse_daily_time("not a time") is None


class TestSecondsUntil:
    def test_later_today(self):
        now = datetime(2026, 9, 17, 1, 0, tzinfo=UTC)

        assert seconds_until(time(3, 0, tzinfo=UTC), now=now) == 2 * HOUR

    def test_already_past_means_tomorrow(self):
        now = datetime(2026, 9, 17, 5, 0, tzinfo=UTC)

        assert seconds_until(time(3, 0, tzinfo=UTC), now=now) == 22 * HOUR

    def test_exactly_now_waits_a_full_day_rather_than_firing_twice(self):
        """A zero-length sleep would run the job again immediately."""
        now = datetime(2026, 9, 17, 3, 0, tzinfo=UTC)

        assert seconds_until(time(3, 0, tzinfo=UTC), now=now) == 24 * HOUR


class TestFingerprint:
    def test_same_payload_same_fingerprint(self):
        assert fingerprint({"a": 1, "b": [2, 3]}) == fingerprint({"b": [2, 3], "a": 1})

    def test_a_changed_value_changes_it(self):
        assert fingerprint({"horizons": [1, 2]}) != fingerprint({"horizons": [1, 2, 3]})

    def test_sequence_order_is_part_of_the_contract(self):
        """Feature order matters to a fitted model — the same names in a
        different order is a different contract, not the same one."""
        assert fingerprint(["temp", "hum"]) != fingerprint(["hum", "temp"])

    def test_set_order_is_not(self):
        assert fingerprint({frozenset({1, 2})}) == fingerprint({frozenset({2, 1})})

    def test_it_is_stable_across_processes(self):
        """`hash()` is randomised per interpreter, so a fingerprint built on it
        would differ every restart and refit the model every time."""
        import subprocess
        import sys

        out = subprocess.run(
            [sys.executable, "-c",
             "from wp6_data.shared.artifacts import fingerprint;"
             "print(fingerprint({'a': [1, 'x']}))"],
            capture_output=True, text=True, check=True,
        )

        assert out.stdout.strip() == fingerprint({"a": [1, "x"]})

    def test_it_is_short_enough_to_read_in_a_log(self):
        assert len(fingerprint("anything")) == FINGERPRINT_LENGTH


@pytest.mark.asyncio
async def test_run_daily_survives_a_failing_job(monkeypatch):
    """A job that raises must not wedge the schedule — the rhythm resumes."""
    import asyncio

    from wp6_data.shared import scheduling

    calls = []

    async def job():
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduling, "RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(scheduling, "seconds_until", lambda *a, **k: 0)

    task = asyncio.create_task(
        scheduling.run_daily(job, at=time(3, tzinfo=UTC), name="test")
    )
    await asyncio.sleep(0.05)
    task.cancel()

    assert len(calls) > 1
