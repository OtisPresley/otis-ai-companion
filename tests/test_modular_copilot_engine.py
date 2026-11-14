"""Tests for the modular & self-optimizing Assist Co-Pilot engine."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.otis_ai.copilot_engine import (
    COPILOT_CONFIG_STORAGE_KEY,
    COPILOT_MEMORY_STORAGE_KEY,
    CopilotEngine,
    classify_confirmation_intent,
    has_unhandled_conditions,
    validate_and_upgrade_assistant_response,
)


def _make_mock_hass(states_map: dict[str, str] | None = None):
    """Build a minimal mock HomeAssistant instance."""
    hass = MagicMock()
    states_map = states_map or {}

    def _get_state(entity_id: str):
        if entity_id in states_map:
            st = MagicMock()
            st.state = states_map[entity_id]
            return st
        return None

    hass.states.get.side_effect = _get_state
    hass.states.async_entity_ids.return_value = list(states_map.keys())
    return hass


def test_confirmation_gate_strict():
    """Questions and critiques must never be classified as confirmations."""
    assert classify_confirmation_intent("yes")["is_confirmation"] is True
    assert classify_confirmation_intent("deploy it")["is_confirmation"] is True
    assert classify_confirmation_intent("cancel")["is_rejection"] is True
    assert classify_confirmation_intent("cancel")["is_confirmation"] is False

    critique = classify_confirmation_intent("Why didn't you deploy the sun elevation condition?")
    assert critique["is_critique_or_question"] is True
    assert critique["is_confirmation"] is False

    critique2 = classify_confirmation_intent("You should use sun.sun instead of sensor.sun_solar_elevation")
    assert critique2["is_critique_or_question"] is True
    assert critique2["is_confirmation"] is False


def test_has_unhandled_conditions():
    """Detect conditions outside the deterministic occupancy fast-path."""
    assert has_unhandled_conditions("turn on light when lux is below 50") is True
    assert has_unhandled_conditions("turn on light when sun elevation is below 4") is False


def test_validator_reexported():
    """validate_and_upgrade_assistant_response remains importable from custom_components.otis_ai."""
    from custom_components.otis_ai import (
        validate_and_upgrade_assistant_response as reexported_validator,
    )

    assert reexported_validator is validate_and_upgrade_assistant_response


@pytest.mark.asyncio
async def test_copilot_engine_storage_and_self_optimization():
    """Verify runtime self-optimization tools persist to copilot_config and copilot_memory."""
    hass = _make_mock_hass({"sun.sun": "below_horizon"})
    fake_stores: dict[str, dict] = {}

    class FakeStore:
        def __init__(self, _hass, _ver, key):
            self.key = key

        async def async_load(self):
            return fake_stores.get(self.key)

        async def async_save(self, data):
            fake_stores[self.key] = data

    with patch("custom_components.otis_ai.copilot_engine.Store", FakeStore):
        engine = CopilotEngine(hass)
        await engine.async_load()

        rule_res = await engine.async_tune_prompt_rule(
            "concise_yaml",
            "Always output a single clean YAML block with mode: restart.",
            enabled=True,
        )
        assert rule_res["rule_key"] == "concise_yaml"

        alias_res = await engine.async_set_entity_alias("solar elevation", "sun.sun")
        assert alias_res == {"alias": "solar elevation", "entity_id": "sun.sun"}

        tpl_res = await engine.async_set_condition_template(
            "sun_elevation_below",
            {"condition": "numeric_state", "entity_id": "sun.sun", "attribute": "elevation", "below": 5},
        )
        assert tpl_res["template"]["below"] == 5

        assert COPILOT_CONFIG_STORAGE_KEY in fake_stores
        assert COPILOT_MEMORY_STORAGE_KEY in fake_stores

        # Reload into fresh engine instance from fake_stores
        engine2 = CopilotEngine(hass)
        await engine2.async_load()
        state = engine2.get_copilot_state()
        assert "concise_yaml" in state["config"]["prompt_rules"]
        assert state["config"]["entity_aliases"]["solar elevation"] == "sun.sun"
        assert state["config"]["condition_templates"]["sun_elevation_below"]["below"] == 5


@pytest.mark.asyncio
async def test_copilot_user_correction_capture_and_prompt_injection():
    """User corrections about disabled entities and YAML preferences are captured and injected into prompts."""
    hass = _make_mock_hass({"sun.sun": "above_horizon", "sensor.sun_solar_elevation": "12.5"})
    fake_stores: dict[str, dict] = {}

    class FakeStore:
        def __init__(self, _hass, _ver, key):
            self.key = key

        async def async_load(self):
            return fake_stores.get(self.key)

        async def async_save(self, data):
            fake_stores[self.key] = data

    with patch("custom_components.otis_ai.copilot_engine.Store", FakeStore):
        engine = CopilotEngine(hass)
        await engine.async_load()

        captured = await engine.async_capture_user_correction(
            "sensor.sun_solar_elevation is disabled, use sun.sun instead of sensor.sun_solar_elevation",
            hass=hass,
        )
        assert len(captured) >= 1

        # Condition parser must respect the learned disabled fact and fall back to sun.sun attribute
        cond = engine.parse_sun_elevation_condition("turn on porch light when sun elevation is below 4")
        assert cond == {
            "condition": "numeric_state",
            "entity_id": "sun.sun",
            "attribute": "elevation",
            "below": 4,
        }

        prompt, compact_prompt, applied_count = engine.build_prompts(
            ha_version="2026.11",
            user_text="Automate porch light",
            rules_snippet="",
            history_snippet="",
            matched_yaml_context="",
            compact_matched_yaml_context="",
            rag_context="",
            maturity_summary="Intermediate",
            notable_integrations=["sun"],
            spatial_summary="Porch",
            climate_summary="None",
            vision_presence_summary="None",
            media_summary="None",
            security_summary="None",
            energy_summary="None",
            area_breakdown_summary="Porch",
            entity_summary="light.porch",
            detailed_entities=[],
            existing_automations=[],
            existing_scripts=[],
            orphan_summary="0",
            suggestions_summary="None",
            backup_summary="",
        )
        assert applied_count >= 1
        assert "VERIFIED LEARNED FACTS & USER CORRECTIONS" in prompt
        assert "VERIFIED LEARNED FACTS & USER CORRECTIONS" in compact_prompt
        assert "sensor.sun_solar_elevation" in prompt

        # Removal works
        fact_id = captured[0]["id"]
        assert await engine.async_remove_learned_fact(fact_id) is True
        assert await engine.async_remove_learned_fact(fact_id) is False


def test_validator_upgrades_empty_condition_and_strips_manual_steps():
    """Validator upgrades condition: [] -> conditions: [] and strips manual UI step tutorials."""
    raw = (
        "Here is your automation:\n\n"
        "```yaml\n"
        "alias: Test TV\n"
        "trigger:\n"
        "  - platform: state\n"
        "    entity_id: binary_sensor.great_room_motion\n"
        "    to: 'on'\n"
        "condition: []\n"
        "action:\n"
        "  - service: media_player.turn_on\n"
        "    target:\n"
        "      entity_id: media_player.shield_android_tv\n"
        "mode: single\n"
        "```\n\n"
        "Steps to Create the Automation:\n"
        "1. Open Home Assistant Core:\n"
        "- Click Add Automation.\n"
    )
    upgraded, _notes, penalty = validate_and_upgrade_assistant_response(None, raw)
    assert "triggers:" in upgraded
    assert "conditions: []" in upgraded
    assert "actions:" in upgraded
    assert "- trigger: state" in upgraded
    assert "- action: media_player.turn_on" in upgraded
    assert "Steps to Create the Automation" not in upgraded
    assert penalty >= 2


def test_validator_upgrades_hallucinated_hold_action_to_delay():
    """Validator converts hallucinated 'action: hold' + 'hold_time: 5m' into valid HA '- delay:'."""
    raw = (
        "```yaml\n"
        "alias: Great Room TV\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: binary_sensor.kitchen_person_occupancy\n"
        "    to: 'on'\n"
        "actions:\n"
        "  - action: hold\n"
        "    target:\n"
        "      entity_id: media_player.bravia_4k_gb_atv3\n"
        "    hold_time: 5m\n"
        "  - action: media_player.turn_on\n"
        "    target:\n"
        "      entity_id: media_player.bravia_4k_gb_atv3\n"
        "mode: single\n"
        "```"
    )
    upgraded, notes, penalty = validate_and_upgrade_assistant_response(None, raw)
    assert "action: hold" not in upgraded
    assert "- delay:" in upgraded
    assert "minutes: 5" in upgraded
    assert penalty >= 1
    assert any("delay" in n.lower() for n in notes)


@pytest.mark.asyncio
async def test_pure_question_not_captured_and_learned_filter_works():
    """Pure follow-up questions are not captured, while explicit preferences filter/prioritize entities."""
    hass = _make_mock_hass({"media_player.bravia_4k_gb_atv3": "off"})
    fake_stores: dict[str, dict] = {}

    class FakeStore:
        def __init__(self, _hass, _ver, key):
            self.key = key

        async def async_load(self):
            return fake_stores.get(self.key)

        async def async_save(self, data):
            fake_stores[self.key] = data

    with patch("custom_components.otis_ai.copilot_engine.Store", FakeStore):
        engine = CopilotEngine(hass)
        await engine.async_load()
        assert await engine.async_capture_user_correction("Why didn't you include a delay?", hass=hass) == []

        captured = await engine.async_capture_user_correction(
            "Remember that I prefer media_player.bravia_4k_gb_atv3 for the Great Room TV, and never use binary_sensor.kitchen_dog_occupancy for room automations.",
            hass=hass,
        )
        assert len(captured) == 1
        assert engine.filter_entities_with_learned_facts(
            ["media_player.great_room_tv", "media_player.bravia_4k_gb_atv3"]
        )[0] == "media_player.bravia_4k_gb_atv3"
        assert "binary_sensor.kitchen_dog_occupancy" not in engine.filter_entities_with_learned_facts(
            ["binary_sensor.kitchen_dog_occupancy", "binary_sensor.kitchen_person_occupancy"]
        )


def test_validator_autocorrects_unambiguous_domain_mismatch():
    """Validator auto-corrects switch.study_fan_study_light -> light.study_fan_study_light and matching service call."""
    hass = _make_mock_hass({
        "binary_sensor.study_presence": "on",
        "light.study_fan_study_light": "off",
    })
    raw = (
        "```yaml\n"
        "alias: Study Light\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: binary_sensor.study_presence\n"
        "    to: 'on'\n"
        "actions:\n"
        "  - action: switch.turn_on\n"
        "    target:\n"
        "      entity_id: switch.study_fan_study_light\n"
        "mode: single\n"
        "```"
    )
    upgraded, _notes, penalty = validate_and_upgrade_assistant_response(hass, raw)
    assert "Removed draft YAML block" not in upgraded
    assert "light.study_fan_study_light" in upgraded
    assert "switch.study_fan_study_light" not in upgraded
    assert "action: light.turn_on" in upgraded
    assert penalty == 0


def test_validator_prefers_visible_over_hidden_and_notifies_when_no_alternative():
    """Validator replaces hidden entity when visible alternative exists, and notifies when disabled/hidden has none."""
    from types import SimpleNamespace

    hass = _make_mock_hass({
        "binary_sensor.study_presence": "on",
        "switch.study_fan_study_light": "off",
        "light.study_fan_study_light": "off",
        "light.study_hidden_only": "off",
    })
    fake_reg = SimpleNamespace(
        entities={
            "binary_sensor.study_presence": SimpleNamespace(hidden_by=None, disabled_by=None),
            "switch.study_fan_study_light": SimpleNamespace(hidden_by="integration", disabled_by=None),
            "light.study_fan_study_light": SimpleNamespace(hidden_by=None, disabled_by=None),
            "light.study_hidden_only": SimpleNamespace(hidden_by="user", disabled_by=None),
            "light.study_disabled_only": SimpleNamespace(hidden_by=None, disabled_by="user"),
        }
    )

    with patch("custom_components.otis_ai.copilot_engine.er.async_get", return_value=fake_reg):
        # 1. Hidden entity with visible alternative -> auto-replaced with visible entity
        raw_hidden_alt = (
            "```yaml\n"
            "alias: Study Light\n"
            "actions:\n"
            "  - action: switch.turn_on\n"
            "    target:\n"
            "      entity_id: switch.study_fan_study_light\n"
            "```"
        )
        upgraded1, _, _ = validate_and_upgrade_assistant_response(hass, raw_hidden_alt)
        assert "light.study_fan_study_light" in upgraded1
        assert "switch.study_fan_study_light" not in upgraded1
        assert "action: light.turn_on" in upgraded1

        # 2. Hidden entity with NO visible alternative -> kept with user notice
        raw_hidden_only = (
            "```yaml\n"
            "alias: Hidden Only\n"
            "actions:\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: light.study_hidden_only\n"
            "```"
        )
        upgraded2, _, _ = validate_and_upgrade_assistant_response(hass, raw_hidden_only)
        assert "light.study_hidden_only" in upgraded2
        assert "hidden" in upgraded2.lower()
        assert "no visible alternative" in upgraded2.lower()

        # 3. Disabled entity with NO enabled alternative -> stripped with disabled notice
        raw_disabled_only = (
            "```yaml\n"
            "alias: Disabled Only\n"
            "actions:\n"
            "  - action: light.turn_on\n"
            "    target:\n"
            "      entity_id: light.study_disabled_only\n"
            "```"
        )
        upgraded3, _, penalty3 = validate_and_upgrade_assistant_response(hass, raw_disabled_only)
        assert "disabled entity" in upgraded3.lower()
        assert "light.study_disabled_only" in upgraded3
        assert penalty3 >= 1


def test_validator_rejects_hallucinated_ha_yaml_syntax():
    """Validator rejects unsupported HA keys like when:, attribute_or_state:, between:, device_id:, domainless entity_id."""
    hass = _make_mock_hass({
        "sensor.study_temp_temperature": "71",
        "light.study_fan_study_light": "off",
    })
    raw = (
        "```yaml\n"
        "alias: Broken Study Fan\n"
        "conditions:\n"
        "  - condition: numeric_state\n"
        "    entity_id: sensor.study_temp_temperature\n"
        "    attribute_or_state: state\n"
        "    between: [70, 71]\n"
        "  - condition: binary_sensor\n"
        "    device_id: f48162ac5b61b99317a71bf038bbcf16\n"
        "    entity_id: study_alarm_controller\n"
        "actions:\n"
        "  - action: switch.turn_on\n"
        "    data:\n"
        "      entity_id: light.study_fan_study_light\n"
        "    when:\n"
        "      condition: numeric_state\n"
        "      entity_id: sensor.study_temp_temperature\n"
        "      above: 72\n"
        "```"
    )
    upgraded, notes, penalty = validate_and_upgrade_assistant_response(hass, raw)
    assert "```yaml" not in upgraded
    assert "invalid home assistant syntax" in upgraded.lower()
    assert penalty >= 6
    assert any("when:" in n for n in notes)
    assert any("attribute_or_state:" in n for n in notes)
    assert any("between:" in n for n in notes)
    assert any("study_alarm_controller" in n for n in notes)


def test_validator_allows_fan_set_percentage_and_action_services():
    """Validator does not mistake action: fan.set_percentage or other service calls for entity IDs."""
    hass = _make_mock_hass({
        "binary_sensor.study_temp_occupancy": "on",
        "sensor.study_temp_temperature": "71",
        "fan.study_fan": "off",
    })
    raw = (
        "```yaml\n"
        "alias: Study Fan Control\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: binary_sensor.study_temp_occupancy\n"
        "    to: 'on'\n"
        "actions:\n"
        "  - choose:\n"
        "      - conditions:\n"
        "          - condition: numeric_state\n"
        "            entity_id: sensor.study_temp_temperature\n"
        "            above: 70\n"
        "            below: 72\n"
        "        sequence:\n"
        "          - action: fan.set_percentage\n"
        "            target:\n"
        "              entity_id: fan.study_fan\n"
        "            data:\n"
        "              percentage: 33\n"
        "mode: single\n"
        "```"
    )
    upgraded, _notes, penalty = validate_and_upgrade_assistant_response(hass, raw)
    assert "Removed draft YAML block" not in upgraded
    assert "fan.set_percentage" in upgraded
    assert penalty == 0


@pytest.mark.asyncio
async def test_learned_facts_merge_and_expand_instead_of_duplicating():
    """Similar or same-entity learned rules expand/update existing entries instead of duplicating."""
    hass = _make_mock_hass({})
    fake_stores: dict[str, dict] = {}

    class FakeStore:
        def __init__(self, _hass, _ver, key):
            self.key = key

        async def async_load(self):
            return fake_stores.get(self.key)

        async def async_save(self, data):
            fake_stores[self.key] = data

    with patch("custom_components.otis_ai.copilot_engine.Store", FakeStore):
        engine = CopilotEngine(hass)
        await engine.async_load()

        await engine.async_record_learned_fact(
            "Always prefer fan.study_fan for Study fan automations.",
            category="entity_preference",
            entities=["fan.study_fan"],
        )
        # Very similar phrasing -> should update/expand, not duplicate
        await engine.async_record_learned_fact(
            "Always prefer fan.study_fan for Study fan automations and never use light.study_fan_study_light.",
            category="entity_preference",
            entities=["fan.study_fan", "light.study_fan_study_light"],
        )
        facts = engine.get_active_learned_facts()
        assert len(facts) == 1
        assert "light.study_fan_study_light" in facts[0]["fact"]
        assert set(facts[0]["entities"]) == {"fan.study_fan", "light.study_fan_study_light"}


@pytest.mark.asyncio
async def test_compact_prompt_uses_positive_choose_example_without_negative_keys():
    """compact_prompt should provide a positive choose:/fan.set_percentage example without priming invalid keys."""
    hass = _make_mock_hass({})
    engine = CopilotEngine(hass)
    _, compact_prompt, _ = engine.build_prompts(
        ha_version="2026.11.1",
        user_text="Create an automation for the Study fan.",
        rules_snippet="",
        history_snippet="",
        matched_yaml_context="",
        compact_matched_yaml_context="",
        rag_context="",
        maturity_summary="",
        notable_integrations=[],
        spatial_summary="",
        climate_summary="",
        vision_presence_summary="",
        media_summary="",
        security_summary="",
        energy_summary="",
        area_breakdown_summary="",
        entity_summary="",
        detailed_entities=[],
        existing_automations=[],
        existing_scripts=[],
        orphan_summary="",
        suggestions_summary="",
        backup_summary="",
    )
    assert "fan.set_percentage" in compact_prompt
    assert "- choose:" in compact_prompt
    assert "attribute_or_state:" not in compact_prompt
    assert "condition: binary_sensor" not in compact_prompt
    assert "between:" not in compact_prompt


def test_validator_rejects_malformed_yaml_and_fan_targeting_light():
    """Validator catches yaml.YAMLError, between_range:, not_equal_to:, and fan.* targeting light.*."""
    hass = _make_mock_hass({
        "sensor.study_temp_temperature": "71",
        "light.study_fan_study_light": "off",
        "fan.study_fan_study_fan": "off",
        "binary_sensor.study_temp_occupancy": "on",
    })
    malformed = (
        "```yaml\n"
        "alias: Broken\n"
        "actions:\n"
        "  - condition: numeric_state\n"
        "    between_range: '70', '71.99'\n"
        "```"
    )
    upgraded_m, notes_m, penalty_m = validate_and_upgrade_assistant_response(hass, malformed)
    assert "```yaml" not in upgraded_m
    assert penalty_m >= 2
    assert any("invalid yaml syntax" in n.lower() for n in notes_m)

    bad_fan = (
        "```yaml\n"
        "alias: Bad Fan Target\n"
        "actions:\n"
        "  - choose:\n"
        "      - conditions:\n"
        "          - condition: state\n"
        "            entity_id: binary_sensor.study_temp_occupancy\n"
        "            not_equal_to: 'on'\n"
        "        sequence:\n"
        "          - action: fan.set_percentage\n"
        "            target:\n"
        "              entity_id: light.study_fan_study_light\n"
        "            data:\n"
        "              percentage: 33\n"
        "```"
    )
    upgraded_f, notes_f, penalty_f = validate_and_upgrade_assistant_response(hass, bad_fan)
    assert "```yaml" not in upgraded_f
    assert penalty_f >= 4
    assert any("not_equal_to:" in n for n in notes_f)
    assert any("light.study_fan_study_light" in n for n in notes_f)

    bad_choose = (
        "```yaml\n"
        "alias: Study Fan Automation\n"
        "triggers:\n"
        "  - trigger: event\n"
        "    event_type: binary_sensor.study_temp_occupancy.state_changed\n"
        "conditions:\n"
        "  - condition: state\n"
        "    entity_id: binary_sensor.study_temp_occupancy\n"
        "actions:\n"
        "  - choose:\n"
        "      when:\n"
        "        - condition: state\n"
        "          entity_id: sensor.study_temp_temperature\n"
        "          above: 72\n"
        "      then:\n"
        "        - action: fan.set_percentage\n"
        "          data:\n"
        "            percentage: 33\n"
        "          target_entity_id: fan.study_fan_study_fan\n"
        "      else:\n"
        "        - action: fan.turn_off\n"
        "          target_entity_id: fan.study_fan_study_fan\n"
        "```"
    )
    upgraded_c, notes_c, penalty_c = validate_and_upgrade_assistant_response(hass, bad_choose)
    assert "```yaml" not in upgraded_c
    assert penalty_c >= 8
    assert any("when:" in n for n in notes_c)
    assert any("else:" in n for n in notes_c)
    assert any("target_entity_id:" in n for n in notes_c)
    assert any("condition: numeric_state" in n for n in notes_c)
    assert any("trigger: state" in n for n in notes_c)


def test_requires_deep_reasoning_complexity_routing():
    """Complex YAML/debugging prompts require deep reasoning; simple queries stay fast/local."""
    from custom_components.otis_ai import _requires_deep_reasoning

    assert _requires_deep_reasoning(
        "Create an automation for the Study that when occupied turns the fan on low when the temperature is above 70 degrees."
    ) is True
    assert _requires_deep_reasoning("Debug why my theater automation failed") is True
    assert _requires_deep_reasoning("What is the temperature in the Study?") is False
    assert _requires_deep_reasoning("Turn on the Study fan") is False


def test_validator_rejects_duplicate_top_level_yaml_keys():
    """Validator catches duplicate top-level YAML keys (e.g. two actions: blocks) before safe_load overwrites them."""
    hass = _make_mock_hass({"fan.study_fan_study_fan": "off", "binary_sensor.study_temp_occupancy": "on"})
    dup_yaml = (
        "```yaml\n"
        "alias: Study Fan Control\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: binary_sensor.study_temp_occupancy\n"
        "actions:\n"
        "  - action: fan.turn_on\n"
        "    target:\n"
        "      entity_id: fan.study_fan_study_fan\n"
        "actions:\n"
        "  - action: fan.turn_off\n"
        "    target:\n"
        "      entity_id: fan.study_fan_study_fan\n"
        "```"
    )
    upgraded, notes, penalty = validate_and_upgrade_assistant_response(hass, dup_yaml)
    assert "```yaml" not in upgraded
    assert penalty >= 2
    assert any("duplicate top-level key" in n.lower() for n in notes)


def test_compile_json_automation_spec_to_valid_ha_yaml():
    """Structured JSON automation specs compile deterministically into valid HA 2026.11 YAML."""
    hass = _make_mock_hass({
        "binary_sensor.study_temp_occupancy": "on",
        "sensor.study_temp_temperature": "71",
        "fan.study_fan_study_fan": "off",
    })
    raw = (
        "```json\n"
        "{\n"
        '  "alias": "Study Fan Control",\n'
        '  "description": "Controls Study fan by occupancy and temperature",\n'
        '  "mode": "restart",\n'
        '  "triggers": [\n'
        '    {"type": "state", "entity_id": "binary_sensor.study_temp_occupancy"},\n'
        '    {"type": "numeric_state", "entity_id": "sensor.study_temp_temperature", "above": 70},\n'
        '    {"type": "numeric_state", "entity_id": "sensor.study_temp_temperature", "above": 72},\n'
        '    {"type": "numeric_state", "entity_id": "sensor.study_temp_temperature", "below": 70}\n'
        "  ],\n"
        '  "conditions": [],\n'
        '  "branches": [\n'
        "    {\n"
        '      "conditions": [\n'
        '        {"type": "state", "entity_id": "binary_sensor.study_temp_occupancy", "state": "on"},\n'
        '        {"type": "numeric_state", "entity_id": "sensor.study_temp_temperature", "above": 72}\n'
        "      ],\n"
        '      "actions": [\n'
        '        {"action": "fan.set_percentage", "entity_id": "fan.study_fan_study_fan", "data": {"percentage": 66}}\n'
        "      ]\n"
        "    },\n"
        "    {\n"
        '      "conditions": [\n'
        '        {"type": "state", "entity_id": "binary_sensor.study_temp_occupancy", "state": "on"},\n'
        '        {"type": "numeric_state", "entity_id": "sensor.study_temp_temperature", "above": 70}\n'
        "      ],\n"
        '      "actions": [\n'
        '        {"action": "fan.set_percentage", "entity_id": "fan.study_fan_study_fan", "data": {"percentage": 33}}\n'
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "default": [\n'
        '    {"action": "fan.turn_off", "entity_id": "fan.study_fan_study_fan"}\n'
        "  ]\n"
        "}\n"
        "```"
    )
    upgraded, notes, penalty = validate_and_upgrade_assistant_response(hass, raw)
    assert penalty == 0
    assert notes == []
    assert "```yaml" in upgraded
    assert "choose:" in upgraded
    assert "sequence:" in upgraded
    assert "default:" in upgraded
    assert "fan.set_percentage" in upgraded
    assert "fan.turn_off" in upgraded
    assert "fan.study_fan_study_fan" in upgraded
    assert "Removed draft YAML block" not in upgraded


@pytest.mark.asyncio
async def test_build_prompts_uses_lean_room_scoped_prompt_for_automation():
    """Room-specific automation requests produce a lean focused prompt for both cloud and local agents."""
    hass = _make_mock_hass({})
    engine = CopilotEngine(hass)
    prompt, compact_prompt, _ = engine.build_prompts(
        ha_version="2026.11.1",
        user_text="Create an automation for the Study fan.",
        rules_snippet="",
        history_snippet="",
        matched_yaml_context="UNRELATED_AUTOMATION_DUMP",
        compact_matched_yaml_context="UNRELATED_COMPACT_DUMP",
        rag_context="UNRELATED_RAG_DUMP",
        maturity_summary="",
        notable_integrations=[],
        spatial_summary="",
        climate_summary="",
        vision_presence_summary="",
        media_summary="",
        security_summary="",
        energy_summary="",
        area_breakdown_summary="UNRELATED_AREA_DUMP",
        entity_summary="",
        detailed_entities=[],
        existing_automations=[],
        existing_scripts=[],
        orphan_summary="",
        suggestions_summary="",
        backup_summary="",
        target_room_context="\nVERIFIED ENTITIES IN TARGET ROOM (Study):\n  - Fans: fan.study_fan_study_fan\n",
    )
    assert prompt == compact_prompt
    assert "fan.study_fan_study_fan" in prompt
    assert "UNRELATED_AUTOMATION_DUMP" not in prompt
    assert "UNRELATED_AREA_DUMP" not in prompt


def test_try_synthesize_room_fan_automation_study_thresholds():
    """Deterministic room fan synthesizer produces exact descending threshold branches and off default."""
    from custom_components.otis_ai.copilot_engine import try_synthesize_room_fan_automation

    room_ctx = (
        "\nVERIFIED ENTITIES IN TARGET ROOM (Study — USE ONLY THESE, NEVER GUESS OR INVENT OTHERS):\n"
        "  - Occupancy/Motion Sensors: binary_sensor.study_temp_occupancy\n"
        "  - Temperature/Environment Sensors: sensor.study_temp_temperature\n"
        "  - Fans: fan.study_fan_study_fan\n"
        "  - Lights: light.study_fan_study_light\n"
    )
    prompt_text = (
        "Create an automation for the Study that when occupied turns the fan on low when the temperature is above 70 degrees, "
        "turns the fan on medium when the temperature is above 72 degrees, "
        "turns the fan off when the temperature falls below 70 degrees or the room becomes unoccupied."
    )
    res = try_synthesize_room_fan_automation(
        prompt_text,
        room_ctx,
        learned_facts=[{"fact": "Always use mode: restart for occupancy automations."}],
    )
    assert res is not None
    y = res["yaml_data"]
    assert y["mode"] == "restart"
    assert len(y["triggers"]) == 4
    choose_block = y["actions"][0]["choose"]
    assert len(choose_block) == 2
    # Branch 0: >72 -> medium (66%)
    assert choose_block[0]["conditions"][1]["above"] == 72
    assert choose_block[0]["sequence"][0]["data"]["percentage"] == 66
    # Branch 1: >70 -> low (33%)
    assert choose_block[1]["conditions"][1]["above"] == 70
    assert choose_block[1]["sequence"][0]["data"]["percentage"] == 33
    # Default: fan.turn_off
    assert y["actions"][0]["default"][0]["action"] == "fan.turn_off"
    assert y["actions"][0]["default"][0]["target"]["entity_id"] == "fan.study_fan_study_fan"


def test_try_synthesize_room_lighting_automation_mudroom():
    """Deterministic room lighting synthesizer produces clean modern 2026.11 occupancy lighting YAML."""
    from custom_components.otis_ai.copilot_engine import try_synthesize_room_lighting_automation

    room_ctx = (
        "\nVERIFIED ENTITIES IN TARGET ROOM (Mudroom — USE ONLY THESE, NEVER GUESS OR INVENT OTHERS):\n"
        "  - Occupancy/Motion Sensors: binary_sensor.mudroom_motion, binary_sensor.mudroom_person_occupancy\n"
        "  - Lights: light.mudroom, light.back_stairs\n"
    )
    prompt_text = (
        "Create an automation for the Mudroom that turns on the light when occupancy is detected "
        "and turns it off 5 minutes after the room becomes unoccupied."
    )
    res = try_synthesize_room_lighting_automation(prompt_text, room_ctx)
    assert res is not None
    y = res["yaml_data"]
    assert y["alias"] == "Mudroom: Motion & Occupancy Lighting"
    assert y["mode"] == "restart"
    assert y["triggers"][0]["id"] == "motion_detected"
    assert y["triggers"][0]["to"] == "on"
    assert y["triggers"][1]["id"] == "motion_cleared"
    assert y["triggers"][1]["for"] == {"minutes": 5}
    choose_block = y["actions"][0]["choose"]
    assert choose_block[0]["sequence"][0]["action"] == "light.turn_on"
    assert choose_block[0]["sequence"][0]["target"]["entity_id"] == ["light.mudroom", "light.back_stairs"]
    assert choose_block[1]["sequence"][0]["action"] == "light.turn_off"


def test_validate_and_upgrade_room_scoped_entity_resolution():
    """Minor hallucinated room entity IDs resolve to verified room entities instead of stripping YAML."""
    from unittest.mock import MagicMock
    from custom_components.otis_ai.copilot_engine import validate_and_upgrade_assistant_response

    hass = MagicMock()
    verified = {
        "binary_sensor.guest_room_occupancy",
        "light.lower_porch",
    }
    hass.states.async_entity_ids.return_value = list(verified)
    hass.states.entity_ids.return_value = list(verified)
    hass.states.get.side_effect = lambda eid: MagicMock() if eid in verified else None

    room_ctx = (
        "\nVERIFIED ENTITIES IN TARGET ROOM (Guest Room — USE ONLY THESE, NEVER GUESS OR INVENT OTHERS):\n"
        "  - Occupancy/Motion Sensors: binary_sensor.guest_room_occupancy\n"
        "  - Lights: light.lower_porch\n"
    )
    speech = (
        "```yaml\n"
        "alias: 'Guest Room Light'\n"
        "triggers:\n"
        "  - trigger: state\n"
        "    entity_id: binary_sensor.guest_room_person_occupancy\n"
        "    to: 'on'\n"
        "actions:\n"
        "  - action: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.lower_fan_lower_porch\n"
        "```\n"
    )
    upgraded, notes, penalty = validate_and_upgrade_assistant_response(
        hass, speech, target_room_context=room_ctx
    )
    assert "Removed draft YAML block" not in upgraded
    assert "binary_sensor.guest_room_occupancy" in upgraded
    assert "light.lower_porch" in upgraded


def test_explanatory_query_preserves_illustrative_yaml():
    """Explanatory syntax questions preserve illustrative YAML examples with placeholder entities."""
    from unittest.mock import MagicMock
    from custom_components.otis_ai.copilot_engine import (
        is_explanatory_query,
        validate_and_upgrade_assistant_response,
    )

    prompt = (
        "Using modern Home Assistant 2026.11 syntax, explain the difference between "
        "triggers/actions and legacy trigger/service format, and give a short example."
    )
    assert is_explanatory_query(prompt) is True
    assert is_explanatory_query("Create an automation to turn on the study light") is False

    hass = MagicMock()
    hass.states.async_entity_ids.return_value = ["light.kitchen"]
    speech = (
        "Here is an example:\n"
        "```yaml\n"
        "triggers:\n"
        "  - trigger: numeric_state\n"
        "    entity_id: sensor.hallway_temp\n"
        "    above: 75\n"
        "actions:\n"
        "  - action: fan.set_percentage\n"
        "    target:\n"
        "      entity_id: fan.upper_fan_upper_fan\n"
        "```\n"
    )
    upgraded, notes, penalty = validate_and_upgrade_assistant_response(
        hass, speech, user_text=prompt
    )
    assert "Removed draft YAML block" not in upgraded
    assert "fan.upper_fan_upper_fan" in upgraded
    assert penalty == 0


def test_cloud_agent_subentry_extraction_and_recommendations():
    """Cloud agent optimizer extracts MappingProxyType subentry models and gives concrete model/rotation recommendations."""
    from types import MappingProxyType
    from unittest.mock import MagicMock
    from custom_components.otis_ai import (
        _extract_cloud_agent_config,
        _recommend_cloud_agent_optimization,
    )

    google_ce = MagicMock()
    google_ce.domain = "google_generative_ai_conversation"
    google_ce.options = MappingProxyType({})
    google_ce.data = MappingProxyType({})
    sub_conv = MagicMock()
    sub_conv.subentry_type = "conversation"
    sub_conv.data = MappingProxyType({"chat_model": "models/gemini-3.8-flash"})
    google_ce.subentries = MappingProxyType({"sub1": sub_conv})

    dom, mod, pft = _extract_cloud_agent_config(google_ce)
    assert dom == "google_generative_ai_conversation"
    assert mod == "models/gemini-3.8-flash"
    assert pft is False

    rec_mod, rec_text = _recommend_cloud_agent_optimization(
        domain=dom,
        agent_name="Google Generative AI",
        current_model=mod,
        protect_free_tier=pft,
        last_error="Timeout after 60s",
        avg_latency=60.0,
    )
    assert rec_mod == "models/gemini-3.5-flash-lite"
    assert "models/gemini-3.5-flash-lite" in rec_text

    groq_ce = MagicMock()
    groq_ce.domain = "groq"
    groq_ce.options = {}
    groq_ce.data = {}
    sub_tg = MagicMock()
    sub_tg.subentry_type = "text_generation"
    sub_tg.data = {"model": "openai/gpt-oss-120b", "protect_free_tier": True}
    groq_ce.subentries = {"sub2": sub_tg}

    g_dom, g_mod, g_pft = _extract_cloud_agent_config(groq_ce)
    assert g_dom == "groq"
    assert g_mod == "openai/gpt-oss-120b"
    assert g_pft is True

    g_rec_mod, g_rec_text = _recommend_cloud_agent_optimization(
        domain=g_dom,
        agent_name="Groq",
        current_model=g_mod,
        protect_free_tier=g_pft,
        last_error="Groq API error (HTTP 413)",
        avg_latency=2.0,
    )
    assert g_rec_mod == ""
    assert "disable/remove it from the Assist rotation" in g_rec_text


def test_sync_cloud_agent_model_metrics_resets_on_model_change():
    """Switching a cloud agent to a new/recommended model clears stale failure metrics and cooldowns."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.otis_ai import _sync_cloud_agent_model_metrics
    from custom_components.otis_ai.rules_manager import BehavioralRulesManager

    rm = BehavioralRulesManager.__new__(BehavioralRulesManager)
    rm._loaded = True
    rm._store = MagicMock()
    rm._store.async_save = AsyncMock()
    rm._rules = {
        "agent_health_metrics": {
            "entry123": {
                "success_count": 0,
                "error_count": 14,
                "consecutive_failures": 14,
                "avg_latency_s": 2.0,
                "quality_penalties": 8,
                "last_error_ts": 1794598040.0,
                "last_error_reason": "503 overloaded",
                "last_success_ts": 0.0,
            }
        }
    }

    did_reset = asyncio.run(
        _sync_cloud_agent_model_metrics(rm, ["entry123"], "models/gemini-3.5-flash-lite")
    )
    assert did_reset is True
    m = rm.get_agent_health_metrics()["entry123"]
    assert m["error_count"] == 0
    assert m["consecutive_failures"] == 0
    assert m["configured_model"] == "models/gemini-3.5-flash-lite"

    # Subsequent check with the same model should NOT reset
    did_reset_again = asyncio.run(
        _sync_cloud_agent_model_metrics(rm, ["entry123"], "models/gemini-3.5-flash-lite")
    )
    assert did_reset_again is False


