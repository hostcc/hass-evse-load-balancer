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

# Writable number entities used for load-balancing current (template unique_id
# suffixes). Longer keys are preferred when resolving.
CURRENT_LIMIT_KEYS: tuple[str, ...] = (
    "modbus_current_limit",  # EM2GO Home
    "charging_current_setpoint",  # Victron EV Charging Station
    "max_current_phase_1",  # Compleo eBox (single-phase setups)
    "output_current",  # Sungrow AC011E
    "max_current",  # Heidelberg Energy Control
)

MAX_CURRENT_READ_KEYS: tuple[str, ...] = (
    "charging_current_maximum",
    "evse_max_current",
    "actual_max_current",
    "hw_max_current",
)

STATUS_SENSOR_KEYS: tuple[str, ...] = (
    "charging_status_raw",
    "evse_state",
    "ocpp_state",
    "status",
)

VEHICLE_CONNECTED_BINARY_KEYS: tuple[str, ...] = (
    "vehicle_connected",
    "cable_connected",
    "connected",
)

CHARGING_BINARY_KEYS: tuple[str, ...] = ("charging_active",)

# Exact EVSE state strings (EM2GO template map and common synonyms).
CONNECTED_STATES: frozenset[str] = frozenset(
    {
        "connected",
        "starting",
        "charging",
        "charging end",
        "ready",
        "plugged",
        "b1",
        "b2",
        "c1",
        "c2",
    }
)

