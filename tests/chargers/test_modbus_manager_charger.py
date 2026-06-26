"""Tests for the Modbus Manager charger implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity_registry import RegistryEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.evse_load_balancer.chargers.charger import PhaseMode
from custom_components.evse_load_balancer.chargers.modbus_manager_charger import (
    DEFAULT_MAX_CURRENT,
    DEFAULT_MIN_CURRENT,
    ModbusManagerCharger,
)
from custom_components.evse_load_balancer.const import (
    CHARGER_DOMAIN_MODBUS_MANAGER,
    Phase,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.fixture
def mock_config_entry():
    return MockConfigEntry(
        domain="evse_load_balancer",
        title="EM2GO Test Charger",
        data={"charger_type": "modbus_manager"},
        unique_id="test_em2go_charger",
    )


@pytest.fixture
def mock_device_entry():
    device_entry = MagicMock(spec=DeviceEntry)
    device_entry.id = "em2go_device_abc123"
    device_entry.identifiers = {
        (CHARGER_DOMAIN_MODBUS_MANAGER, "modbus_manager_127.0.0.1_slave_255")
    }
    device_entry.model = "EM2GO Home (Slave 255)"
    return device_entry


@pytest.fixture
def modbus_manager_charger(mock_hass, mock_config_entry, mock_device_entry):
    with (
        patch(
            "custom_components.evse_load_balancer.chargers.modbus_manager_charger."
            "ModbusManagerCharger.refresh_entities"
        ),
        patch(
            "custom_components.evse_load_balancer.chargers.modbus_manager_charger."
            "ModbusManagerCharger._resolve_entity_key",
            return_value="modbus_current_limit",
        ),
    ):
        charger = ModbusManagerCharger(
            hass=mock_hass,
            config_entry=mock_config_entry,
            device_entry=mock_device_entry,
        )
        charger._get_entity_state_by_key = MagicMock()
        charger._get_entity_id_by_key = MagicMock(
            return_value="number.em2go_modbus_current_limit"
        )
        charger._get_limit_bounds = MagicMock(
            return_value=(DEFAULT_MIN_CURRENT, DEFAULT_MAX_CURRENT)
        )
        return charger


def test_is_charger_device_true(mock_device_entry):
    assert ModbusManagerCharger.is_charger_device(mock_device_entry)


def test_is_charger_device_false_wrong_domain():
    device_entry = MagicMock(spec=DeviceEntry)
    device_entry.identifiers = {("other_domain", "something")}
    assert not ModbusManagerCharger.is_charger_device(device_entry)


def test_supports_device_true(mock_hass, mock_device_entry):
    limit_entry = MagicMock(spec=RegistryEntry)
    limit_entry.domain = "number"
    limit_entry.unique_id = "em2go_modbus_current_limit"

    with patch(
        "custom_components.evse_load_balancer.chargers.modbus_manager_charger.er.async_get"
    ) as mock_er_get:
        mock_er_get.return_value.entities.get_entries_for_device_id.return_value = [
            limit_entry
        ]
        assert ModbusManagerCharger.supports_device(mock_hass, mock_device_entry)


def test_supports_device_false_inverter(mock_hass):
    device_entry = MagicMock(spec=DeviceEntry)
    device_entry.id = "inverter_device"
    device_entry.identifiers = {
        (CHARGER_DOMAIN_MODBUS_MANAGER, "modbus_manager_127.0.0.1_502_slave_1")
    }
    power_entry = MagicMock(spec=RegistryEntry)
    power_entry.domain = "sensor"
    power_entry.unique_id = "sg_total_dc_power"

    with patch(
        "custom_components.evse_load_balancer.chargers.modbus_manager_charger.er.async_get"
    ) as mock_er_get:
        mock_er_get.return_value.entities.get_entries_for_device_id.return_value = [
            power_entry
        ]
        assert not ModbusManagerCharger.supports_device(mock_hass, device_entry)


def test_supports_device_heidelberg_key(mock_hass, mock_device_entry):
    limit_entry = MagicMock(spec=RegistryEntry)
    limit_entry.domain = "number"
    limit_entry.unique_id = "hec_max_current"

    with patch(
        "custom_components.evse_load_balancer.chargers.modbus_manager_charger.er.async_get"
    ) as mock_er_get:
        mock_er_get.return_value.entities.get_entries_for_device_id.return_value = [
            limit_entry
        ]
        assert ModbusManagerCharger.supports_device(mock_hass, mock_device_entry)


@pytest.mark.asyncio
async def test_set_current_limit_clamps_minimum(modbus_manager_charger, mock_hass):
    await modbus_manager_charger.set_current_limit(
        {Phase.L1: 0, Phase.L2: 0, Phase.L3: 0}
    )
    mock_hass.services.async_call.assert_called_once_with(
        domain="number",
        service="set_value",
        service_data={
            "entity_id": "number.em2go_modbus_current_limit",
            "value": DEFAULT_MIN_CURRENT,
        },
        blocking=True,
    )


@pytest.mark.asyncio
async def test_set_current_limit_uses_minimum_phase(modbus_manager_charger, mock_hass):
    test_limits = {Phase.L1: 16, Phase.L2: 14, Phase.L3: 15}
    await modbus_manager_charger.set_current_limit(test_limits)
    mock_hass.services.async_call.assert_called_once_with(
        domain="number",
        service="set_value",
        service_data={
            "entity_id": "number.em2go_modbus_current_limit",
            "value": 14,
        },
        blocking=True,
    )


@pytest.mark.asyncio
async def test_set_current_limit_clamps_maximum(modbus_manager_charger, mock_hass):
    await modbus_manager_charger.set_current_limit(
        {Phase.L1: 40, Phase.L2: 40, Phase.L3: 40}
    )
    mock_hass.services.async_call.assert_called_once_with(
        domain="number",
        service="set_value",
        service_data={
            "entity_id": "number.em2go_modbus_current_limit",
            "value": DEFAULT_MAX_CURRENT,
        },
        blocking=True,
    )


def test_get_current_limit_success(modbus_manager_charger):
    modbus_manager_charger._get_entity_state_by_key.return_value = "28.0"
    result = modbus_manager_charger.get_current_limit()
    assert result == {Phase.L1: 28, Phase.L2: 28, Phase.L3: 28}


def test_get_current_limit_missing_entity(modbus_manager_charger):
    modbus_manager_charger._get_entity_state_by_key.return_value = None
    assert modbus_manager_charger.get_current_limit() is None


def test_get_max_current_limit_from_entity(modbus_manager_charger):
    modbus_manager_charger._get_entity_state_by_key.side_effect = ["32.0", None]
    result = modbus_manager_charger.get_max_current_limit()
    assert result == {Phase.L1: 32, Phase.L2: 32, Phase.L3: 32}


def test_get_max_current_limit_fallback(modbus_manager_charger):
    modbus_manager_charger._get_entity_state_by_key.return_value = None
    result = modbus_manager_charger.get_max_current_limit()
    assert result == {
        Phase.L1: int(DEFAULT_MAX_CURRENT),
        Phase.L2: int(DEFAULT_MAX_CURRENT),
        Phase.L3: int(DEFAULT_MAX_CURRENT),
    }


def test_car_connected_binary_sensor(modbus_manager_charger):
    modbus_manager_charger._get_entity_id_by_key = MagicMock(
        return_value="binary_sensor.em2go_vehicle_connected"
    )
    modbus_manager_charger._get_entity_state = MagicMock(return_value="on")
    assert modbus_manager_charger.car_connected() is True


def test_car_connected_status_sensor(modbus_manager_charger):
    modbus_manager_charger._get_binary_state = MagicMock(return_value=None)
    modbus_manager_charger._get_status_text = MagicMock(return_value="connected")
    assert modbus_manager_charger.car_connected() is True


def test_is_charging_binary_sensor(modbus_manager_charger):
    modbus_manager_charger._get_binary_state = MagicMock(return_value=True)
    assert modbus_manager_charger.is_charging() is True


def test_set_phase_mode_noop(modbus_manager_charger):
    modbus_manager_charger.set_phase_mode(PhaseMode.SINGLE, Phase.L1)


def test_set_phase_mode_invalid(modbus_manager_charger):
    with pytest.raises(ValueError) as excinfo:
        modbus_manager_charger.set_phase_mode("invalid_mode", Phase.L1)
    assert "Invalid mode" in str(excinfo.value)


def test_current_change_settle_time(modbus_manager_charger):
    assert modbus_manager_charger.current_change_settle_time == 20
