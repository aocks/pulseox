"""Tests for the optional `grace_period` field of PulseOxSpec.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pydantic

from pulseox.specs import PulseOxSpec


def make_spec(**kwargs):
    """Helper to build a PulseOxSpec with reasonable defaults."""
    defaults = {
        'owner': 'testowner',
        'repo': 'testrepo',
        'path': 'example.md',
        'schedule': timedelta(minutes=1),
    }
    defaults.update(kwargs)
    return PulseOxSpec(**defaults)


def ago(**kwargs):
    """Return an ISO timestamp `kwargs` (timedelta args) in the past."""
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat()


class TestGracePeriodTimedelta:
    """Grace period behavior with timedelta schedules."""

    def test_no_grace_period_defaults_to_old_behavior(self):
        spec = make_spec(schedule=timedelta(minutes=1))
        assert spec.grace_period is None
        assert spec.is_within_schedule(updated_str=ago(seconds=30))
        assert not spec.is_within_schedule(updated_str=ago(minutes=2))

    def test_grace_period_extends_schedule(self):
        spec = make_spec(schedule=timedelta(minutes=1),
                         grace_period=timedelta(minutes=5))
        # 2 minutes late relative to schedule, but within 5 minute grace
        assert spec.is_within_schedule(updated_str=ago(minutes=3))
        # Past schedule plus grace period
        assert not spec.is_within_schedule(updated_str=ago(minutes=7))

    def test_short_grace_period_still_complains(self):
        spec = make_spec(schedule=timedelta(minutes=1),
                         grace_period=timedelta(seconds=10))
        assert not spec.is_within_schedule(updated_str=ago(minutes=2))

    def test_zero_grace_period_same_as_none(self):
        spec_none = make_spec(schedule=timedelta(minutes=1))
        spec_zero = make_spec(schedule=timedelta(minutes=1),
                              grace_period=timedelta(0))
        for updated_str in (ago(seconds=30), ago(minutes=2)):
            assert (spec_none.is_within_schedule(updated_str=updated_str)
                    == spec_zero.is_within_schedule(updated_str=updated_str))

    def test_grace_period_argument_overrides_field(self):
        spec = make_spec(schedule=timedelta(minutes=1))
        updated_str = ago(minutes=3)
        assert not spec.is_within_schedule(updated_str=updated_str)
        assert spec.is_within_schedule(
            updated_str=updated_str, grace_period=timedelta(minutes=10))

    def test_no_update_still_missing_even_with_grace(self):
        spec = make_spec(schedule=timedelta(minutes=1),
                         grace_period=timedelta(days=365))
        spec.updated = None
        assert not spec.is_within_schedule()


class TestGracePeriodCron:
    """Grace period behavior with cron string schedules."""

    def test_cron_without_grace_period(self):
        # Runs every minute; updated 3 minutes ago is past next run
        spec = make_spec(schedule='* * * * *')
        assert not spec.is_within_schedule(updated_str=ago(minutes=3))

    def test_cron_with_grace_period(self):
        spec = make_spec(schedule='* * * * *',
                         grace_period=timedelta(minutes=10))
        # 3 minutes since update is within the 10 minute grace period
        assert spec.is_within_schedule(updated_str=ago(minutes=3))
        # Well beyond next run plus grace period
        assert not spec.is_within_schedule(updated_str=ago(minutes=20))


class TestGracePeriodValidationAndSerialization:

    def test_negative_grace_period_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            make_spec(grace_period=timedelta(minutes=-1))

    def test_round_trip_serialization(self):
        # Dashboards persist specs as JSON, so grace_period must survive
        # a serialization round trip.
        spec = make_spec(grace_period=timedelta(minutes=5))
        parsed = PulseOxSpec.model_validate_json(spec.model_dump_json())
        assert parsed.grace_period == timedelta(minutes=5)
        assert parsed == spec

    def test_round_trip_with_none_grace_period(self):
        spec = make_spec()
        parsed = PulseOxSpec.model_validate_json(spec.model_dump_json())
        assert parsed.grace_period is None
        assert parsed == spec
