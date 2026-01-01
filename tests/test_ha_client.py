"""Integration tests for Home Assistant client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from app.ha_client import HAClient
from app.config import Config, HAConfig
from app.models import PowerInputs, EVState


@pytest.fixture
def ha_config():
    """Test configuration for HA client."""
    config = Config()
    config.home_assistant = HAConfig(
        url="https://test.local:8123",
        token="test_token_12345",
        verify_ssl=False
    )
    return config


@pytest.fixture
def ha_client(ha_config):
    """Create HA client instance."""
    return HAClient(ha_config)


@pytest.fixture
def mock_session():
    """Create a mock aiohttp session."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.close = AsyncMock()
    session.closed = False  # Session is not closed
    session.get = MagicMock()
    session.post = MagicMock()
    return session


@pytest.fixture
def connected_client(ha_client, mock_session):
    """Create HA client with mock session already connected."""
    ha_client._session = mock_session
    ha_client._connected = True
    return ha_client


@pytest.fixture
def sample_states():
    """Sample entity states from HA API."""
    return [
        {
            "entity_id": "sensor.electricity_currently_delivered",
            "state": "1.5",
            "attributes": {"unit_of_measurement": "kW"}
        },
        {
            "entity_id": "sensor.electricity_currently_returned",
            "state": "0.0",
            "attributes": {"unit_of_measurement": "kW"}
        },
        {
            "entity_id": "sensor.solaredge_i1_ac_power",
            "state": "2500",
            "attributes": {"unit_of_measurement": "W"}
        },
        {
            "entity_id": "switch.storage_boiler",
            "state": "on",
            "attributes": {}
        },
        {
            "entity_id": "sensor.storage_boiler_power",
            "state": "2450",
            "attributes": {}
        },
        {
            "entity_id": "switch.abb_terra_ac_charging",
            "state": "off",
            "attributes": {}
        },
        {
            "entity_id": "sensor.abb_terra_ac_charging_state",
            "state": "Ready",
            "attributes": {"state_code": 129}
        },
        {
            "entity_id": "number.abb_terra_ac_current_limit",
            "state": "10",
            "attributes": {}
        },
        {
            "entity_id": "input_select.pm_override_boiler",
            "state": "auto",
            "attributes": {}
        }
    ]


class TestHAClientConnection:
    """Test HA client connection management."""

    @pytest.mark.asyncio
    async def test_connect_creates_session(self, ha_client):
        """Connect should create an aiohttp session."""
        with patch('aiohttp.TCPConnector'):
            with patch('aiohttp.ClientSession') as mock_client_session:
                mock_session = AsyncMock()
                mock_client_session.return_value = mock_session

                await ha_client.connect()

                assert ha_client._session is mock_session
                mock_client_session.assert_called_once()

                # Clean up
                ha_client._session = None

    @pytest.mark.asyncio
    async def test_close_clears_session(self, ha_client, mock_session):
        """Close should clear the session."""
        ha_client._session = mock_session

        await ha_client.close()

        assert ha_client._session is None
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, ha_client):
        """Test async context manager protocol."""
        with patch('aiohttp.TCPConnector'):
            with patch('aiohttp.ClientSession') as mock_client_session:
                mock_session = AsyncMock()
                mock_session.close = AsyncMock()
                mock_client_session.return_value = mock_session

                async with ha_client as client:
                    assert client._session is mock_session

                assert ha_client._session is None


class TestGetAllStates:
    """Test get_all_states() method."""

    @pytest.mark.asyncio
    async def test_get_all_states_returns_parsed_states(self, ha_client, mock_session, sample_states):
        """get_all_states() should return dict mapping entity_id to state object."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value=sample_states)

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.get = AsyncMock(return_value=mock_response)

        result = await ha_client.get_all_states()

        assert isinstance(result, dict)
        assert "sensor.electricity_currently_delivered" in result
        assert result["sensor.electricity_currently_delivered"]["state"] == "1.5"
        assert "switch.storage_boiler" in result
        assert result["switch.storage_boiler"]["state"] == "on"

    @pytest.mark.asyncio
    async def test_get_all_states_calls_correct_endpoint(
        self, ha_client, mock_session, sample_states
    ):
        """get_all_states() should call /api/states endpoint."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value=sample_states)

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.get = AsyncMock(return_value=mock_response)

        await ha_client.get_all_states()

        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert "https://test.local:8123/api/states" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_all_states_raises_when_not_connected(self, ha_client):
        """get_all_states() should raise RuntimeError when not connected."""
        with pytest.raises(RuntimeError, match="Client not connected"):
            await ha_client.get_all_states()


