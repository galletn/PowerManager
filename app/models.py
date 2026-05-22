"""Pydantic models for Power Manager."""

from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Optional


class EVState(IntEnum):
    """ABB Terra AC charger states.

    ABB firmware reports either IEC 61851-1 standard states (0-5) or
    ABB custom states (128+), depending on firmware. Both formats are handled.

    States 4 (IEC C2) and 132 (ABB custom) BOTH mean "actively charging" —
    the charger alternates between them in some firmware versions.
    """
    # IEC 61851-1 standard states
    IEC_IDLE = 0              # State A - no car connected
    IEC_CONNECTED_B1 = 1      # State B1 - connected, pending authorization
    IEC_CONNECTED_B2 = 2      # State B2 - connected, ready (authorized)
    IEC_READY_C1 = 3          # State C1 - ready, PWM not yet active
    IEC_CHARGING_C2 = 4       # State C2 - ACTIVELY charging
    IEC_OTHER = 5

    # ABB custom states
    NO_CAR = 128
    READY = 129
    FULL = 130                # "Charging Complete" per ABB docs
    CHARGING = 132
    PAUSED = 133

    @staticmethod
    def _coerce(code) -> Optional[int]:
        """Best-effort coerce HA state into an int code; None for unparseable.

        HA sometimes returns numeric sensor states as strings (e.g. "132").
        Callers should be insulated from that without silently misclassifying.
        """
        if code is None:
            return None
        if isinstance(code, int):
            return code
        try:
            return int(code)
        except (TypeError, ValueError):
            return None

    @classmethod
    def is_charging(cls, code) -> bool:
        """Charger is actively delivering current to the car."""
        c = cls._coerce(code)
        return c in (cls.IEC_CHARGING_C2.value, cls.CHARGING.value)

    @classmethod
    def is_plugged(cls, code) -> bool:
        """A car is physically connected to the charger (incl. fully charged)."""
        c = cls._coerce(code)
        return c in (
            cls.IEC_CONNECTED_B1.value, cls.IEC_CONNECTED_B2.value,
            cls.IEC_READY_C1.value, cls.IEC_CHARGING_C2.value,
            cls.READY.value, cls.CHARGING.value, cls.FULL.value, cls.PAUSED.value,
        )

    @classmethod
    def is_active_session(cls, code) -> bool:
        """Plugged AND not yet finished — needs scheduling, alert-eligible."""
        return cls.is_plugged(code) and not cls.is_done(code)

    @classmethod
    def is_done(cls, code) -> bool:
        """Charger reports the car is fully charged."""
        return cls._coerce(code) == cls.FULL.value


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
    pool_fan_mode: str = 'low'
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

    # Battery (SolarEdge Energy Bank)
    battery_power: float = 0.0          # +discharge, -charge (W)
    battery_soe: Optional[float] = None # State of Energy 0-100%
    battery_status: str = 'unknown'     # Charging/Discharging/Idle
    battery_capacity: Optional[float] = None  # Max capacity (Wh)

    # BMW Cars - i5 eDrive40
    bmw_i5_battery: Optional[float] = None
    bmw_i5_range: Optional[float] = None
    bmw_i5_location: str = 'unknown'
    bmw_i5_charging_state: str = 'unknown'
    bmw_i5_charging_power: Optional[float] = None
    bmw_i5_plug_state: str = 'unknown'
    bmw_i5_target_soc: Optional[int] = None
    bmw_i5_mileage: Optional[int] = None
    bmw_i5_time_to_full: Optional[float] = None
    bmw_i5_charging_soc: Optional[float] = None  # Only valid during charging
    bmw_i5_charging_range: Optional[float] = None  # Only valid during charging

    # BMW Cars - iX1 eDrive20
    bmw_ix1_battery: Optional[float] = None
    bmw_ix1_range: Optional[float] = None
    bmw_ix1_location: str = 'unknown'
    bmw_ix1_charging_state: str = 'unknown'
    bmw_ix1_charging_power: Optional[float] = None
    bmw_ix1_plug_state: str = 'unknown'
    bmw_ix1_target_soc: Optional[int] = None
    bmw_ix1_mileage: Optional[int] = None
    bmw_ix1_time_to_full: Optional[float] = None
    bmw_ix1_charging_soc: Optional[float] = None  # Only valid during charging
    bmw_ix1_charging_range: Optional[float] = None  # Only valid during charging


