import logging
import voluptuous as vol

from homeassistant.helpers import (
    template as template_helper,
    config_validation as cv
)

from homeassistant.const import (
    CONF_VALUE_TEMPLATE,
    ATTR_TEMPERATURE,
)

from homeassistant.components import climate, mqtt
from homeassistant.components.climate import (
    PLATFORM_SCHEMA as CLIMATE_PLATFORM_SCHEMA,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_PRESET_MODE,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
)

from homeassistant.components.climate.const import (
    FAN_LOW,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    ATTR_HVAC_MODE,
)

from homeassistant.components.mqtt.climate import (
    MqttClimate,
    async_setup_entry as mqtt_async_setup_entry,
    TOPIC_KEYS,
    TEMPLATE_KEYS,
    CONF_MODE_LIST,
    CONF_HOLD_LIST,
    CONF_PAYLOAD_ON,
    CONF_PAYLOAD_OFF,
    CONF_SEND_IF_OFF,
    CONF_TEMP_INITIAL,
    CONF_TEMP_MIN,
    CONF_TEMP_MAX,
    CONF_TEMP_STEP,
    CONF_HOLD_COMMAND_TOPIC,
    CONF_HOLD_STATE_TOPIC,
    CONF_MODE_COMMAND_TOPIC,
    CONF_MODE_STATE_TOPIC,
    CONF_MODE_STATE_TEMPLATE,
    CONF_TEMP_COMMAND_TOPIC,
    CONF_TEMP_STATE_TOPIC,
    PLATFORM_SCHEMA as MQTT_PLATFORM_SCHEMA,
)

from homeassistant.components.mqtt.discovery import MQTT_DISCOVERY_NEW, clear_discovery_hash

from homeassistant.components.mqtt import (
    ATTR_DISCOVERY_HASH,
    CONF_QOS,
    CONF_RETAIN,
    CONF_UNIQUE_ID,
    MQTT_BASE_PLATFORM_SCHEMA,
    MqttAttributes,
    MqttAvailability,
    MqttDiscoveryUpdate,
    MqttEntityDeviceInfo,
    subscription
)

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

from . import (
    DATA_ZIPATO_CONFIG,
    CONF_TOPIC
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Zipato Thermostat"

CONF_NAME = "name"

CONF_ATTR_HEATING_LEVEL_ACTUAL = "attribute_heating_level_actual"
CONF_ATTR_HEATING_LEVEL_DISABLED = "attribute_heating_level_disabled"
CONF_ATTR_HEATING_LEVEL_STATE = "attribute_heating_level_state"
CONF_ATTR_HEATING_LEVEL_TARGET = "attribute_heating_level_target"

CONF_ATTR_MASTER_CONTROL_MODE = "attribute_master_control_mode"
CONF_ATTR_MASTER_CONTROL_VALUE = "attribute_master_control_value"
CONF_ATTR_MASTER_CONTROL_PRESET = "attribute_master_control_preset"
CONF_ATTR_MASTER_CONTROL_HOLD_UNTIL = "attribute_master_control_hold_until"

SCHEMA_BASE = CLIMATE_PLATFORM_SCHEMA.extend(MQTT_BASE_PLATFORM_SCHEMA.schema)
PLATFORM_SCHEMA = (
    SCHEMA_BASE.extend({
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_RETAIN, default=mqtt.DEFAULT_RETAIN): cv.boolean,
        vol.Optional(CONF_TEMP_INITIAL, default=21): cv.positive_int,
        vol.Optional(CONF_TEMP_MIN, default=DEFAULT_MIN_TEMP): vol.Coerce(float),
        vol.Optional(CONF_TEMP_MAX, default=DEFAULT_MAX_TEMP): vol.Coerce(float),
        vol.Optional(CONF_TEMP_STEP, default=1.0): vol.Coerce(float),
        vol.Required(CONF_ATTR_HEATING_LEVEL_ACTUAL): cv.string,
        vol.Required(CONF_ATTR_HEATING_LEVEL_DISABLED): cv.string,
        vol.Optional(CONF_ATTR_HEATING_LEVEL_STATE): cv.string,
        vol.Optional(CONF_ATTR_HEATING_LEVEL_TARGET): cv.string,
        vol.Required(CONF_ATTR_MASTER_CONTROL_MODE): cv.string,
        vol.Required(CONF_ATTR_MASTER_CONTROL_VALUE): cv.string,
        vol.Optional(CONF_ATTR_MASTER_CONTROL_PRESET): cv.string,
        vol.Optional(CONF_ATTR_MASTER_CONTROL_HOLD_UNTIL): cv.string,
    })
    .extend(mqtt.MQTT_AVAILABILITY_SCHEMA.schema)
    .extend(mqtt.MQTT_JSON_ATTRS_SCHEMA.schema)
)

