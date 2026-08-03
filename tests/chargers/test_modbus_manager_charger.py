"""Tests for the Modbus Manager charger implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity_registry import RegistryEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.evse_load_balancer.chargers.charger import Charger, PhaseMode
from custom_components.evse_load_balancer.chargers.modbus_manager_charger import (
    DEFAULT_MAX_CURRENT,
    DEFAULT_MIN_CURRENT,
    ModbusManagerCharger,
)
from custom_components.evse_load_balancer.const import (
    CHARGER_DOMAIN_MODBUS_MANAGER,
    Phase,
)
from custom_components.evse_load_balancer.ha_device import HaDevice


def _registry_entry(
    entity_id: str, unique_id: str, domain: str, device_id: str = "dev"
) -> MagicMock:
    entry = MagicMock(spec=RegistryEntry)
    entry.entity_id = entity_id
    entry.unique_id = unique_id
    entry.domain = domain
    entry.device_id = device_id
    entry.disabled = False
    return entry


def _device_entry(
    device_id: str = "em2go_device_abc123",
    name: str = "nh19",
) -> MagicMock:
    device_entry = MagicMock(spec=DeviceEntry)
    device_entry.id = device_id
    device_entry.name = name
    device_entry.name_by_user = None
    device_entry.identifiers = {
        (CHARGER_DOMAIN_MODBUS_MANAGER, f"modbus_manager_{device_id}")
    }
    device_entry.model = "EM2GO Home (Slave 255)"
    return device_entry


EM2GO1_ENTITIES = [
    _registry_entry(
        "number.em2go1_modbus_current_limit",
        "em2go1_modbus_current_limit",
        "number",
        "device_a",
    ),
    _registry_entry(
        "sensor.em2go1_evse_max_current",
        "em2go1_evse_max_current",
        "sensor",
        "device_a",
    ),
    _registry_entry(
        "sensor.em2go1_evse_state",
        "em2go1_evse_state",
        "sensor",
        "device_a",
    ),
    _registry_entry(
        "binary_sensor.em2go1_vehicle_connected",
        "em2go1_vehicle_connected",
        "binary_sensor",
        "device_a",
    ),
    _registry_entry(
        "binary_sensor.em2go1_charging_active",
        "em2go1_charging_active",
        "binary_sensor",
        "device_a",
    ),
]


def _build_charger(
    hass: MagicMock,
    config_entry: MockConfigEntry,
    device_entry: MagicMock,
    entities: list,
) -> ModbusManagerCharger:
    with patch(
        "custom_components.evse_load_balancer.chargers.modbus_manager_charger."
        "ModbusManagerCharger.refresh_entities"
    ):
        charger = ModbusManagerCharger.__new__(ModbusManagerCharger)
        HaDevice.__init__(charger, hass, device_entry)
        Charger.__init__(charger, hass, config_entry, device_entry)
        charger.entities = entities
        charger._current_limit_entity_id = charger._resolve_entity_id(
            ("modbus_current_limit",), domain="number"
        )
        charger._max_current_entity_id = charger._resolve_entity_id(
            ("evse_max_current", "hw_max_current")
        )
        charger._status_entity_id = charger._resolve_entity_id(
            ("evse_state",), domain="sensor"
        )
        charger._vehicle_connected_entity_id = charger._resolve_entity_id(
            ("vehicle_connected",), domain="binary_sensor"
        )
        charger._charging_active_entity_id = charger._resolve_entity_id(
            ("charging_active",), domain="binary_sensor"
        )
        charger._get_limit_bounds = MagicMock(
            return_value=(DEFAULT_MIN_CURRENT, DEFAULT_MAX_CURRENT)
        )
        return charger


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
    return _device_entry()


@pytest.fixture
def modbus_manager_charger(mock_hass, mock_config_entry):
    return _build_charger(
        mock_hass,
        mock_config_entry,
        _device_entry("device_a", "nh19"),
        EM2GO1_ENTITIES,
    )


def test_is_charger_device_true(mock_device_entry):
    assert ModbusManagerCharger.is_charger_device(mock_device_entry)


def test_is_charger_device_false_wrong_domain():
    device_entry = MagicMock(spec=DeviceEntry)
    device_entry.identifiers = {("other_domain", "something")}
    assert not ModbusManagerCharger.is_charger_device(device_entry)


def test_supports_device_true(mock_hass, mock_device_entry):
    limit_entry = _registry_entry(
        "number.em2go_modbus_current_limit",
        "em2go_modbus_current_limit",
        "number",
    )
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
    power_entry = _registry_entry(
        "sg_total_dc_power", "sg_total_dc_power", "sensor"
    )
    with patch(
        "custom_components.evse_load_balancer.chargers.modbus_manager_charger.er.async_get"
    ) as mock_er_get:
        mock_er_get.return_value.entities.get_entries_for_device_id.return_value = [
            power_entry
        ]
        assert not ModbusManagerCharger.supports_device(mock_hass, device_entry)


def test_supports_device_heidelberg_key(mock_hass, mock_device_entry):
    limit_entry = _registry_entry(
        "number.hec_max_current", "hec_max_current", "number"
    )
    with patch(
        "custom_components.evse_load_balancer.chargers.modbus_manager_charger.er.async_get"
    ) as mock_er_get:
        mock_er_get.return_value.entities.get_entries_for_device_id.return_value = [
            limit_entry
        ]
        assert ModbusManagerCharger.supports_device(mock_hass, mock_device_entry)


def test_find_prefers_exact_max_current_over_hw_max():
    entries = [
        _registry_entry(
            "sensor.hec_hw_max_current", "hec_hw_max_current", "sensor"
        ),
        _registry_entry("number.hec_max_current", "hec_max_current", "number"),
    ]
    entity_id = ModbusManagerCharger._find_entity_id_in_entries(
        entries, ("max_current", "hw_max_current"), domain="number"
    )
    assert entity_id == "number.hec_max_current"


def test_resolve_pins_em2go1_suffixes(modbus_manager_charger):
    assert (
        modbus_manager_charger._current_limit_entity_id
        == "number.em2go1_modbus_current_limit"
    )
    assert modbus_manager_charger._status_entity_id == "sensor.em2go1_evse_state"
    assert (
        modbus_manager_charger._max_current_entity_id
        == "sensor.em2go1_evse_max_current"
    )


@pytest.mark.asyncio
async def test_set_current_limit_uses_pinned_entity(modbus_manager_charger, mock_hass):
    await modbus_manager_charger.set_current_limit(
        {Phase.L1: 0, Phase.L2: 0, Phase.L3: 0}
    )
    mock_hass.services.async_call.assert_called_once_with(
        domain="number",
        service="set_value",
        service_data={
            "entity_id": "number.em2go1_modbus_current_limit",
            "value": DEFAULT_MIN_CURRENT,
        },
        blocking=True,
    )


@pytest.mark.asyncio
async def test_set_current_limit_uses_minimum_phase(modbus_manager_charger, mock_hass):
    await modbus_manager_charger.set_current_limit(
        {Phase.L1: 16, Phase.L2: 14, Phase.L3: 15}
    )
    mock_hass.services.async_call.assert_called_once_with(
        domain="number",
        service="set_value",
        service_data={
            "entity_id": "number.em2go1_modbus_current_limit",
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
            "entity_id": "number.em2go1_modbus_current_limit",
            "value": DEFAULT_MAX_CURRENT,
        },
        blocking=True,
    )


@pytest.mark.asyncio
async def test_two_chargers_do_not_cross_write(mock_hass, mock_config_entry):
    entities_a = EM2GO1_ENTITIES
    entities_b = [
        _registry_entry(
            "number.em2go2_modbus_current_limit",
            "em2go2_modbus_current_limit",
            "number",
            "device_b",
        ),
        _registry_entry(
            "sensor.em2go2_evse_state", "em2go2_evse_state", "sensor", "device_b"
        ),
    ]

    charger_a = _build_charger(
        mock_hass, mock_config_entry, _device_entry("device_a", "nh19"), entities_a
    )
    charger_b = _build_charger(
        mock_hass,
        mock_config_entry,
        _device_entry("device_b", "nh19 mobile"),
        entities_b,
    )

    assert charger_a._current_limit_entity_id == "number.em2go1_modbus_current_limit"
    assert charger_b._current_limit_entity_id == "number.em2go2_modbus_current_limit"
    assert charger_a._status_entity_id == "sensor.em2go1_evse_state"
    assert charger_b._status_entity_id == "sensor.em2go2_evse_state"

    await charger_b.set_current_limit({Phase.L1: 10, Phase.L2: 10, Phase.L3: 10})
    mock_hass.services.async_call.assert_called_once_with(
        domain="number",
        service="set_value",
        service_data={
            "entity_id": "number.em2go2_modbus_current_limit",
            "value": 10,
        },
        blocking=True,
    )


def test_get_current_limit_success(modbus_manager_charger):
    modbus_manager_charger._read_state = MagicMock(return_value="28.0")
    result = modbus_manager_charger.get_current_limit()
    assert result == {Phase.L1: 28, Phase.L2: 28, Phase.L3: 28}


def test_get_current_limit_missing_entity(modbus_manager_charger):
    modbus_manager_charger._read_state = MagicMock(return_value=None)
    assert modbus_manager_charger.get_current_limit() is None


def test_get_max_current_limit_from_entity(modbus_manager_charger):
    modbus_manager_charger._read_state = MagicMock(return_value="32.0")
    result = modbus_manager_charger.get_max_current_limit()
    assert result == {Phase.L1: 32, Phase.L2: 32, Phase.L3: 32}


def test_get_max_current_limit_fallback(modbus_manager_charger):
    modbus_manager_charger._max_current_entity_id = None
    modbus_manager_charger._read_state = MagicMock(return_value=None)
    result = modbus_manager_charger.get_max_current_limit()
    assert result == {
        Phase.L1: int(DEFAULT_MAX_CURRENT),
        Phase.L2: int(DEFAULT_MAX_CURRENT),
        Phase.L3: int(DEFAULT_MAX_CURRENT),
    }


def test_can_charge_standby(modbus_manager_charger):
    states = {
        "binary_sensor.em2go1_charging_active": "off",
        "binary_sensor.em2go1_vehicle_connected": "off",
        "sensor.em2go1_evse_state": "Standby",
    }
    modbus_manager_charger._read_state = MagicMock(
        side_effect=lambda eid: states.get(eid)
    )
    assert modbus_manager_charger.can_charge() is False
    assert modbus_manager_charger.is_charging() is False
    assert modbus_manager_charger.car_connected() is False


def test_can_charge_charging(modbus_manager_charger):
    states = {
        "binary_sensor.em2go1_charging_active": "on",
        "binary_sensor.em2go1_vehicle_connected": "on",
        "sensor.em2go1_evse_state": "Charging",
    }
    modbus_manager_charger._read_state = MagicMock(
        side_effect=lambda eid: states.get(eid)
    )
    assert modbus_manager_charger.can_charge() is True
    assert modbus_manager_charger.is_charging() is True
    assert modbus_manager_charger.car_connected() is True


def test_charging_end_can_charge_but_not_is_charging(modbus_manager_charger):
    states = {
        "binary_sensor.em2go1_charging_active": "off",
        "binary_sensor.em2go1_vehicle_connected": "on",
        "sensor.em2go1_evse_state": "Charging end",
    }
    modbus_manager_charger._read_state = MagicMock(
        side_effect=lambda eid: states.get(eid)
    )
    assert modbus_manager_charger.can_charge() is True
    assert modbus_manager_charger.car_connected() is True
    assert modbus_manager_charger.is_charging() is False


def test_charging_end_via_status_only(modbus_manager_charger):
    """Substring 'charging' must not make is_charging true for Charging end."""
    modbus_manager_charger._charging_active_entity_id = None
    modbus_manager_charger._vehicle_connected_entity_id = None
    modbus_manager_charger._read_state = MagicMock(return_value="Charging end")
    assert modbus_manager_charger.can_charge() is True
    assert modbus_manager_charger.is_charging() is False


def test_set_phase_mode_noop(modbus_manager_charger):
    modbus_manager_charger.set_phase_mode(PhaseMode.SINGLE, Phase.L1)


def test_set_phase_mode_invalid(modbus_manager_charger):
    with pytest.raises(ValueError) as excinfo:
        modbus_manager_charger.set_phase_mode("invalid_mode", Phase.L1)
    assert "Invalid mode" in str(excinfo.value)


def test_current_change_settle_time(modbus_manager_charger):
    assert modbus_manager_charger.current_change_settle_time == 20