class TestTurnOnOff:
    """Test turn_on() and turn_off() methods."""

    @pytest.mark.asyncio
    async def test_turn_on_calls_correct_endpoint(self, ha_client, mock_session):
        """turn_on() should call the correct service endpoint."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        result = await ha_client.turn_on("switch.storage_boiler")

        assert result is True
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        url = call_args[0][0]
        assert url == "https://test.local:8123/api/services/switch/turn_on"

    @pytest.mark.asyncio
    async def test_turn_off_calls_correct_endpoint(self, ha_client, mock_session):
        """turn_off() should call the correct service endpoint."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        result = await ha_client.turn_off("switch.storage_boiler")

        assert result is True
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        url = call_args[0][0]
        assert url == "https://test.local:8123/api/services/switch/turn_off"

    @pytest.mark.asyncio
    async def test_turn_on_extracts_domain_from_entity_id(self, ha_client, mock_session):
        """turn_on() should extract domain from entity_id for service call."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        await ha_client.turn_on("light.living_room")

        call_args = mock_session.post.call_args
        url = call_args[0][0]
        assert url == "https://test.local:8123/api/services/light/turn_on"

    @pytest.mark.asyncio
    async def test_turn_on_includes_entity_id_in_payload(self, ha_client, mock_session):
        """turn_on() should include entity_id in the request payload."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        await ha_client.turn_on("switch.storage_boiler")

        call_args = mock_session.post.call_args
        assert call_args.kwargs["json"]["entity_id"] == "switch.storage_boiler"


class TestSetNumber:
    """Test set_number() method."""

    @pytest.mark.asyncio
    async def test_set_number_calls_correct_endpoint(self, ha_client, mock_session):
        """set_number() should call number.set_value service."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        result = await ha_client.set_number("number.abb_terra_ac_current_limit", 12)

        assert result is True
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        url = call_args[0][0]
        assert url == "https://test.local:8123/api/services/number/set_value"

    @pytest.mark.asyncio
    async def test_set_number_includes_value_in_payload(self, ha_client, mock_session):
        """set_number() should include value in the request payload."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        await ha_client.set_number("number.abb_terra_ac_current_limit", 16)

        call_args = mock_session.post.call_args
        entity_id = call_args.kwargs["json"]["entity_id"]
        assert entity_id == "number.abb_terra_ac_current_limit"
        assert call_args.kwargs["json"]["value"] == 16


