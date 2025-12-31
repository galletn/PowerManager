"""Home Assistant API client."""

import logging
from typing import Any, Optional

import aiohttp

from .config import Config, EntitiesConfig
from .models import PowerInputs, EVState

logger = logging.getLogger(__name__)


class HAClient:
    """Async Home Assistant REST API client."""

    def __init__(self, config: Config):
        self.url = config.home_assistant.url.rstrip("/")
        self.token = config.home_assistant.token
        self.verify_ssl = config.home_assistant.verify_ssl
        self.entities = config.entities
        self.units_p1 = config.units_p1
        self.units_pv = config.units_pv
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self):
        """Create HTTP session."""
        connector = aiohttp.TCPConnector(ssl=self.verify_ssl)
        self._session = aiohttp.ClientSession(
            connector=connector,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )

    async def close(self):
        """Close HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def get_all_states(self) -> dict[str, dict]:
        """
        Fetch all entity states in one call.
        Returns dict mapping entity_id to state object.
        """
        if not self._session:
            raise RuntimeError("Client not connected")

        async with self._session.get(
            f"{self.url}/api/states",
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
            states = await resp.json()
            return {s["entity_id"]: s for s in states}

    async def get_state(self, entity_id: str) -> Optional[dict]:
        """Fetch single entity state."""
        if not self._session:
            raise RuntimeError("Client not connected")

        async with self._session.get(
            f"{self.url}/api/states/{entity_id}",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            return await resp.json()

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        **kwargs
    ) -> bool:
        """Call a Home Assistant service."""
        if not self._session:
            raise RuntimeError("Client not connected")

        data = {"entity_id": entity_id, **kwargs}
        logger.info(f"Calling {domain}.{service} on {entity_id}")

        async with self._session.post(
            f"{self.url}/api/services/{domain}/{service}",
            json=data,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
            return True

    async def turn_on(self, entity_id: str) -> bool:
        """Turn on a switch/light."""
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "turn_on", entity_id)

    async def turn_off(self, entity_id: str) -> bool:
        """Turn off a switch/light."""
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "turn_off", entity_id)

    async def set_number(self, entity_id: str, value: float) -> bool:
        """Set a number entity value (e.g., EV charger amps)."""
        return await self.call_service("number", "set_value", entity_id, value=value)

    async def set_climate(
        self,
        entity_id: str,
        hvac_mode: str = "off",
        temperature: Optional[float] = None
    ) -> bool:
        """Set climate entity mode and temperature."""
        if hvac_mode == "off":
            return await self.call_service("climate", "turn_off", entity_id)

        kwargs = {"hvac_mode": hvac_mode}
        if temperature is not None:
            kwargs["temperature"] = temperature

        return await self.call_service("climate", "set_hvac_mode", entity_id, **kwargs)

    async def send_notification(self, entity_id: str, title: str, message: str) -> bool:
        """Send a mobile notification."""
        return await self.call_service(
            "notify",
            entity_id.replace("mobile_app_", ""),
            entity_id,
            title=title,
            message=message
        )

    async def set_input_text(self, entity_id: str, value: str) -> bool:
        """Set an input_text helper value."""
        return await self.call_service("input_text", "set_value", entity_id, value=value[:255])

    def parse_inputs(self, states: dict[str, dict]) -> PowerInputs:
        """Parse all states into PowerInputs object."""
        e = self.entities

        def get_num(entity_id: str, default: float = 0.0, multiplier: float = 1.0) -> Optional[float]:
            state = states.get(entity_id, {})
            val = state.get("state")
            if val in (None, "unavailable", "unknown", ""):
                return default if default != 0.0 else None
            try:
                return float(val) * multiplier
            except (ValueError, TypeError):
                return default

        def get_str(entity_id: str, default: str = "") -> str:
            state = states.get(entity_id, {})
            val = state.get("state")
            if val in (None, "unavailable", "unknown"):
                return default
            return str(val)

        def get_int(entity_id: str, default: int = 0) -> int:
            val = get_num(entity_id, float(default))
            return int(val) if val is not None else default

        def get_ev_state(entity_id: str, default: int = 128) -> int:
            """Get EV charger state from state_code attribute (ABB Terra returns string in state)."""
            state = states.get(entity_id, {})
            attrs = state.get("attributes", {})
            # ABB Terra AC returns numeric code in state_code attribute
            if "state_code" in attrs:
                try:
                    return int(attrs["state_code"])
                except (ValueError, TypeError):
                    pass
            # Fallback to parsing state value
            val = state.get("state")
            if val in (None, "unavailable", "unknown", ""):
                return default
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        return PowerInputs(
            # Power readings
            p1_power=get_num(e.p1, 0.0, self.units_p1),
            p1_return=get_num(e.p1_return, 0.0, self.units_p1),
            pv_power=get_num(e.pv, 0.0, self.units_pv),

            # Boiler
            boiler_switch=get_str(e.boiler_switch, "off"),
            boiler_power=get_num(e.boiler_power, 0.0),
            boiler_force=get_str(e.boiler_force, "off"),

            # Pool
            pool_season=get_str(e.pool_season, "off"),
            pool_power=get_num(e.pool_power, 0.0),
            pool_climate=get_str(e.pool_climate, "off"),
            pool_pump_switch=get_str(e.pool_pump, "on"),
            pool_pump_power=get_num(e.pool_pump_power, 0.0),
            pool_ambient_temp=get_num(e.pool_ambient_temp),

            # EV Charger
            ev_state=get_ev_state(e.ev_state, EVState.NO_CAR),
            ev_switch=get_str(e.ev_switch, "off"),
            ev_power=get_num(e.ev_power, 0.0),
            ev_limit=get_int(e.ev_limit, 6),

            # Heaters
            heater_right_switch=get_str(e.heater_right, "off"),
            heater_table_switch=get_str(e.heater_table, "off"),

            # AC Units
            ac_living_state=get_str(e.ac_living, "off"),
            ac_mancave_state=get_str(e.ac_mancave, "off"),
            ac_office_state=get_str(e.ac_office, "off"),
            ac_bedroom_state=get_str(e.ac_bedroom, "off"),
            ac_living_power=get_num(e.ac_living_power, 0.0),
            ac_office_power=get_num(e.ac_office_power, 0.0),

            # Temperatures
            temp_living=get_num(e.temp_living, 20.0),
            temp_bedroom=get_num(e.temp_bedroom, 20.0),
            temp_mancave=get_num(e.temp_mancave, 20.0),

            # Overrides
            ovr_ac_living=get_str(e.ovr_ac_living, ""),
            ovr_ac_bedroom=get_str(e.ovr_ac_bedroom, ""),
            ovr_ac_office=get_str(e.ovr_ac_office, ""),
            ovr_ac_mancave=get_str(e.ovr_ac_mancave, ""),
            ovr_pool=get_str(e.ovr_pool, ""),
            ovr_boiler=get_str(e.ovr_boiler, ""),
            ovr_ev=get_str(e.ovr_ev, ""),
            ovr_table_heater=get_str(e.ovr_table_heater, ""),

            # BMW Cars
            bmw_i5_battery=get_num(e.bmw_i5_battery),
            bmw_i5_range=get_num(e.bmw_i5_range),
            bmw_i5_location=get_str(e.bmw_i5_location, "unknown"),
            bmw_ix1_battery=get_num(e.bmw_ix1_battery),
            bmw_ix1_range=get_num(e.bmw_ix1_range),
            bmw_ix1_location=get_str(e.bmw_ix1_location, "unknown"),
        )
