import logging
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN, DEFAULT_POLL_INTERVAL
from .api import RackLinkAPI, RackLinkAPIError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    ip = entry.data["ip"]
    name = entry.data["name"]
    api = RackLinkAPI(ip)
    await api.connect_persistent()

    async def async_update_data():
        # Try a ping to ensure connection is alive
        try:
            await api.ping()
        except RackLinkAPIError:
            # Try reconnect
            await api.close()
            try:
                await api.connect_persistent()
            except RackLinkAPIError:
                return {"reachable": False, "outlets": {}, "count": 0, "name": name}

        # If reachable, get status
        try:
            count = await api.get_outlet_count()
            outlets = list(range(1, count+1))
            statuses = await api.get_outlets_status(outlets)
            return {"reachable": True, "outlets": statuses, "count": count, "name": name}
        except RackLinkAPIError:
            return {"reachable": False, "outlets": {}, "count": 0, "name": name}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="racklink_pdu",
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
    )

    coordinator.api = api
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.api.close()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