class TestParseInputs:
    """Test parse_inputs() method."""

    def test_parse_inputs_returns_power_inputs(self, ha_client, sample_states):
        """parse_inputs() should return PowerInputs object."""
        states_dict = {s["entity_id"]: s for s in sample_states}

        result = ha_client.parse_inputs(states_dict)

        assert isinstance(result, PowerInputs)

    def test_parse_inputs_parses_power_values(self, ha_client, sample_states):
        """parse_inputs() should correctly parse power sensor values."""
        states_dict = {s["entity_id"]: s for s in sample_states}

        result = ha_client.parse_inputs(states_dict)

        # P1 power: 1.5 kW * 1000 (units_p1) = 1500 W
        assert result.p1_power == 1500.0
        # PV power: 2500 W * 1 (units_pv) = 2500 W
        assert result.pv_power == 2500.0

    def test_parse_inputs_parses_switch_states(self, ha_client, sample_states):
        """parse_inputs() should correctly parse switch states."""
        states_dict = {s["entity_id"]: s for s in sample_states}

        result = ha_client.parse_inputs(states_dict)

        assert result.boiler_switch == "on"
        assert result.ev_switch == "off"

    def test_parse_inputs_parses_ev_state_from_state_code(self, ha_client, sample_states):
        """parse_inputs() should parse EV state from state_code attribute."""
        states_dict = {s["entity_id"]: s for s in sample_states}

        result = ha_client.parse_inputs(states_dict)

        # state_code: 129 = EVState.READY
        assert result.ev_state == EVState.READY

    def test_parse_inputs_parses_override_values(self, ha_client, sample_states):
        """parse_inputs() should correctly parse override input_select values."""
        states_dict = {s["entity_id"]: s for s in sample_states}

        result = ha_client.parse_inputs(states_dict)

        assert result.ovr_boiler == "auto"

    def test_parse_inputs_handles_missing_entities(self, ha_client):
        """parse_inputs() should return defaults for missing entities."""
        empty_states = {}

        result = ha_client.parse_inputs(empty_states)

        # Should return defaults (None for optional numeric, defaults for others)
        # Note: get_num returns None when entity missing and default is 0.0
        assert result.p1_power is None
        assert result.boiler_switch == "off"
        assert result.ev_state == EVState.NO_CAR

    def test_parse_inputs_handles_unavailable_entities(self, ha_client):
        """parse_inputs() should handle 'unavailable' entity states."""
        states = {
            "sensor.electricity_currently_delivered": {
                "entity_id": "sensor.electricity_currently_delivered",
                "state": "unavailable",
                "attributes": {}
            },
            "switch.storage_boiler": {
                "entity_id": "switch.storage_boiler",
                "state": "unavailable",
                "attributes": {}
            }
        }

        result = ha_client.parse_inputs(states)

        # Should return defaults for unavailable entities
        # Note: get_num returns None when state is unavailable and default is 0.0
        assert result.p1_power is None
        assert result.boiler_switch == "off"

    def test_parse_inputs_handles_unknown_entities(self, ha_client):
        """parse_inputs() should handle 'unknown' entity states."""
        states = {
            "sensor.electricity_currently_delivered": {
                "entity_id": "sensor.electricity_currently_delivered",
                "state": "unknown",
                "attributes": {}
            }
        }

        result = ha_client.parse_inputs(states)

        # get_num returns None when state is unknown and default is 0.0
        assert result.p1_power is None

    def test_parse_inputs_handles_invalid_numeric_values(self, ha_client):
        """parse_inputs() should handle non-numeric values in numeric sensors."""
        states = {
            "sensor.electricity_currently_delivered": {
                "entity_id": "sensor.electricity_currently_delivered",
                "state": "not_a_number",
                "attributes": {}
            }
        }

        result = ha_client.parse_inputs(states)

        assert result.p1_power == 0.0

    def test_parse_inputs_handles_empty_string_state(self, ha_client):
        """parse_inputs() should handle empty string states."""
        states = {
            "sensor.electricity_currently_delivered": {
                "entity_id": "sensor.electricity_currently_delivered",
                "state": "",
                "attributes": {}
            }
        }

        result = ha_client.parse_inputs(states)

        # get_num returns None when state is empty string and default is 0.0
        assert result.p1_power is None

    def test_parse_inputs_applies_unit_multipliers(self, ha_client):
        """parse_inputs() should apply correct unit multipliers."""
        states = {
            # P1 uses kW (multiplied by 1000)
            "sensor.electricity_currently_delivered": {
                "entity_id": "sensor.electricity_currently_delivered",
                "state": "2.5",
                "attributes": {}
            },
            # PV uses W (multiplied by 1)
            "sensor.solaredge_i1_ac_power": {
                "entity_id": "sensor.solaredge_i1_ac_power",
                "state": "3000",
                "attributes": {}
            }
        }

        result = ha_client.parse_inputs(states)

        # P1: 2.5 kW * 1000 = 2500 W
        assert result.p1_power == 2500.0
        # PV: 3000 W * 1 = 3000 W
        assert result.pv_power == 3000.0


class TestErrorHandling:
    """Test error handling when HA is unreachable or entity doesn't exist."""

    @pytest.mark.asyncio
    async def test_get_all_states_raises_on_connection_error(
        self, ha_client, mock_session
    ):
        """get_all_states() should propagate connection errors after retries."""
        from app.ha_client import HAConnectionError

        ha_client._session = mock_session
        ha_client._connected = True
        # AsyncMock that raises on await
        mock_session.get = AsyncMock(
            side_effect=aiohttp.ClientError("Connection refused")
        )
        # Mock connect to prevent actual reconnection during retry
        ha_client.connect = AsyncMock()

        # With retry logic, it now raises HAConnectionError after retries
        with pytest.raises(HAConnectionError):
            await ha_client.get_all_states()

    @pytest.mark.asyncio
    async def test_get_all_states_raises_on_http_error(
        self, ha_client, mock_session
    ):
        """get_all_states() should raise on HTTP errors."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=500,
                message="Internal Server Error"
            )
        )

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.get = AsyncMock(return_value=mock_response)

        with pytest.raises(aiohttp.ClientResponseError):
            await ha_client.get_all_states()

    @pytest.mark.asyncio
    async def test_get_state_returns_none_for_missing_entity(
        self, ha_client, mock_session
    ):
        """get_state() should return None for 404 responses."""
        mock_response = AsyncMock()
        mock_response.status = 404

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.get = AsyncMock(return_value=mock_response)

        result = await ha_client.get_state("sensor.nonexistent_entity")

        assert result is None

    @pytest.mark.asyncio
    async def test_turn_on_raises_on_connection_error(
        self, ha_client, mock_session
    ):
        """turn_on() should propagate connection errors after retries."""
        from app.ha_client import HAConnectionError

        ha_client._session = mock_session
        ha_client._connected = True
        # AsyncMock that raises on await
        mock_session.post = AsyncMock(
            side_effect=aiohttp.ClientError("Connection refused")
        )
        # Mock connect to prevent actual reconnection during retry
        ha_client.connect = AsyncMock()

        # With retry logic, it now raises HAConnectionError after retries
        with pytest.raises(HAConnectionError):
            await ha_client.turn_on("switch.storage_boiler")

    @pytest.mark.asyncio
    async def test_call_service_raises_when_not_connected(self, ha_client):
        """call_service() should raise RuntimeError when not connected."""
        with pytest.raises(RuntimeError, match="Client not connected"):
            await ha_client.call_service("switch", "turn_on", "switch.test")

    @pytest.mark.asyncio
    async def test_turn_off_raises_on_http_error(self, ha_client, mock_session):
        """turn_off() should raise on HTTP errors."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=401,
                message="Unauthorized"
            )
        )

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        with pytest.raises(aiohttp.ClientResponseError):
            await ha_client.turn_off("switch.storage_boiler")


