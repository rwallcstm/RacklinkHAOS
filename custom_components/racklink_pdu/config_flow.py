from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
import voluptuous as vol
from .const import DOMAIN
from .helpers.socket_helper import test_connection

class RackLinkPDUConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RackLink PDU."""

    async def async_step_user(self, user_input=None):
        """Handle the initial setup step."""
        errors = {}
        if user_input is not None:
            try:
                await test_connection(user_input["ip"])
                return self.async_create_entry(title=user_input["name"], data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"

        schema = vol.Schema({
            vol.Required("name"): cv.string,
            vol.Required("ip"): cv.string,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RackLinkPDUOptionsFlow(config_entry)

class RackLinkPDUOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for RackLink PDU."""

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema({})
        return self.async_show_form(step_id="init", data_schema=schema)
