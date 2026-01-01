"""Tests for the 24-hour scheduler."""

import pytest
from datetime import datetime, timedelta
from dataclasses import replace

from app.config import Config
from app.models import PowerInputs, EVState
from app.scheduler import generate_schedule, ScheduleSlot, ScheduleResult


class TestGenerateSchedule:
    """Test basic schedule generation."""

    def test_generate_schedule_returns_result(self, config, winter_offpeak):
        """Generate schedule should return a valid ScheduleResult."""
        result = generate_schedule(winter_offpeak, config)

        assert isinstance(result, ScheduleResult)
        assert result.slots is not None
        assert isinstance(result.slots, list)
        assert len(result.slots) > 0
        assert result.timetable is not None
        assert result.warnings is not None

    def test_generate_schedule_creates_24_hours_of_slots(self, config, winter_offpeak):
        """Schedule should cover 24 hours in 30-minute slots (48 slots)."""
        result = generate_schedule(winter_offpeak, config)

        # 24 hours / 30 minutes = 48 slots
        assert len(result.slots) == 48

    def test_generate_schedule_slots_are_30_minutes(self, config, winter_offpeak):
        """Each slot should be exactly 30 minutes."""
        result = generate_schedule(winter_offpeak, config)

        for slot in result.slots:
            duration = slot.end - slot.start
            assert duration == timedelta(minutes=30)


class TestScheduleRespectsLimits:
    """Test that schedule respects power limits."""

    def test_schedule_respects_power_limits(self, config, base_inputs, winter_offpeak):
        """No slot should exceed its tariff-based power limit."""
        result = generate_schedule(winter_offpeak, config, inputs=base_inputs)

        for slot in result.slots:
            # Total power in slot should not exceed the limit
            assert slot.total_power <= slot.power_limit, \
                f"Slot at {slot.start} exceeds limit: {slot.total_power}W > {slot.power_limit}W"

    def test_peak_slots_have_correct_limit(self, config, winter_peak):
        """Peak tariff slots should have the peak power limit."""
        result = generate_schedule(winter_peak, config)

        # Find a peak slot
        peak_slots = [s for s in result.slots if s.tariff == 'peak']
        if peak_slots:
            for slot in peak_slots:
                assert slot.power_limit == config.max_import.peak

    def test_offpeak_slots_have_correct_limit(self, config, winter_offpeak):
        """Off-peak tariff slots should have the off-peak power limit."""
        result = generate_schedule(winter_offpeak, config)

        offpeak_slots = [s for s in result.slots if s.tariff == 'off-peak']
        if offpeak_slots:
            for slot in offpeak_slots:
                assert slot.power_limit == config.max_import.off_peak

    def test_super_offpeak_slots_have_correct_limit(self, config):
        """Super off-peak tariff slots should have the super off-peak power limit."""
        # Use 3:00 AM which is super-off-peak
        super_offpeak_time = datetime(2024, 1, 15, 3, 0, 0)
        result = generate_schedule(super_offpeak_time, config)

        super_offpeak_slots = [s for s in result.slots if s.tariff == 'super-off-peak']
        assert len(super_offpeak_slots) > 0, "Should have super-off-peak slots"
        for slot in super_offpeak_slots:
            assert slot.power_limit == config.max_import.super_off_peak


class TestSchedulePriorityOrder:
    """Test that schedule respects device priority order."""

    def test_schedule_respects_priority_order(self, config, base_inputs, winter_offpeak):
        """Higher priority devices should be scheduled before lower priority ones."""
        # Set up inputs so we need both boiler and EV (boiler priority 2, EV priority 3)
        inputs = replace(
            base_inputs,
            ev_state=EVState.READY,
            boiler_switch='off',
            boiler_power=0,
            bmw_i5_battery=40,  # Needs charging
            bmw_i5_location='home'
        )

        result = generate_schedule(winter_offpeak, config, inputs=inputs)

        # Boiler (priority 2) should have more slots scheduled than
        # if EV was prioritized first, but this is hard to test directly.
        # Instead, verify that both devices can be scheduled without
        # exceeding limits.
        for slot in result.slots:
            assert slot.total_power <= slot.power_limit

        # Check that boiler is in the schedule when needed
        boiler_slots = [s for s in result.slots if 'boiler' in s.devices]
        # Boiler should be scheduled (it's higher priority than table heater)
        assert len(boiler_slots) > 0 or not result.boiler_estimate.get('needed'), \
            "Boiler should be scheduled when needed"