def test_deprecated_model_never_recommended_again():
    """Models that return 404/deprecated are recorded and excluded from future recommendations."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.otis_ai import _recommend_cloud_agent_optimization
    from custom_components.otis_ai.rules_manager import BehavioralRulesManager

    rm = BehavioralRulesManager.__new__(BehavioralRulesManager)
    rm._loaded = True
    rm._store = MagicMock()
    rm._store.async_save = AsyncMock()
    rm._rules = {"agent_health_metrics": {}, "deprecated_models": []}

    asyncio.run(
        rm.async_record_agent_metric(
            "entry123",
            success=False,
            error_reason="404 Not Found: This model models/gemini-2.5-flash-lite is no longer available",
            configured_model="models/gemini-2.5-flash-lite",
        )
    )
    dep = rm.get_deprecated_models()
    assert "models/gemini-2.5-flash-lite" in dep

    rec_mod, _ = _recommend_cloud_agent_optimization(
        domain="google_generative_ai_conversation",
        agent_name="Google Generative AI",
        current_model="models/gemini-3.8-flash",
        protect_free_tier=False,
        last_error="Timeout",
        avg_latency=30.0,
        deprecated_models=dep,
        peer_working_models=["models/gemini-2.5-flash-lite", "models/gemini-3.5-flash"],
    )
    assert rec_mod != "models/gemini-2.5-flash-lite"
    assert rec_mod == "models/gemini-3.5-flash"


def test_fan_synthesizer_skips_battery_and_humidity_sensors():
    """Room fan synthesizer selects genuine temperature sensors and skips _battery/humidity/lux sensors."""
    from custom_components.otis_ai.copilot_engine import (
        is_valid_env_sensor,
        try_synthesize_room_fan_automation,
    )

    assert is_valid_env_sensor("sensor.equipment_temperature_battery", metric="temperature") is False
    assert is_valid_env_sensor("sensor.equipment_temperature_humidity", metric="temperature") is False
    assert is_valid_env_sensor("sensor.theater_humidity", metric="temperature") is False
    assert is_valid_env_sensor("sensor.equipment_temperature_temperature", metric="temperature") is True
    assert is_valid_env_sensor("sensor.theater_temperature", metric="temperature") is True
    assert is_valid_env_sensor("sensor.theater_temp_voltage", metric="temperature", device_class="voltage") is False

    room_ctx = (
        "\nVERIFIED ENTITIES IN TARGET ROOM (Theater — USE ONLY THESE, NEVER GUESS OR INVENT OTHERS):\n"
        "  - Temperature/Environment Sensors: sensor.equipment_temperature_battery, sensor.equipment_temperature_humidity, sensor.equipment_temperature_temperature\n"
        "  - Fans: fan.theater_ceiling_fan_main_fan\n"
    )
    res = try_synthesize_room_fan_automation(
        "Write an automation to turn on the Theater fan to medium if the Theater temperature goes above 74 degrees",
        room_ctx,
    )
    assert res is not None
    assert "sensor.equipment_temperature_temperature" in res["yaml_str"]
    assert "sensor.equipment_temperature_battery" not in res["yaml_str"]
    assert "sensor.equipment_temperature_humidity" not in res["yaml_str"]







