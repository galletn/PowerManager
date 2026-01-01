"""Pytest fixtures for Power Manager tests."""

import pytest
from datetime import datetime

from app.config import Config
from app.models import PowerInputs, AllDeviceStates, EVState


@pytest.fixture
def config():
    """Default test configuration."""
    return Config()


@pytest.fixture
def base_inputs():
    """Base power inputs for testing."""
    return PowerInputs(
        p1_power=1000,
        p1_return=0,
        pv_power=0,
        boiler_switch='off',
        boiler_power=0,
        boiler_force='off',
        pool_season='off',
        pool_power=0,
        pool_climate='off',
        pool_pump_switch='on',
        pool_pump_power=120,
        pool_ambient_temp=10,
        ev_state=EVState.NO_CAR,
        ev_switch='off',
        ev_power=0,
        ev_limit=6,
        heater_right_switch='off',
        heater_table_switch='off',
        ac_living_state='off',
        ac_mancave_state='off',
        ac_office_state='off',
        ac_bedroom_state='off',
        ac_living_power=0,
        ac_office_power=0,
        temp_living=20,
        temp_bedroom=20,
        temp_mancave=20,
        ovr_ac_living='',
        ovr_ac_bedroom='',
        ovr_ac_office='',
        ovr_ac_mancave='',
        ovr_pool='',
        ovr_boiler='',
        ovr_ev='',
        bmw_i5_battery=40,
        bmw_i5_range=124,
        bmw_i5_location='home',
        bmw_ix1_battery=83,
        bmw_ix1_range=254,
        bmw_ix1_location='not_home',
    )


@pytest.fixture
def device_state():
    """Initial device state."""
    return AllDeviceStates()


@pytest.fixture
def winter_evening():
    """Winter evening time (20:00 January)."""
    return datetime(2024, 1, 15, 20, 0, 0)


@pytest.fixture
def summer_midday():
    """Summer midday time (12:00 July)."""
    return datetime(2024, 7, 15, 12, 0, 0)


@pytest.fixture
def winter_offpeak():
    """Winter off-peak time (23:00)."""
    return datetime(2024, 1, 15, 23, 0, 0)


@pytest.fixture
def winter_peak():
    """Winter peak time (09:00 - morning peak)."""
    return datetime(2024, 1, 15, 9, 0, 0)