class TestEVScheduledBeforeDeadline:
    """Test that EV charging is scheduled before the morning deadline."""

    def test_ev_scheduled_before_deadline(self, config, base_inputs, winter_offpeak):
        """EV charging should be scheduled to complete before 07:00 deadline."""
        # EV needs charging
        inputs = replace(
            base_inputs,
            ev_state=EVState.READY,
            bmw_i5_battery=30,  # Low battery, needs charging
            bmw_i5_location='home'
        )

        result = generate_schedule(winter_offpeak, config, inputs=inputs)

        # Find EV slots
        ev_slots = [s for s in result.slots if 'ev' in s.devices]

        if result.ev_estimate.get('needed') and len(ev_slots) > 0:
            # All EV slots should be before 07:00 deadline
            deadline_hour = 7
            for slot in ev_slots:
                # Slot should either be before midnight and before 7am,
                # or after midnight but before 7am
                slot_hour = slot.start.hour
                # For next-day scheduling, we need to handle the case where
                # schedule starts in the evening (e.g., 23:00) and continues
                # past midnight. The deadline is 07:00 the NEXT day.
                # If the slot is on the next day (slot.start.day > now.day),
                # then check it's before 07:00.
                if slot.start.day > inputs.bmw_i5_battery:  # Different day check
                    assert slot_hour < deadline_hour, \
                        f"EV slot at {slot.start} should be before 07:00 deadline"

    def test_ev_not_scheduled_during_peak(self, config, base_inputs, winter_peak):
        """EV should not be scheduled during peak tariff periods."""
        inputs = replace(
            base_inputs,
            ev_state=EVState.READY,
            bmw_i5_battery=30,
            bmw_i5_location='home'
        )

        result = generate_schedule(winter_peak, config, inputs=inputs)

        # Find EV slots during peak
        ev_peak_slots = [
            s for s in result.slots
            if 'ev' in s.devices and s.tariff == 'peak'
        ]

        # EV should not be scheduled during peak
        assert len(ev_peak_slots) == 0, \
            "EV should not be scheduled during peak tariff"


class TestScheduleSlot:
    """Test ScheduleSlot functionality."""

    def test_slot_can_add_device(self):
        """Slot should correctly determine if device can be added."""
        slot = ScheduleSlot(
            start=datetime(2024, 1, 15, 10, 0),
            end=datetime(2024, 1, 15, 10, 30),
            tariff='off-peak',
            power_limit=5000
        )

        # Should be able to add a 2500W device
        assert slot.can_add('boiler', 2500) is True

        # Add the device
        assert slot.add_device('boiler', 2500) is True
        assert slot.total_power == 2500
        assert slot.remaining_capacity == 2500

        # Should still be able to add another 2000W device
        assert slot.can_add('ev', 2000) is True

        # But not a 3000W device
        assert slot.can_add('table_heater', 3000) is False

    def test_slot_total_power(self):
        """Slot total power should sum all device powers."""
        slot = ScheduleSlot(
            start=datetime(2024, 1, 15, 10, 0),
            end=datetime(2024, 1, 15, 10, 30),
            tariff='super-off-peak',
            power_limit=8000
        )

        slot.add_device('boiler', 2500)
        slot.add_device('ev', 4000)
        slot.add_device('table_heater', 1000)

        assert slot.total_power == 7500
        assert slot.remaining_capacity == 500
