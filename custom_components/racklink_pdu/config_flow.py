import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN
from .api import RackLinkAPI, RackLinkAPIError

DATA_SCHEMA = vol.Schema({
    vol.Required("ip"): str,
    vol.Required("name"): str
})

class RackLinkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            ip = user_input["ip"]
            name = user_input["name"]
            try:
                api = RackLinkAPI(ip)
                count = await self.hass.async_add_executor_job(api.get_outlet_count)
            except RackLinkAPIError:
                return self.async_show_form(
                    step_id="user", data_schema=DATA_SCHEMA, errors={"base": "cannot_connect"}
                )

            await self.async_set_unique_id(ip)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=name, data={"ip": ip, "name": name})

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)
