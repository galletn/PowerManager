"""Regression test for CODE_REVIEW_PASS2.md N6.

generate_timetable previously had this structure:

    for entry in timetable:
        entry['total_power'] = sum(entry['devices'].values())
        entry['utilization'] = ...
    if current_entry:
        timetable.append(current_entry)

The final hour (current_entry) was appended AFTER the totals loop, so it
arrived with total_power=0 and no utilization key. dashboard.js read
`entry.total_power || 0` and the over-limit visualisation never warned for
that hour.

Fix: append current_entry BEFORE the totals loop (or include it in the loop).
"""

from datetime import datetime, timedelta

from app.scheduler import ScheduleSlot, generate_timetable


def _make_slots_with_device_in_final_hour():
    """Build 48 half-hour slots; only the last 2 (final hour) carry a device."""
    base = datetime(2024, 1, 15, 0, 0, 0)
    slots = []
    for i in range(48):
        start = base + timedelta(minutes=30 * i)
        slot = ScheduleSlot(
            start=start,
            end=start + timedelta(minutes=30),
            tariff='off-peak',
            power_limit=5000,
        )
        if i >= 46:  # last hour: 23:00-23:30 and 23:30-24:00
            slot.devices['boiler'] = 2500
        slots.append(slot)
    return slots


def test_last_hour_has_total_power():
    timetable = generate_timetable(_make_slots_with_device_in_final_hour())
    assert len(timetable) == 24, "should produce 24 hourly entries"
    last_hour = timetable[-1]
    assert last_hour['hour'] == '23:00'
    assert last_hour['total_power'] == 2500, (
        f"last hour total_power={last_hour['total_power']!r}; "
        "the pre-fix bug returned 0 because current_entry was appended "
        "AFTER the totals loop."
    )


def test_last_hour_has_utilization():
    timetable = generate_timetable(_make_slots_with_device_in_final_hour())
    last_hour = timetable[-1]
    assert 'utilization' in last_hour, (
        "last hour missing 'utilization' key — over-limit dashboard "
        "visualisation will never warn for this hour"
    )
    # 2500/5000 = 50%
    assert last_hour['utilization'] == 50


def test_all_24_hours_have_totals_keys():
    """Every hour must have total_power AND utilization, not just the first 23."""
    slots = _make_slots_with_device_in_final_hour()
    timetable = generate_timetable(slots)

    for entry in timetable:
        assert 'total_power' in entry, f"hour {entry['hour']} missing total_power"
        assert 'utilization' in entry, f"hour {entry['hour']} missing utilization"