CHARGING_STATES: frozenset[str] = frozenset({"charging"})

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

        self._current_limit_entity_id = self._resolve_entity_id(
            CURRENT_LIMIT_KEYS, domain="number"
        )
        if self._current_limit_entity_id is None:
            msg = (
                "Modbus Manager device has no supported current-limit number entity. "
                f"Expected unique_id suffix in {CURRENT_LIMIT_KEYS}."
            )
            raise ValueError(msg)

        self._max_current_entity_id = self._resolve_entity_id(MAX_CURRENT_READ_KEYS)
        self._status_entity_id = self._resolve_entity_id(
            STATUS_SENSOR_KEYS, domain="sensor"
        )
        self._vehicle_connected_entity_id = self._resolve_entity_id(
            VEHICLE_CONNECTED_BINARY_KEYS, domain="binary_sensor"
        )
        self._charging_active_entity_id = self._resolve_entity_id(
            CHARGING_BINARY_KEYS, domain="binary_sensor"
        )

        _LOGGER.info(
            "ModbusManagerCharger ready device=%s name=%s limit=%s max=%s "
            "status=%s vehicle=%s charging=%s",
            device_entry.id,
            device_entry.name_by_user or device_entry.name,
            self._current_limit_entity_id,
            self._max_current_entity_id,
            self._status_entity_id,
            self._vehicle_connected_entity_id,
            self._charging_active_entity_id,
        )

    @staticmethod
    def is_charger_device(device: DeviceEntry) -> bool:
        """Check for modbus_manager devices (use supports_device for EV capability)."""
        return any(
            id_domain == CHARGER_DOMAIN_MODBUS_MANAGER
            for id_domain, _ in device.identifiers
        )

    @staticmethod
    def supports_device(hass: HomeAssistant, device: DeviceEntry) -> bool:
        """Check if the device exposes a writable current-limit number entity."""
        if not ModbusManagerCharger.is_charger_device(device):
            return False
        registry = er.async_get(hass)
        entries = registry.entities.get_entries_for_device_id(
            device.id, include_disabled_entities=True
        )
        return (
            ModbusManagerCharger._find_entity_id_in_entries(
                entries, CURRENT_LIMIT_KEYS, domain="number"
            )
            is not None
        )

    @staticmethod
    def _find_entity_id_in_entries(
        entries: list, key_suffixes: tuple[str, ...], domain: str | None = None
    ) -> str | None:
        """Return entity_id for the longest matching unique_id suffix on this device."""
        for key in sorted(key_suffixes, key=len, reverse=True):
            suffix = f"_{key}".lower()
            matches = [
                entry
                for entry in entries
                if (domain is None or entry.domain == domain)
                and (entry.unique_id or "").lower().endswith(suffix)
            ]
            if len(matches) == 1:
                return matches[0].entity_id
            if len(matches) > 1:
                # Prefer matches that are not also a longer known key suffix.
                exact = [
                    entry
                    for entry in matches
                    if not any(
                        (entry.unique_id or "").lower().endswith(f"_{longer}")
                        for longer in key_suffixes
                        if len(longer) > len(key)
                    )
                ]
                chosen = exact[0] if exact else matches[0]
                _LOGGER.debug(
                    "Multiple entities for suffix '_%s'; using %s from %s",
                    key,
                    chosen.entity_id,
                    [m.entity_id for m in matches],
                )
                return chosen.entity_id
        return None

    def _resolve_entity_id(
        self, key_suffixes: tuple[str, ...], domain: str | None = None
    ) -> str | None:
        return self._find_entity_id_in_entries(self.entities, key_suffixes, domain)

    def _read_state(self, entity_id: str | None) -> str | None:
        if entity_id is None:
            return None
        return self._get_entity_state(entity_id)

    def _get_limit_bounds(self) -> tuple[float, float]:
        """Read min/max from the HA number entity attributes when available."""
        attrs = self._get_entity_state_attrs(self._current_limit_entity_id) or {}
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
        min_value, max_value = self._get_limit_bounds()
        requested = float(min(limit.values())) if limit else min_value
        value = max(min_value, min(requested, max_value))

        _LOGGER.debug(
            "set_current_limit device=%s entity=%s value=%s (requested=%s)",
            self.device_entry.id,
            self._current_limit_entity_id,
            value,
            requested,
        )
        await self.hass.services.async_call(
            domain="number",
            service="set_value",
            service_data={
                "entity_id": self._current_limit_entity_id,
                "value": value,
            },
            blocking=True,
        )

    def get_current_limit(self) -> dict[Phase, int] | None:
        """Return the configured charge current limit."""
        state = self._read_state(self._current_limit_entity_id)
        if state is None:
            _LOGGER.warning(
                "Current limit unavailable device=%s entity=%s",
                self.device_entry.id,
                self._current_limit_entity_id,
            )
            return None
        return dict.fromkeys(Phase, int(float(state)))

    def get_max_current_limit(self) -> dict[Phase, int] | None:
        """Return hardware/configured maximum charge current when exposed."""
        state = self._read_state(self._max_current_entity_id)
        if state is not None:
            return dict.fromkeys(Phase, int(float(state)))
        _, max_value = self._get_limit_bounds()
        return dict.fromkeys(Phase, int(max_value))

    def has_synced_phase_limits(self) -> bool:
        """Single limit entity applies to all phases on supported templates."""
        return True

    def _binary_is_on(self, entity_id: str | None) -> bool | None:
        state = self._read_state(entity_id)
        if state is None:
            return None
        return str(state).lower() in ("on", "true", "1")

    def _status_text(self) -> str | None:
        state = self._read_state(self._status_entity_id)
        if state is None:
            return None
        return str(state).lower()

    def _status_in(self, states: frozenset[str]) -> bool:
        status = self._status_text()
        if status is None:
            return False
        return status in states

    def car_connected(self) -> bool:
        """Car plugged in and EVSE ready or active."""
        vehicle = self._binary_is_on(self._vehicle_connected_entity_id)
        if vehicle is True:
            _LOGGER.debug(
                "car_connected device=%s entity=%s state=on",
                self.device_entry.id,
                self._vehicle_connected_entity_id,
            )
            return True
        charging = self._binary_is_on(self._charging_active_entity_id)
        if charging is True:
            _LOGGER.debug(
                "car_connected device=%s entity=%s state=on",
                self.device_entry.id,
                self._charging_active_entity_id,
            )
            return True
        result = self._status_in(CONNECTED_STATES)
        _LOGGER.debug(
            "car_connected device=%s entity=%s status=%s result=%s",
            self.device_entry.id,
            self._status_entity_id,
            self._status_text(),
            result,
        )
        return result

    def can_charge(self) -> bool:
        """Car connected and EVSE ready or delivering."""
        charging = self._binary_is_on(self._charging_active_entity_id)
        if charging is True:
            _LOGGER.debug(
                "can_charge device=%s entity=%s state=on",
                self.device_entry.id,
                self._charging_active_entity_id,
            )
            return True
        vehicle = self._binary_is_on(self._vehicle_connected_entity_id)
        if vehicle is True:
            _LOGGER.debug(
                "can_charge device=%s entity=%s state=on",
                self.device_entry.id,
                self._vehicle_connected_entity_id,
            )
            return True
        result = self._status_in(CONNECTED_STATES)
        _LOGGER.debug(
            "can_charge device=%s entity=%s status=%s result=%s",
            self.device_entry.id,
            self._status_entity_id,
            self._status_text(),
            result,
        )
        return result

    def is_charging(self) -> bool:
        """EVSE is actively charging."""
        charging = self._binary_is_on(self._charging_active_entity_id)
        if charging is True:
            _LOGGER.debug(
                "is_charging device=%s entity=%s state=on",
                self.device_entry.id,
                self._charging_active_entity_id,
            )
            return True
        result = self._status_in(CHARGING_STATES)
        _LOGGER.debug(
            "is_charging device=%s entity=%s status=%s result=%s",
            self.device_entry.id,
            self._status_entity_id,
            self._status_text(),
            result,
        )
        return result

    async def async_unload(self) -> None:
        """Unload the charger."""