class TestGetState:
    """Test get_state() method for single entity retrieval."""

    @pytest.mark.asyncio
    async def test_get_state_returns_entity_state(self, ha_client, mock_session):
        """get_state() should return the entity state dict."""
        expected_state = {
            "entity_id": "sensor.test",
            "state": "42",
            "attributes": {"unit": "W"}
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value=expected_state)

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.get = AsyncMock(return_value=mock_response)

        result = await ha_client.get_state("sensor.test")

        assert result == expected_state

    @pytest.mark.asyncio
    async def test_get_state_calls_correct_endpoint(self, ha_client, mock_session):
        """get_state() should call the correct API endpoint."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value={})

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.get = AsyncMock(return_value=mock_response)

        await ha_client.get_state("sensor.electricity_currently_delivered")

        call_args = mock_session.get.call_args
        expected_url = "api/states/sensor.electricity_currently_delivered"
        assert expected_url in str(call_args)

    @pytest.mark.asyncio
    async def test_get_state_raises_when_not_connected(self, ha_client):
        """get_state() should raise RuntimeError when not connected."""
        with pytest.raises(RuntimeError, match="Client not connected"):
            await ha_client.get_state("sensor.test")

    @pytest.mark.asyncio
    async def test_get_state_raises_on_non_404_error(self, ha_client, mock_session):
        """get_state() should raise on non-404 HTTP errors."""
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=500,
                message="Internal Server Error"
            )
        )

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.get = AsyncMock(return_value=mock_response)

        with pytest.raises(aiohttp.ClientResponseError):
            await ha_client.get_state("sensor.test")


class TestSetClimate:
    """Test set_climate() method."""

    @pytest.mark.asyncio
    async def test_set_climate_off_calls_turn_off(self, ha_client, mock_session):
        """set_climate() with hvac_mode='off' should call climate.turn_off."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        result = await ha_client.set_climate("climate.living", hvac_mode="off")

        assert result is True
        call_args = mock_session.post.call_args
        assert "climate/turn_off" in str(call_args)

    @pytest.mark.asyncio
    async def test_set_climate_heat_calls_set_hvac_mode(
        self, ha_client, mock_session
    ):
        """set_climate() with hvac_mode='heat' should call climate.set_hvac_mode."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        result = await ha_client.set_climate(
            "climate.living", hvac_mode="heat", temperature=22
        )

        assert result is True
        call_args = mock_session.post.call_args
        assert "climate/set_hvac_mode" in str(call_args)
        assert call_args.kwargs["json"]["hvac_mode"] == "heat"
        assert call_args.kwargs["json"]["temperature"] == 22


class TestInputText:
    """Test set_input_text() method."""

    @pytest.mark.asyncio
    async def test_set_input_text_calls_correct_service(
        self, ha_client, mock_session
    ):
        """set_input_text() should call input_text.set_value service."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        result = await ha_client.set_input_text(
            "input_text.power_manager_status", "Running OK"
        )

        assert result is True
        call_args = mock_session.post.call_args
        assert "input_text/set_value" in str(call_args)
        assert call_args.kwargs["json"]["value"] == "Running OK"

    @pytest.mark.asyncio
    async def test_set_input_text_truncates_long_values(
        self, ha_client, mock_session
    ):
        """set_input_text() should truncate values longer than 255 characters."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        ha_client._session = mock_session
        ha_client._connected = True
        mock_session.post = AsyncMock(return_value=mock_response)

        long_value = "x" * 300  # 300 characters, should be truncated to 255

        await ha_client.set_input_text("input_text.test", long_value)

        call_args = mock_session.post.call_args
        assert len(call_args.kwargs["json"]["value"]) == 255