MODE_REQUEST_TOPIC = "mode_request_topic"
TEMP_REQUEST_TOPIC = "temp_request_topic"
HOLD_REQUEST_TOPIC = "hold_request_topic"

COMMAND_TEMPLATE = "command_template"
MODE_COMMAND_TEMPLATE = "mode_command_template"
TEMP_COMMAND_TEMPLATE = "temp_command_template"
HOLD_COMMAND_TEMPLATE = 'hold_command_template'

DEFAULT_CONFIG = {
    CONF_SEND_IF_OFF: True,
    CONF_MODE_LIST: [HVAC_MODE_OFF, HVAC_MODE_HEAT],
    CONF_HOLD_LIST: {
        "PROGRAM",
        "HOLD_UNTIL",
        "HOLD_PERIOD",
        "HOLD_PERMANENT",
    },
    CONF_PAYLOAD_ON: "ON",
    CONF_PAYLOAD_OFF: "OFF",
    CONF_VALUE_TEMPLATE: template_helper.Template('{{value_json.value}}'),
    CONF_MODE_STATE_TEMPLATE: template_helper.Template('{% if value_json.value %}off{% else %}heat{% endif %}'),
    COMMAND_TEMPLATE: template_helper.Template('{"value": "{{value}}" }'),
    TEMP_COMMAND_TEMPLATE: template_helper.Template('{"value": "{{value}}" }'),
    MODE_COMMAND_TEMPLATE: template_helper.Template('{% if value == "off" %}{"value": true}{% else %}{"value": false}{% endif %}'),
}

COMMAND_TEMPLATE_KEYS = (
    MODE_COMMAND_TEMPLATE,
    TEMP_COMMAND_TEMPLATE,
    HOLD_COMMAND_TEMPLATE
)

REQUEST_KEYS = {
    MODE_REQUEST_TOPIC,
    TEMP_REQUEST_TOPIC,
    HOLD_REQUEST_TOPIC
}

STATE_TOPIC_WIREFRAME = "%s/attributes/%s/#"
COMMAND_TOPIC_WIREFRAME = "%s/request/attributes/%s/value"
REQUEST_TOPIC_WIREFRAME = "%s/request/attributes/%s/getValue"