@dataclass
class DecisionContext:
    """Typed context passed from calculate_decisions to all _handle_* and
    _apply_*_logic functions. Replaces the prior 45-key dict-based ctx.

    Constructed once at the end of calculate_decisions's "input parsing"
    block. Read-only by convention — handlers MAY mutate fields on
    `device_state` (a member) but MUST NOT reassign ctx fields. Use
    `dataclasses.replace(ctx, ...)` if a derived ctx is needed (not
    currently any consumer).

    Field defaults preserve the prior `ctx.get(key, default)` runtime
    semantics from app/decision_engine.py — a missing field at a `.X`
    access site now returns the dataclass default instead of raising.
    """
    # === Override / mode flags ===
    ovr: dict = field(default_factory=dict)
    is_summer: bool = False

    # === EV input/state ===
    ev_done: bool = False
    ev_plugged: bool = False
    ev_ready: bool = False
    ev_charging: bool = False
    ev_limit: int = 6
    ev_power: float = 0.0
    ev_hours_needed: float = 0.0

    # === Boiler input/state ===
    boiler_on: bool = False
    boiler_full: bool = False
    boiler_force: bool = False    # Runtime stores `inputs.boiler_force == 'on'`, not the raw HA string.
    boiler_power: float = 0.0

    # === Heater input/state (set in BOTH branches post-Story-1.15) ===
    ht_on: bool = False
    hr_on: bool = False
    ht_power: float = 0.0

    # === Pool input/state ===
    pool_heating_on: bool = False
    pool_power: float = 0.0
    pool_season: bool = False

    # === Dishwasher input/state ===
    dw_switch_on: bool = False
    dw_power: float = 0.0
    dw_running: bool = False
    dw_waiting: bool = False

    # === Power state ===
    headroom: float = 0.0
    hyst: int = 0
    pv: float = 0.0
    p1: float = 0.0
    p1_return: float = 0.0
    net_p1: float = 0.0
    is_exporting: bool = False
    smooth_p1: float = 0.0
    smooth_p1_return: float = 0.0
    smooth_pv: float = 0.0
    smooth_net_p1: float = 0.0
    smooth_is_exporting: bool = False
    battery_charge: float = 0.0
    battery_soe: Optional[float] = None
    battery_power: Optional[float] = None

    # === Tariff / time ===
    tariff: str = 'peak'
    tariff_info: dict = field(default_factory=dict)
    date: Any = None                # datetime
    now: float = 0.0                # epoch ms (now.timestamp() * 1000)

    # === Config / services / state references ===
    config: Any = None              # app.config.Config — Any to avoid circular import
    can_switch: Optional[Callable] = None
    device_state: Optional[Any] = None  # AllDeviceStates


@dataclass
class DeviceDecision:
    """Decision for a single device."""
    action: str = 'none'  # 'none', 'on', 'off', 'pause', 'adjust'
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
    # Solar surplus tracking: timestamp when device was turned on due to solar surplus
    # Used to implement grace period before turning off (avoid ping-pong)
    boiler_solar_surplus_since: float = 0.0
    pool_solar_surplus_since: float = 0.0
    # Timestamp when we started importing (no solar surplus) while device is on
    # Used to turn off device after grace period of sustained import
    boiler_importing_since: float = 0.0
    pool_importing_since: float = 0.0


@dataclass
class Alert:
    """Alert/notification to send."""
    level: str  # 'warning', 'critical'
    message: str
    notify_entity: Optional[str] = None
    car_name: Optional[str] = None
    battery: Optional[float] = None
    range_km: Optional[float] = None


class PowerBuffer:
    """Rolling buffer of power readings for smoothing transient spikes.

    Solar production and grid export can spike briefly (e.g., 5kW export burst
    when sun returns before battery inverter ramps up). Using raw instantaneous
    readings causes devices to flip-flop. This buffer provides smoothed values
    that filter out transients.

    Uses minimum of recent readings for export/solar (conservative — only acts
    on sustained surplus) and maximum for import (conservative — doesn't
    underestimate grid draw).
    """

    def __init__(self, max_samples: int = 6):
        """Initialize buffer. Default 6 samples = ~3 minutes at 30s polling."""
        self.max_samples = max_samples
        self._p1_return: deque[float] = deque(maxlen=max_samples)  # grid export
        self._p1_power: deque[float] = deque(maxlen=max_samples)   # grid import
        self._pv_power: deque[float] = deque(maxlen=max_samples)   # solar

    def add(self, inputs: 'PowerInputs') -> None:
        """Add a new set of readings to the buffer."""
        self._p1_return.append(inputs.p1_return)
        self._p1_power.append(inputs.p1_power)
        self._pv_power.append(inputs.pv_power)

    @property
    def ready(self) -> bool:
        """True when buffer has enough samples for meaningful smoothing."""
        return len(self._p1_return) >= 3

    @property
    def smoothed_p1_return(self) -> float:
        """Conservative grid export: minimum of recent readings.

        Only reports high export if it's been sustained, filtering out
        transient spikes when sun returns before battery ramps up.
        """
        if not self._p1_return:
            return 0.0
        return min(self._p1_return)

    @property
    def smoothed_p1_power(self) -> float:
        """Conservative grid import: maximum of recent readings.

        Reports the worst-case import to avoid underestimating grid draw.
        """
        if not self._p1_power:
            return 0.0
        return max(self._p1_power)

    @property
    def smoothed_pv(self) -> float:
        """Conservative solar: minimum of recent readings."""
        if not self._pv_power:
            return 0.0
        return min(self._pv_power)


@dataclass
class DecisionResult:
    """Result from decision engine."""
    decisions: Decisions
    plan: list[str]
    headroom: float
    alerts: list[Alert]
    meta: dict


