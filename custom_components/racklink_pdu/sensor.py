from homeassistant.components.sensor import SensorEntity
from .helpers.socket_helper import get_status
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    sensors = [RackLinkPDUSensor(data, sensor_type) for sensor_type in ["status", "error"]]
    async_add_entities(sensors)

class RackLinkPDUSensor(SensorEntity):
    """Representation of a PDU sensor."""

    def __init__(self, data, sensor_type):
        self._data = data
        self._sensor_type = sensor_type
        self._state = None

    async def async_update(self):
        try:
            self._state = await get_status(self._data["ip"], self._sensor_type)
        except Exception:
            self._state = "unavailable"