async def async_setup_platform(
    hass: HomeAssistantType, config: ConfigType, async_add_entities, discovery_info=None
):
    """Set up MQTT climate device through configuration.yaml."""
    await _async_setup_entity(hass, config, async_add_entities)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up MQTT climate device dynamically through MQTT discovery."""

    await mqtt_async_setup_entry(hass, config_entry, async_add_entities)


async def _async_setup_entity(
    hass, config, async_add_entities, config_entry=None, discovery_hash=None
):
    """Set up the MQTT climate devices."""
    async_add_entities([ZipatoClimate(hass, config, config_entry, discovery_hash)])

class ZipatoClimate(MqttClimate):
    """Representation of a Zipato climate device."""

    def __init__(self, hass, config, config_entry, discovery_hash):
        self._zipato_config = hass.data[DATA_ZIPATO_CONFIG]
        self._topic_prefix = self._zipato_config.get(CONF_TOPIC)

        config.update(DEFAULT_CONFIG)
        MqttClimate.__init__(self, hass, config, config_entry, discovery_hash)

    def _setup_from_config(self, config):
        """(Re)Setup the entity."""
        prefix = self._topic_prefix

        # set to None in non-optimistic mode
        self._target_temp = (
            self._current_fan_mode
        ) = self._current_operation = self._current_swing_mode = None
        self._target_temp_low = None
        self._target_temp_high = None

        self._topic = {}

        for key in TOPIC_KEYS:
            self._topic[key] = None

        self._topic.update({
            CONF_TEMP_STATE_TOPIC: STATE_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_MASTER_CONTROL_VALUE]),
            CONF_TEMP_COMMAND_TOPIC: COMMAND_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_MASTER_CONTROL_VALUE]),
            TEMP_REQUEST_TOPIC: REQUEST_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_MASTER_CONTROL_VALUE]),
            CONF_MODE_STATE_TOPIC: STATE_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_HEATING_LEVEL_DISABLED]),
            CONF_MODE_COMMAND_TOPIC: COMMAND_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_HEATING_LEVEL_DISABLED]),
            MODE_REQUEST_TOPIC: REQUEST_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_HEATING_LEVEL_DISABLED]),
            CONF_HOLD_STATE_TOPIC: STATE_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_MASTER_CONTROL_MODE]),
            CONF_HOLD_COMMAND_TOPIC: COMMAND_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_MASTER_CONTROL_MODE]),
            HOLD_REQUEST_TOPIC: REQUEST_TOPIC_WIREFRAME % (prefix, config[CONF_ATTR_MASTER_CONTROL_MODE]),
        })

        self._target_temp = config[CONF_TEMP_INITIAL]

        self._target_temp_low = config[CONF_TEMP_INITIAL]
        self._target_temp_high = config[CONF_TEMP_INITIAL]

        self._current_fan_mode = FAN_LOW
        self._current_swing_mode = HVAC_MODE_OFF
        self._current_operation = HVAC_MODE_OFF

        self._action = None
        self._away = False
        self._hold = None
        self._aux = False

        value_templates = {}
        for key in TEMPLATE_KEYS:
            value_templates[key] = lambda value: value
        if CONF_VALUE_TEMPLATE in config:
            value_template = config.get(CONF_VALUE_TEMPLATE)
            value_template.hass = self.hass
            value_templates = {
                key: value_template.async_render_with_possible_json_value
                for key in TEMPLATE_KEYS
            }
        for key in TEMPLATE_KEYS & config.keys():
            tpl = config[key]
            value_templates[key] = tpl.async_render_with_possible_json_value
            tpl.hass = self.hass

        self._value_templates = value_templates

        command_templates = {}
        for key in COMMAND_TEMPLATE_KEYS:
            command_templates[key] = lambda value: value
        if COMMAND_TEMPLATE in config:
            command_template = config.get(COMMAND_TEMPLATE)
            command_template.hass = self.hass
            command_templates = {
                key: command_template.async_render_with_possible_json_value
                for key in COMMAND_TEMPLATE_KEYS
            }
        for key in COMMAND_TEMPLATE_KEYS & config.keys():
            tpl = config[key]
            command_templates[key] = tpl.async_render_with_possible_json_value
            tpl.hass = self.hass

        self._command_templates = command_templates

    async def _subscribe_topics(self):
        """(Re)Subscribe to topics."""
        await super(ZipatoClimate, self)._subscribe_topics()

        for request in REQUEST_KEYS:
            self._publish(request, '')

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_TARGET_TEMPERATURE | SUPPORT_PRESET_MODE

    @property
    def preset_modes(self):
        """Return preset modes."""
        return self._config[CONF_HOLD_LIST]

    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        if kwargs.get(ATTR_HVAC_MODE) is not None:
            operation_mode = kwargs.get(ATTR_HVAC_MODE)
            await self.async_set_hvac_mode(operation_mode)

        temp_command = self._command_templates[TEMP_COMMAND_TEMPLATE]
        self._set_temperature(
            temp_command(kwargs.get(ATTR_TEMPERATURE)), CONF_TEMP_COMMAND_TOPIC,
            CONF_TEMP_STATE_TOPIC, '_target_temp')

        # Always optimistic?
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        """Set new operation mode."""
        mode_command = self._command_templates[MODE_COMMAND_TEMPLATE]
        self._publish(CONF_MODE_COMMAND_TOPIC,
            mode_command(hvac_mode))

        if self._topic[CONF_MODE_STATE_TOPIC] is None:
            self._current_operation = hvac_mode
            self.async_write_ha_state()

        self._publish(TEMP_REQUEST_TOPIC, '')
        self._publish(HOLD_REQUEST_TOPIC, '')

    def _set_hold_mode(self, hold_mode):
        """Set hold mode.

        Returns if we should optimistically write the state.
        """
        hold_command = self._command_templates[HOLD_COMMAND_TEMPLATE]
        self._publish(CONF_HOLD_COMMAND_TOPIC,
            hold_command(hold_mode or "off"))

        if self._topic[CONF_HOLD_STATE_TOPIC] is not None:
            return False

        self._hold = hold_mode
        return True