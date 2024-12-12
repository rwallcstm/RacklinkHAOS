from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .api import RackLinkAPIError
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    name = coordinator.data["name"]
    count = coordinator.data.get("count", 0)
    ip = entry.data["ip"]

    entities = []
    for i in range(1, count+1):
        entities.append(RackLinkOutletSwitch(coordinator, ip, i, name))
    async_add_entities(entities, True)

class RackLinkOutletSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, ip, outlet_number, device_name):
        super().__init__(coordinator)
        self._ip = ip
        self._outlet_number = outlet_number
        self._attr_name = f"{device_name} Outlet {outlet_number}"
        self._attr_unique_id = f"{self._ip}_outlet_{self._outlet_number}"
        self._device_name = device_name

    @property
    def is_on(self):
        data = self.coordinator.data
        if not data["reachable"]:
            return False
        return data["outlets"].get(self._outlet_number, False)

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._ip)},
            name=self._device_name,
            manufacturer="RackLink",
            model="Select Series PDU",
        )

    async def async_turn_on(self):
        await self._set_outlet_state(True)

    async def async_turn_off(self):
        await self._set_outlet_state(False)

    async def _set_outlet_state(self, on):
        api = self.coordinator.api
        try:
            await api.set_outlet_state(self._outlet_number, on)
        except RackLinkAPIError as e:
            _LOGGER.debug("Failed to set outlet state: %s", e)
        await self.coordinator.async_request_refresh()
