"""Config flow for Otis AI Companion integration."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import selector
from homeassistant.components import conversation

from .const import (
    DOMAIN,
    CONF_CONVERSATION_AGENT,
    CONF_SPATIAL_MAP_PATH,
    CONF_THEME_NAME,
    DEFAULT_THEME_NAME,
    DEFAULT_SPATIAL_MAP_PATH,
)

_LOGGER = logging.getLogger(__name__)

def _get_agents(hass) -> list:
    """Get all available conversation agents, filtering out Otis AI itself."""
    from homeassistant.components.conversation import get_agent_manager
    agents = []
    try:
        manager = get_agent_manager(hass)
        agents = list(manager.async_get_agent_info())
    except Exception as err:
        _LOGGER.debug("Error getting agent manager: %s. Falling back to default agent.", err)
        default_agent = conversation.async_get_agent_info(hass)
        if default_agent:
            if isinstance(default_agent, list):
                agents = default_agent
            else:
                agents = [default_agent]

    filtered = []
    seen_ids = set()
    for a in agents:
        aid = getattr(a, "id", str(a))
        name = getattr(a, "name", "")
        if DOMAIN in str(aid).lower() or "otis" in str(name).lower():
            continue
        filtered.append(a)
        seen_ids.add(str(aid))

    # Also discover all active conversation entities in Home Assistant (e.g., conversation.text_generation_assist)
    class EntityAgentInfo:
        def __init__(self, agent_id: str, agent_name: str) -> None:
            self.id = agent_id
            self.name = agent_name

        def __repr__(self) -> str:
            return f"<AgentInfo id={self.id} name={self.name}>"

    if hass and hasattr(hass, "states"):
        try:
            for s in hass.states.async_all("conversation"):
                eid = s.entity_id
                if eid in ("conversation.home_assistant",) or DOMAIN in eid.lower() or "otis" in eid.lower():
                    continue
                if eid not in seen_ids:
                    filtered.append(EntityAgentInfo(eid, s.attributes.get("friendly_name") or eid))
                    seen_ids.add(eid)
        except Exception:
            pass

    return filtered


async def async_get_system_ai_preferred_agent(hass, agents: list) -> str | None:
    """Inspect Settings > System > AI (.storage/ai_task) to auto-detect preferred primary AI agent."""
    try:
        from homeassistant.helpers.storage import Store
        from homeassistant.helpers import entity_registry as er

        store = Store(hass, 1, "ai_task")
        data = await store.async_load()
        if data and isinstance(data, dict):
            gen_entity_id = data.get("gen_data_entity_id") or data.get("gen_image_entity_id")
            if gen_entity_id:
                ent_reg = er.async_get(hass)
                entry = ent_reg.async_get(gen_entity_id)
                if entry:
                    target_config_entry_id = entry.config_entry_id
                    target_platform = entry.platform

                    for agent in agents:
                        aid = getattr(agent, "id", str(agent))
                        if aid == target_config_entry_id or getattr(agent, "config_entry_id", None) == target_config_entry_id:
                            return aid
                        if target_platform and target_platform != "conversation" and target_platform in str(aid).lower():
                            return aid
    except Exception as err:
        _LOGGER.debug("Could not inspect System AI preferences: %s", err)
    return None


class OtisAIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Otis AI Companion."""

    VERSION = 1

    async def async_step_import(self, import_data: dict[str, Any] | None = None) -> FlowResult:
        """Handle import from configuration.yaml."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        agents = _get_agents(self.hass)
        detected_primary = await async_get_system_ai_preferred_agent(self.hass, agents)
        default_agent = detected_primary if detected_primary else (agents[0].id if agents else None)
        import_data = import_data or {}
        return self.async_create_entry(
            title="Otis AI Companion",
            data={
                CONF_CONVERSATION_AGENT: import_data.get(CONF_CONVERSATION_AGENT, default_agent),
                CONF_SPATIAL_MAP_PATH: import_data.get(CONF_SPATIAL_MAP_PATH, DEFAULT_SPATIAL_MAP_PATH),
                CONF_THEME_NAME: import_data.get(CONF_THEME_NAME, DEFAULT_THEME_NAME),
            },
        )

    async def async_step_user(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        # Get list of available conversation agents
        agents = _get_agents(self.hass)
        
        if user_input is not None:
            agent_id = user_input.get(CONF_CONVERSATION_AGENT)
            return self.async_create_entry(
                title="Otis AI Companion",
                data={
                    CONF_CONVERSATION_AGENT: agent_id,
                    CONF_SPATIAL_MAP_PATH: user_input.get(CONF_SPATIAL_MAP_PATH, DEFAULT_SPATIAL_MAP_PATH),
                    CONF_THEME_NAME: user_input.get(CONF_THEME_NAME, DEFAULT_THEME_NAME),
                },
            )

        if not agents:
            return self.async_show_form(
                step_id="onboarding",
                data_schema=vol.Schema({
                    vol.Optional("acknowledge_no_agent", default=False): cv.boolean,
                }),
            )

        # Auto-detect primary agent:
        # 1. Check Settings > System > AI
        # 2. If single agent, use it
        # 3. Otherwise default to first
        detected_primary = await async_get_system_ai_preferred_agent(self.hass, agents)
        default_agent = detected_primary if detected_primary else agents[0].id

        agent_options = [{"value": agent.id, "label": agent.name} for agent in agents]
        schema = vol.Schema({
            vol.Required(CONF_CONVERSATION_AGENT, default=default_agent): selector({
                "select": {
                    "options": agent_options,
                    "mode": "dropdown",
                }
            }),
            vol.Optional(CONF_SPATIAL_MAP_PATH, default=DEFAULT_SPATIAL_MAP_PATH): cv.string,
            vol.Optional(CONF_THEME_NAME, default=DEFAULT_THEME_NAME): cv.string,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
        )

    async def async_step_onboarding(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Handle onboarding when no AI agent is present."""
        if user_input is not None:
            return self.async_create_entry(
                title="Otis AI Companion (Limited)",
                data={
                    CONF_CONVERSATION_AGENT: None,
                    CONF_SPATIAL_MAP_PATH: DEFAULT_SPATIAL_MAP_PATH,
                    CONF_THEME_NAME: DEFAULT_THEME_NAME,
                },
            )

        return self.async_show_form(
            step_id="onboarding",
            data_schema=vol.Schema({
                vol.Required("understand_limitations", default=True): cv.boolean,
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OtisAIOptionsFlowHandler:
        """Get the options flow for this handler."""
        return OtisAIOptionsFlowHandler(config_entry)


class OtisAIOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Otis AI Companion."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        data = self._config_entry.data

        # Get list of available conversation agents
        agents = _get_agents(self.hass)
        agent_options = [{"value": agent.id, "label": agent.name} for agent in agents]
        
        default_agent = options.get(CONF_CONVERSATION_AGENT) or data.get(CONF_CONVERSATION_AGENT)
        if not default_agent and agents:
            default_agent = agents[0].id

        schema_dict = {}
        if agents:
            schema_dict[vol.Optional(CONF_CONVERSATION_AGENT, default=default_agent)] = selector({
                "select": {
                    "options": agent_options,
                    "mode": "dropdown",
                }
            })
        else:
            schema_dict[vol.Optional(CONF_CONVERSATION_AGENT, default="")] = cv.string

        schema_dict.update({
            vol.Optional(
                CONF_SPATIAL_MAP_PATH,
                default=options.get(CONF_SPATIAL_MAP_PATH, data.get(CONF_SPATIAL_MAP_PATH, DEFAULT_SPATIAL_MAP_PATH))
            ): cv.string,
            vol.Optional(
                CONF_THEME_NAME,
                default=options.get(CONF_THEME_NAME, data.get(CONF_THEME_NAME, DEFAULT_THEME_NAME))
            ): cv.string,
        })

        schema = vol.Schema(schema_dict)

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
