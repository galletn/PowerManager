"""Configuration management for Power Manager."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class HAConfig:
    """Home Assistant connection settings."""
    url: str = ""
    token: str = ""
    verify_ssl: bool = False


@dataclass
class GridConfig:
    """Grid power limits by tariff."""
    peak: int = 2500
    off_peak: int = 5000
    super_off_peak: int = 8000
    super_off_peak_winter: int = 9000  # Higher limit in winter for heating


@dataclass
class TariffPricesConfig:
    """Electricity prices per kWh (EUR). Update monthly based on supplier rates."""
    peak: float = 0.17
    off_peak: float = 0.13
    super_off_peak: float = 0.10


@dataclass
class EVConfig:
    """EV charger settings."""
    min_amps: int = 6
    max_amps: int = 16
    watts_per_amp: int = 692  # 3-phase: ~230V × 3 = 690W per amp
    amp_change_threshold: int = 2
    # Note: Effective charging power is calculated dynamically based on grid limits
    # Min power: 6A × 692W = 4.2kW, Max power: 16A × 692W = 11kW


@dataclass
class BoilerConfig:
    """Boiler settings."""
    power: int = 2500
    idle_threshold: int = 50
    deadline_winter: float = 6.5
    deadline_summer: float = 8.0
    full_confirm_seconds: int = 120  # Power must be low for this many seconds to confirm "full"


@dataclass
class PoolConfig:
    """Pool heat pump settings."""
    idle_power: int = 100
    active_power: int = 2000


@dataclass
class FrostProtectionConfig:
    """Frost protection settings."""
    enabled: bool = True
    temp_threshold: float = 5.0
    critical_threshold: float = 2.0
    pump_min_power: int = 100
    pump_off_alert_delay: int = 300
    notify_entity: str = "mobile_app_your_phone"


@dataclass
class BMWLowBatteryConfig:
    """BMW low battery warning settings."""
    enabled: bool = True
    battery_threshold: int = 50
    check_hours: list = field(default_factory=lambda: [20, 21, 22])
    notify_entity: str = "mobile_app_your_phone"


@dataclass
class HeaterConfig:
    """Heater power settings."""
    right_power: int = 2500
    table_power: int = 4100


@dataclass
class ACUnitConfig:
    """AC unit settings."""
    power: int = 1000
    winter_setpoint: int = 22


@dataclass
class ACConfig:
    """All AC unit settings."""
    living: ACUnitConfig = field(default_factory=lambda: ACUnitConfig(power=1500, winter_setpoint=21))
    mancave: ACUnitConfig = field(default_factory=lambda: ACUnitConfig(power=1000, winter_setpoint=17))
    office: ACUnitConfig = field(default_factory=lambda: ACUnitConfig(power=1000, winter_setpoint=22))
    bedroom: ACUnitConfig = field(default_factory=lambda: ACUnitConfig(power=1000, winter_setpoint=22))


@dataclass
class EntitiesConfig:
    """Home Assistant entity IDs."""
    # Power sensors
    p1: str = "sensor.electricity_currently_delivered"
    p1_return: str = "sensor.electricity_currently_returned"
    pv: str = "sensor.solaredge_i1_ac_power"

    # EV Charger
    ev_switch: str = "switch.abb_terra_ac_charging"
    ev_power: str = "sensor.abb_terra_ac_active_power"
    ev_limit: str = "number.abb_terra_ac_current_limit"
    ev_state: str = "sensor.abb_terra_ac_charging_state"

    # Boiler
    boiler_switch: str = "switch.storage_boiler"
    boiler_power: str = "sensor.storage_boiler_power"
    boiler_force: str = "input_boolean.force_heat_boiler"

    # Pool
    pool_climate: str = "climate.98d8639f920c"
    pool_power: str = "sensor.pool_heating_current_consumption"
    pool_season: str = "input_boolean.pool_season"
    pool_pump: str = "switch.poolhouse_pool_pump"
    pool_pump_power: str = "sensor.poolhouse_pool_pump_power"
    pool_ambient_temp: str = "sensor.98d8639f920c_ambient_temp_t05"

    # Heaters
    heater_right: str = "switch.livingroom_right_heater"
    heater_table: str = "switch.livingroom_table_heater_state"

    # Dishwasher
    dishwasher_switch: str = "switch.kitchen_dishwasher"
    dishwasher_power: str = "sensor.kitchen_dishwasher_power"

    # AC Units
    ac_living: str = "climate.living"
    ac_mancave: str = "climate.mancave"
    ac_office: str = "climate.bureau"
    ac_bedroom: str = "climate.slaapkamer"
    ac_living_power: str = "sensor.living_current_power"
    ac_office_power: str = "sensor.bureau_current_power"

    # Temperatures
    temp_living: str = "sensor.livingroom_temperature_temperature"
    temp_bedroom: str = "sensor.bedroom_temperature_temperature"
    temp_mancave: str = "sensor.mancave_inside_temperature"

    # Overrides
    ovr_ac_living: str = "input_select.pm_override_ac_living"
    ovr_ac_bedroom: str = "input_select.pm_override_ac_slaapkamer"
    ovr_ac_office: str = "input_select.pm_override_ac_bureau"
    ovr_ac_mancave: str = "input_select.pm_override_ac_mancave"
    ovr_pool: str = "input_select.pm_override_pool"
    ovr_boiler: str = "input_select.pm_override_boiler"
    ovr_ev: str = "input_select.pm_override_ev"
    ovr_table_heater: str = "input_select.pm_override_table_heater"
    ovr_dishwasher: str = "input_select.pm_override_dishwasher"

    # Status helpers
    status_text: str = "input_text.power_manager_status"
    status_plan: str = "input_text.power_manager_plan"
    status_actions: str = "input_text.power_manager_actions"

    # Power limit helpers (configurable via dashboard)
    limit_peak: str = "input_number.pm_limit_peak"
    limit_off_peak: str = "input_number.pm_limit_off_peak"
    limit_super_off_peak: str = "input_number.pm_limit_super_off_peak"

    # BMW Cars - i5 eDrive40
    bmw_i5_battery: str = "sensor.i5_edrive40_battery_hv_state_of_charge"
    bmw_i5_range: str = "sensor.i5_edrive40_range_ev_remaining_range"
    bmw_i5_location: str = "device_tracker.i5_edrive40_location"
    bmw_i5_charging_state: str = "sensor.i5_edrive40_charging_ev_charging_state"
    bmw_i5_charging_power: str = "sensor.i5_edrive40_battery_ev_charging_power"
    bmw_i5_plug_state: str = "sensor.i5_edrive40_charging_port_plug_state"
    bmw_i5_target_soc: str = "sensor.i5_edrive40_battery_ev_target_state_of_charge"
    bmw_i5_mileage: str = "sensor.i5_edrive40_vehicle_mileage"
    bmw_i5_time_to_full: str = "sensor.i5_edrive40_charging_ev_time_to_full_charge"
    # i5 charging-specific sensors (only valid during charging)
    bmw_i5_charging_soc: str = "sensor.i5_edrive40_charging_ev_predicted_state_of_charge"
    bmw_i5_charging_range: str = "sensor.i5_edrive40_range_ev_estimate_during_charging"

    # BMW Cars - iX1 eDrive20
    bmw_ix1_battery: str = "sensor.ix1_edrive20_battery_hv_state_of_charge"
    bmw_ix1_range: str = "sensor.ix1_edrive20_range_ev_remaining_range"
    bmw_ix1_location: str = "device_tracker.ix1_edrive20_location"
    bmw_ix1_charging_state: str = "sensor.ix1_edrive20_charging_ev_charging_state"
    bmw_ix1_charging_power: str = "sensor.ix1_edrive20_battery_ev_charging_power"
    bmw_ix1_plug_state: str = "sensor.ix1_edrive20_charging_port_plug_state"
    bmw_ix1_target_soc: str = "sensor.ix1_edrive20_battery_ev_target_state_of_charge"
    bmw_ix1_mileage: str = "sensor.ix1_edrive20_vehicle_mileage"
    bmw_ix1_time_to_full: str = "sensor.ix1_edrive20_charging_ev_time_to_full_charge"
    # iX1 charging-specific sensors (only valid during charging)
    bmw_ix1_charging_soc: str = "sensor.ix1_edrive20_charging_ev_predicted_state_of_charge"
    bmw_ix1_charging_range: str = "sensor.ix1_edrive20_range_ev_estimate_during_charging"

    # Battery (SolarEdge Energy Bank - on second inverter SE5000H)
    battery_power: str = "sensor.solaredge2_i1_b1_dc_power_inverted" # +discharge, -charge (W)
    battery_soe: str = "sensor.solaredge2_i1_b1_state_of_energy_2"   # 0-100%
    battery_status: str = "sensor.solaredge2_i1_b1_status_2"         # B_STATUS_CHARGE etc.
    battery_capacity: str = "sensor.solaredge2_i1_b1_maximum_energy_2" # Max capacity (kWh)

    # Sun and weather for dashboard icons
    sun: str = "sun.sun"
    weather: str = "weather.huis"
    solar_forecast: str = "sensor.estimated_solar_power_left_today"

    # Additional consumers for power tracking
    media_power: str = "sensor.livingroom_media_power_power"
    server_power: str = "sensor.serverroom_server_power"
    desk_power: str = "sensor.livingroom_desk_power_power"
    storage_fridge_power: str = "sensor.storage_fridge_power"
    kitchen_fridge_power: str = "sensor.kitchen_fridge_power"
    washing_machine_power: str = "sensor.garage_washing_machine_power"
    tumble_dryer_power: str = "sensor.garage_tumble_dryer_power"
    serverroom_storage_power: str = "sensor.serverroom_storage_power"
    pool_heater_power: str = "sensor.pool_heating_current_consumption"
    table_heater_power: str = "sensor.livingroom_table_heater_power"
    chargers_power: str = "sensor.livingroom_chargers_power"


@dataclass
class TimingConfig:
    """Timing settings."""
    hysteresis: int = 300
    min_on_time: int = 300
    min_off_time: int = 180


@dataclass
class Config:
    """Main configuration."""
    home_assistant: HAConfig = field(default_factory=HAConfig)
    polling_interval: int = 30
    port: int = 8081  # Server port for uvicorn
    max_import: GridConfig = field(default_factory=GridConfig)
    tariff_prices: TariffPricesConfig = field(default_factory=TariffPricesConfig)
    ev: EVConfig = field(default_factory=EVConfig)
    boiler: BoilerConfig = field(default_factory=BoilerConfig)
    pool: PoolConfig = field(default_factory=PoolConfig)
    frost_protection: FrostProtectionConfig = field(default_factory=FrostProtectionConfig)
    bmw_low_battery: BMWLowBatteryConfig = field(default_factory=BMWLowBatteryConfig)
    heaters: HeaterConfig = field(default_factory=HeaterConfig)
    ac: ACConfig = field(default_factory=ACConfig)
    entities: EntitiesConfig = field(default_factory=EntitiesConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    summer_cool_threshold: float = 25.0
    summer_target_temp: float = 22.0
    units_p1: int = 1000  # P1 meter: kW -> W
    units_pv: int = 1     # SolarEdge: already in W
    enable_notifications: bool = True
    debug: bool = False


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from YAML file or environment."""
    config = Config()

    # Try to load from file
    if config_path is None:
        config_path = os.environ.get("PM_CONFIG", "config.yaml")

    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f)
            if data:
                _apply_config(config, data)

    # Override with environment variables
    if os.environ.get("HA_URL"):
        config.home_assistant.url = os.environ["HA_URL"]
    if os.environ.get("HA_TOKEN"):
        config.home_assistant.token = os.environ["HA_TOKEN"]
    if os.environ.get("PORT"):
        config.port = int(os.environ["PORT"])

    # Validate configuration
    if not config.home_assistant.token:
        raise ValueError("Home Assistant token is required but not configured")

    if config.max_import.peak <= 0:
        raise ValueError("max_import.peak must be greater than 0")
    if config.max_import.off_peak <= 0:
        raise ValueError("max_import.off_peak must be greater than 0")
    if config.max_import.super_off_peak <= 0:
        raise ValueError("max_import.super_off_peak must be greater than 0")

    if not config.home_assistant.verify_ssl:
        logger.warning("SSL verification is disabled for Home Assistant connection")

    return config


