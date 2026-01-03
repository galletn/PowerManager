"""Pydantic models for Power Manager."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional


class EVState(IntEnum):
    """ABB Terra AC charger states.

    The charger can report either OCPP states (1-6) or custom states (128+).
    We handle both formats.
    """
    # OCPP standard states
    OCPP_AVAILABLE = 1
    OCPP_PREPARING = 2
    OCPP_CHARGING = 3
    OCPP_SUSPENDED_EV = 4  # Car connected, charging suspended by EV
    OCPP_SUSPENDED_EVSE = 5  # Charging suspended by charger
    OCPP_FINISHING = 6

    # ABB custom states (seen in some firmware versions)
    NO_CAR = 128
    READY = 129
    FULL = 130
    CHARGING = 132


@dataclass
class PowerInputs:
    """Validated sensor readings from Home Assistant."""
    # Power readings (Watts)
    p1_power: float = 0.0       # Grid import
    p1_return: float = 0.0      # Grid export (for calculating true consumption)
    pv_power: float = 0.0       # Solar production

    # Boiler
    boiler_switch: str = 'off'
    boiler_power: float = 0.0
    boiler_force: str = 'off'

    # Pool
    pool_season: str = 'off'
    pool_power: float = 0.0
    pool_climate: str = 'off'
    pool_pump_switch: str = 'on'
    pool_pump_power: float = 0.0
    pool_ambient_temp: Optional[float] = None

    # EV Charger
    ev_state: int = EVState.NO_CAR
    ev_switch: str = 'off'
    ev_power: float = 0.0
    ev_limit: int = 6

    # Heaters
    heater_right_switch: str = 'off'
    heater_table_switch: str = 'off'
    heater_table_power: float = 0.0

    # Dishwasher
    dishwasher_switch: str = 'off'
    dishwasher_power: float = 0.0

    # Laundry
    washing_machine_power: float = 0.0
    tumble_dryer_power: float = 0.0

    # AC Units
    ac_living_state: str = 'off'
    ac_mancave_state: str = 'off'
    ac_office_state: str = 'off'
    ac_bedroom_state: str = 'off'
    ac_living_power: float = 0.0
    ac_office_power: float = 0.0

    # Temperatures
    temp_living: float = 20.0
    temp_bedroom: float = 20.0
    temp_mancave: float = 20.0

    # Overrides
    ovr_ac_living: str = ''
    ovr_ac_bedroom: str = ''
    ovr_ac_office: str = ''
    ovr_ac_mancave: str = ''
    ovr_pool: str = ''
    ovr_boiler: str = ''
    ovr_ev: str = ''
    ovr_table_heater: str = ''
    ovr_dishwasher: str = ''

    # BMW Cars
    bmw_i5_battery: Optional[float] = None
    bmw_i5_range: Optional[float] = None
    bmw_i5_location: str = 'unknown'
    bmw_ix1_battery: Optional[float] = None
    bmw_ix1_range: Optional[float] = None
    bmw_ix1_location: str = 'unknown'


@dataclass
class DeviceDecision:
    """Decision for a single device."""
    action: str = 'none'  # 'none', 'on', 'off', 'adjust'
    reason: str = ''


@dataclass
class EVDecision(DeviceDecision):
    """Decision for EV charger with amp setting."""
    amps: int = 6


@dataclass
class ACDecision(DeviceDecision):
    """Decision for AC unit with mode and temperature."""
    mode: str = 'off'  # 'off', 'heat', 'cool', 'auto'
    temp: int = 22


@dataclass
class Decisions:
    """All device decisions."""
    ev: EVDecision = field(default_factory=lambda: EVDecision())
    boiler: DeviceDecision = field(default_factory=lambda: DeviceDecision())
    pool: DeviceDecision = field(default_factory=lambda: DeviceDecision())
    pool_pump: DeviceDecision = field(default_factory=lambda: DeviceDecision())
    heater_right: DeviceDecision = field(default_factory=lambda: DeviceDecision())
    heater_table: DeviceDecision = field(default_factory=lambda: DeviceDecision())
    dishwasher: DeviceDecision = field(default_factory=lambda: DeviceDecision())
    ac_living: ACDecision = field(default_factory=lambda: ACDecision())
    ac_mancave: ACDecision = field(default_factory=lambda: ACDecision(temp=17))
    ac_office: ACDecision = field(default_factory=lambda: ACDecision())
    ac_bedroom: ACDecision = field(default_factory=lambda: ACDecision())


@dataclass
class DeviceState:
    """State of a single device with timing info."""
    on: bool = False
    last_change: float = 0.0  # timestamp


@dataclass
class AllDeviceStates:
    """All device states for timing/hysteresis."""
    ev: DeviceState = field(default_factory=lambda: DeviceState())
    boiler: DeviceState = field(default_factory=lambda: DeviceState())
    pool: DeviceState = field(default_factory=lambda: DeviceState())
    pool_pump: DeviceState = field(default_factory=lambda: DeviceState(on=True))
    heater_right: DeviceState = field(default_factory=lambda: DeviceState())
    heater_table: DeviceState = field(default_factory=lambda: DeviceState())
    dishwasher: DeviceState = field(default_factory=lambda: DeviceState())
    ac_living: DeviceState = field(default_factory=lambda: DeviceState())
    ac_mancave: DeviceState = field(default_factory=lambda: DeviceState())
    ac_office: DeviceState = field(default_factory=lambda: DeviceState())
    ac_bedroom: DeviceState = field(default_factory=lambda: DeviceState())
    # Boiler "full" detection: timestamp when power first dropped below threshold
    # 0.0 means power is above threshold (not low)
    boiler_low_power_since: float = 0.0
    # Boiler heating tracking: when boiler last actively heated (power > threshold)
    # Used to detect if boiler has heated tonight before deadline
    boiler_last_heating_time: float = 0.0
    # Track total heating time in current night cycle (resets at midnight)
    boiler_heating_tonight_seconds: float = 0.0
    boiler_heating_night_date: str = ''  # Date string to detect day rollover


@dataclass
class Alert:
    """Alert/notification to send."""
    level: str  # 'warning', 'critical'
    message: str
    notify_entity: Optional[str] = None
    car_name: Optional[str] = None
    battery: Optional[float] = None
    range_km: Optional[float] = None


@dataclass
class DecisionResult:
    """Result from decision engine."""
    decisions: Decisions
    plan: list[str]
    headroom: float
    alerts: list[Alert]
    meta: dict


@dataclass
class PowerStatus:
    """Current power status for dashboard."""
    grid_import: float
    grid_export: float
    pv_production: float
    net_power: float
    is_exporting: bool
    tariff: str
    devices: dict
    plan: list[str]
    alerts: list[dict]
    last_update: datetime
