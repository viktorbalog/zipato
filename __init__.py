"""The Zipato MQTT integration."""
from homeassistant.helpers.typing import ConfigType, HomeAssistantType, ServiceDataType

from homeassistant.components.mqtt import (
    async_setup as mqtt_async_setup,
    async_setup_entry as mqtt_async_setup_entry,
)

DOMAIN = "zipato"
DATA_ZIPATO_CONFIG = "zipato_config"

CONF_TOPIC = "topic"

async def async_setup(hass: HomeAssistantType, config: ConfigType) -> bool:
    conf: ConfigType = config.get(DOMAIN)

    hass.data[DATA_ZIPATO_CONFIG] = dict({
        CONF_TOPIC: conf.get(CONF_TOPIC),
    })

    return await mqtt_async_setup(hass, config)

async def async_setup_entry(hass, entry):
    """Load a config entry."""
    return await mqtt_async_setup_entry(hass, entry)