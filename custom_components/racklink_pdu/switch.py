from homeassistant.components.switch import SwitchEntity
from .helpers.socket_helper import send_command
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up switches dynamically."""
    data = hass.data[DOMAIN][entry.entry_id]
    outlets = await query_outlets(data["ip"])  # Query PDU outlets
    switches = [RackLinkOutletSwitch(data, outlet) for outlet in outlets]
    async_add_entities(switches)

async def query_outlets(ip):
    """Query the PDU for its outlets."""
    # Placeholder logic; replace with actual command
    return ["Outlet 1", "Outlet 2", "Outlet 3"]

class RackLinkOutletSwitch(SwitchEntity):
    """Representation of a PDU outlet."""

    def __init__(self, data, outlet):
        self._data = data
        self._outlet = outlet

    async def async_turn_on(self):
        await send_command(self._data["ip"], f"turn_on:{self._outlet}")

    async def async_turn_off(self):
        await send_command(self._data["ip"], f"turn_off:{self._outlet}")
