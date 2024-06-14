"""Constants for the Home Assistant Websocket client."""

from typing import Final

# Can be used to specify a catch all when registering state or event listeners.
MATCH_ALL: Final = "*"

# common hass events (for convenience reasons duplicated here)
EVENT_AREA_REGISTRY_UPDATED = "area_registry_updated"
EVENT_DEVICE_REGISTRY_UPDATED = "device_registry_updated"
EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"
EVENT_STATE_CHANGED = "state_changed"
