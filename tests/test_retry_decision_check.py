"""Regression tests for CODE_REVIEW_PASS2.md N4.

Pre-fix: verify_and_retry_pending_commands re-issued a stored expected_state
without re-consulting the engine. Scenario: at 06:55 (last super-off-peak
minute) the engine wants boiler ON; a transient HA glitch swallows the call.
At 07:01 (after the 1-minute backoff) the engine no longer wants boiler ON
(tariff flipped to peak, decision is now `off`). The retry would fire
`turn_on(boiler)` anyway, overriding the current decision.

Fix: before each retry, look up the current decision for that entity. If the
desired state has flipped against the pending command, drop it instead.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import (
    AppState, PendingCommand, app_state, verify_and_retry_pending_commands,
)
from app.models import Decisions
from app.config import Config


@pytest.fixture(autouse=True)
def restore_app_state():
    """Snapshot/restore app_state around each test (it's a module global)."""
    saved_config = app_state.config
    saved_decisions = app_state.last_decisions
    saved_pending = dict(app_state.pending_commands)
    saved_client = app_state.ha_client
    try:
        yield
    finally:
        app_state.config = saved_config
        app_state.last_decisions = saved_decisions
        app_state.pending_commands = saved_pending
        app_state.ha_client = saved_client


@pytest.fixture
def fresh_state():
    """Wire app_state with a Config and a mocked HA client."""
    config = Config()
    app_state.config = config
    app_state.ha_client = MagicMock()
    app_state.ha_client.turn_on = AsyncMock(return_value=True)
    app_state.ha_client.turn_off = AsyncMock(return_value=True)
    app_state.ha_client.send_notification = AsyncMock(return_value=True)
    app_state.pending_commands = {}
    app_state.last_decisions = Decisions()
    return config


def _stale_pending(entity_id: str, expected_state: str) -> PendingCommand:
    """A pending command old enough to be eligible for retry (>1 min)."""
    now = datetime.now()
    cmd = PendingCommand(
        entity_id=entity_id,
        expected_state=expected_state,
        command_time=now - timedelta(minutes=2),
        last_retry=now - timedelta(minutes=2),
        retry_count=0,
    )
    return cmd


@pytest.mark.asyncio
async def test_retry_dropped_when_decision_flipped_off(fresh_state):
    """The 06:55 super-off-peak → 07:01 peak scenario.

    Boiler was commanded ON but state is still 'off'. Engine has since
    decided action='off'. Retry must NOT call turn_on; pending entry must
    be dropped.
    """
    boiler_entity = fresh_state.entities.boiler_switch
    app_state.pending_commands[boiler_entity] = _stale_pending(
        boiler_entity, 'on'
    )
    # Engine has since flipped to 'off'
    app_state.last_decisions.boiler.action = 'off'

    # HA reports boiler still off (the command never landed)
    states = {boiler_entity: {'state': 'off'}}

    await verify_and_retry_pending_commands(states)

    # The stale retry must NOT have fired
    app_state.ha_client.turn_on.assert_not_called()
    # The pending command must be gone (dropped, not still queued)
    assert boiler_entity not in app_state.pending_commands


@pytest.mark.asyncio
async def test_retry_dropped_when_decision_flipped_on(fresh_state):
    """Reverse direction: boiler was commanded OFF, state still 'on',
    engine has since decided 'on'. Retry must NOT call turn_off."""
    boiler_entity = fresh_state.entities.boiler_switch
    app_state.pending_commands[boiler_entity] = _stale_pending(
        boiler_entity, 'off'
    )
    app_state.last_decisions.boiler.action = 'on'

    states = {boiler_entity: {'state': 'on'}}

    await verify_and_retry_pending_commands(states)

    app_state.ha_client.turn_off.assert_not_called()
    assert boiler_entity not in app_state.pending_commands


@pytest.mark.asyncio
async def test_retry_still_fires_when_decision_unchanged(fresh_state):
    """Engine still wants ON, command still pending — retry must fire."""
    boiler_entity = fresh_state.entities.boiler_switch
    app_state.pending_commands[boiler_entity] = _stale_pending(
        boiler_entity, 'on'
    )
    app_state.last_decisions.boiler.action = 'on'

    states = {boiler_entity: {'state': 'off'}}

    await verify_and_retry_pending_commands(states)

    app_state.ha_client.turn_on.assert_called_once_with(boiler_entity)
    # Still queued for further verification
    assert boiler_entity in app_state.pending_commands


@pytest.mark.asyncio
async def test_retry_still_fires_when_decision_is_none(fresh_state):
    """Engine has no fresh opinion (action='none'): keep retrying."""
    boiler_entity = fresh_state.entities.boiler_switch
    app_state.pending_commands[boiler_entity] = _stale_pending(
        boiler_entity, 'on'
    )
    app_state.last_decisions.boiler.action = 'none'  # default

    states = {boiler_entity: {'state': 'off'}}

    await verify_and_retry_pending_commands(states)

    app_state.ha_client.turn_on.assert_called_once()
    assert boiler_entity in app_state.pending_commands


@pytest.mark.asyncio
async def test_ev_pause_action_treated_as_off(fresh_state):
    """For the EV, action='pause' (soft-pause via amps=5) is logically off
    as far as a turn_on retry is concerned — so a pending turn_on must drop."""
    ev_entity = fresh_state.entities.ev_switch
    app_state.pending_commands[ev_entity] = _stale_pending(ev_entity, 'on')
    app_state.last_decisions.ev.action = 'pause'

    states = {ev_entity: {'state': 'off'}}

    await verify_and_retry_pending_commands(states)

    app_state.ha_client.turn_on.assert_not_called()
    assert ev_entity not in app_state.pending_commands


@pytest.mark.asyncio
async def test_ev_adjust_action_treated_as_on(fresh_state):
    """action='adjust' (changing amps) still implies the EV is on — keep
    retrying a pending turn_on."""
    ev_entity = fresh_state.entities.ev_switch
    app_state.pending_commands[ev_entity] = _stale_pending(ev_entity, 'on')
    app_state.last_decisions.ev.action = 'adjust'

    states = {ev_entity: {'state': 'off'}}

    await verify_and_retry_pending_commands(states)

    app_state.ha_client.turn_on.assert_called_once()
    assert ev_entity in app_state.pending_commands


@pytest.mark.asyncio
async def test_retry_success_path_still_works(fresh_state):
    """If the command actually succeeded between snapshots, drop the pending
    entry without firing a retry — regression on the existing happy path."""
    boiler_entity = fresh_state.entities.boiler_switch
    app_state.pending_commands[boiler_entity] = _stale_pending(
        boiler_entity, 'on'
    )
    app_state.last_decisions.boiler.action = 'on'

    states = {boiler_entity: {'state': 'on'}}  # HA confirms on

    await verify_and_retry_pending_commands(states)

    app_state.ha_client.turn_on.assert_not_called()
    assert boiler_entity not in app_state.pending_commands