def _apply_config(config: Config, data: dict) -> None:
    """Apply YAML data to config object."""
    if "home_assistant" in data:
        ha = data["home_assistant"]
        if "url" in ha:
            config.home_assistant.url = ha["url"]
        if "token" in ha:
            config.home_assistant.token = ha["token"]
        if "verify_ssl" in ha:
            config.home_assistant.verify_ssl = ha["verify_ssl"]

    if "polling_interval" in data:
        config.polling_interval = data["polling_interval"]

    if "port" in data:
        config.port = data["port"]

    if "max_import" in data:
        mi = data["max_import"]
        if "peak" in mi:
            config.max_import.peak = mi["peak"]
        if "off_peak" in mi:
            config.max_import.off_peak = mi["off_peak"]
        if "super_off_peak" in mi:
            config.max_import.super_off_peak = mi["super_off_peak"]

    if "tariff_prices" in data:
        tp = data["tariff_prices"]
        if "peak" in tp:
            config.tariff_prices.peak = tp["peak"]
        if "off_peak" in tp:
            config.tariff_prices.off_peak = tp["off_peak"]
        if "super_off_peak" in tp:
            config.tariff_prices.super_off_peak = tp["super_off_peak"]

    if "frost_protection" in data:
        fp = data["frost_protection"]
        if "enabled" in fp:
            config.frost_protection.enabled = fp["enabled"]
        if "temp_threshold" in fp:
            config.frost_protection.temp_threshold = fp["temp_threshold"]
        if "critical_threshold" in fp:
            config.frost_protection.critical_threshold = fp["critical_threshold"]
        if "notify_entity" in fp:
            config.frost_protection.notify_entity = fp["notify_entity"]

    if "bmw_low_battery" in data:
        bmw = data["bmw_low_battery"]
        if "enabled" in bmw:
            config.bmw_low_battery.enabled = bmw["enabled"]
        if "battery_threshold" in bmw:
            config.bmw_low_battery.battery_threshold = bmw["battery_threshold"]
        if "check_hours" in bmw:
            config.bmw_low_battery.check_hours = bmw["check_hours"]
        if "notify_entity" in bmw:
            config.bmw_low_battery.notify_entity = bmw["notify_entity"]

    if "debug" in data:
        config.debug = data["debug"]
