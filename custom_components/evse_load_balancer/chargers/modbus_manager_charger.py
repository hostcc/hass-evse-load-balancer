"""Modbus Manager EV charger implementation."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from ..const import CHARGER_DOMAIN_MODBUS_MANAGER, Phase  # noqa: TID252
from ..ha_device import HaDevice  # noqa: TID252
from .charger import Charger, PhaseMode

_LOGGER = logging.getLogger(__name__)

# Writable number entities used for load-balancing current (template unique_id suffixes).
CURRENT_LIMIT_KEYS: tuple[str, ...] = (
    "modbus_current_limit",  # EM2GO Home
    "max_current",  # Heidelberg Energy Control
    "output_current",  # Sungrow AC011E
    "charging_current_setpoint",  # Victron EV Charging Station
    "max_current_phase_1",  # Compleo eBox (single-phase setups)
)

MAX_CURRENT_READ_KEYS: tuple[str, ...] = (
    "evse_max_current",
    "hw_max_current",
    "charging_current_maximum",
    "actual_max_current",
)

STATUS_SENSOR_KEYS: tuple[str, ...] = (
    "evse_state",
    "status",
    "charging_status_raw",
    "ocpp_state",
)

VEHICLE_CONNECTED_BINARY_KEYS: tuple[str, ...] = (
    "vehicle_connected",
    "connected",
    "cable_connected",
)

CHARGING_BINARY_KEYS: tuple[str, ...] = ("charging_active",)

# Fallback when status is a mapped string sensor (lowercase substring match).
CONNECTED_STATUS_MARKERS: tuple[str, ...] = (
    "connected",
    "charging",
    "starting",
    "ready",
    "plugged",
    "b1",
    "b2",
    "c1",
    "c2",
)

CHARGING_STATUS_MARKERS: tuple[str, ...] = ("charging",)

DEFAULT_MIN_CURRENT = 6.0
DEFAULT_MAX_CURRENT = 32.0


class ModbusManagerCharger(HaDevice, Charger):
    """Charger adapter for ha-modbus-manager ``ev_charger`` templates."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
    ) -> None:
        """Initialize the Modbus Manager charger adapter."""
        HaDevice.__init__(self, hass, device_entry)
        Charger.__init__(self, hass, config_entry, device_entry)
        self.refresh_entities()
        self._current_limit_key = self._resolve_entity_key(
            CURRENT_LIMIT_KEYS, domain="number"
        )
        if self._current_limit_key is None:
            msg = (
                "Modbus Manager device has no supported current-limit number entity. "
                f"Expected unique_id suffix in {CURRENT_LIMIT_KEYS}."
            )
            raise ValueError(msg)

    @staticmethod
    def is_charger_device(device: DeviceEntry) -> bool:
        """True for modbus_manager devices (use supports_device for EV capability)."""
        return any(
            id_domain == CHARGER_DOMAIN_MODBUS_MANAGER
            for id_domain, _ in device.identifiers
        )

    @staticmethod
    def supports_device(hass: HomeAssistant, device: DeviceEntry) -> bool:
        """True when the device exposes a writable current-limit number entity."""
        if not ModbusManagerCharger.is_charger_device(device):
            return False
        registry = er.async_get(hass)
        entries = registry.entities.get_entries_for_device_id(
            device.id, include_disabled_entities=True
        )
        return ModbusManagerCharger._find_key_in_entries(
            entries, CURRENT_LIMIT_KEYS, domain="number"
        ) is not None

    @staticmethod
    def _find_key_in_entries(
        entries: list, key_suffixes: tuple[str, ...], domain: str | None = None
    ) -> str | None:
        for key in key_suffixes:
            suffix = f"_{key}".lower()
            for entry in entries:
                if domain is not None and entry.domain != domain:
                    continue
                unique_id = (entry.unique_id or "").lower()
                if unique_id.endswith(suffix):
                    return key
        return None

    def _resolve_entity_key(
        self, key_suffixes: tuple[str, ...], domain: str | None = None
    ) -> str | None:
        return self._find_key_in_entries(self.entities, key_suffixes, domain)

    def _get_limit_bounds(self) -> tuple[float, float]:
        """Read min/max from the HA number entity attributes when available."""
        entity_id = self._get_entity_id_by_key(self._current_limit_key)
        attrs = self._get_entity_state_attrs(entity_id) or {}
        min_value = float(attrs.get("min", DEFAULT_MIN_CURRENT))
        max_value = float(attrs.get("max", DEFAULT_MAX_CURRENT))
        return min_value, max_value

    @property
    def current_change_settle_time(self) -> int:
        """Allow Modbus writes and post-write settle before the next change."""
        return 20

    async def async_setup(self) -> None:
        """Set up the charger."""

    def set_phase_mode(self, mode: PhaseMode, _phase: Phase | None = None) -> None:
        """No-op — phase switching is template-specific and not handled here."""
        if mode not in PhaseMode:
            msg = "Invalid mode. Must be 'single' or 'multi'."
            raise ValueError(msg)

    async def set_current_limit(self, limit: dict[Phase, int]) -> None:
        """Set charge current via the modbus-manager number entity."""
        limit_entity_id = self._get_entity_id_by_key(self._current_limit_key)
        min_value, max_value = self._get_limit_bounds()
        requested = float(min(limit.values())) if limit else min_value
        value = max(min_value, min(requested, max_value))

        await self.hass.services.async_call(
            domain="number",
            service="set_value",
            service_data={
                "entity_id": limit_entity_id,
                "value": value,
            },
            blocking=True,
        )

    def get_current_limit(self) -> dict[Phase, int] | None:
        """Return the configured charge current limit."""
        state = self._get_entity_state_by_key(self._current_limit_key)
        if state is None:
            _LOGGER.warning(
                "Current limit not available for key '%s'.",
                self._current_limit_key,
            )
            return None
        return dict.fromkeys(Phase, int(float(state)))

    def get_max_current_limit(self) -> dict[Phase, int] | None:
        """Return hardware/configured maximum charge current when exposed."""
        for key in MAX_CURRENT_READ_KEYS:
            state = self._get_entity_state_by_key(key)
            if state is not None:
                return dict.fromkeys(Phase, int(float(state)))
        _, max_value = self._get_limit_bounds()
        return dict.fromkeys(Phase, int(max_value))

    def has_synced_phase_limits(self) -> bool:
        """Single limit entity applies to all phases on supported templates."""
        return True

    def _get_binary_state(self, key_suffixes: tuple[str, ...]) -> bool | None:
        for key in key_suffixes:
            try:
                entity_id = self._get_entity_id_by_key(key)
            except ValueError:
                continue
            state = self._get_entity_state(entity_id)
            if state is not None:
                return str(state).lower() in ("on", "true", "1")
        return None

    def _get_status_text(self) -> str | None:
        for key in STATUS_SENSOR_KEYS:
            try:
                state = self._get_entity_state_by_key(key)
            except ValueError:
                continue
            if state is not None:
                return str(state).lower()
        return None

    def _status_matches(self, markers: tuple[str, ...]) -> bool:
        status = self._get_status_text()
        if status is None:
            return False
        return any(marker in status for marker in markers)

    def car_connected(self) -> bool:
        """Car plugged in and EVSE ready or active."""
        binary = self._get_binary_state(VEHICLE_CONNECTED_BINARY_KEYS)
        if binary is not None:
            return binary
        if self._get_binary_state(CHARGING_BINARY_KEYS):
            return True
        return self._status_matches(CONNECTED_STATUS_MARKERS)

    def can_charge(self) -> bool:
        """Car connected and EVSE ready or delivering."""
        if self._get_binary_state(CHARGING_BINARY_KEYS):
            return True
        binary = self._get_binary_state(VEHICLE_CONNECTED_BINARY_KEYS)
        if binary is not None:
            return binary
        return self._status_matches(CONNECTED_STATUS_MARKERS)

    def is_charging(self) -> bool:
        """EVSE is actively charging."""
        if self._get_binary_state(CHARGING_BINARY_KEYS):
            return True
        return self._status_matches(CHARGING_STATUS_MARKERS)

    async def async_unload(self) -> None:
        """Unload the charger."""
