"""Phase J.2: the exact HAOS test light, a template light helper on `input_boolean.licht`.

The HAOS acceptance of 1.7.0-rc.4 used no physical device. "Test Leuchte" is a template
light created as a UI helper (template config entry) whose state is
`{{ states('input_boolean.licht') }}` and whose actions switch that boolean helper. These
tests run that configuration with the native integrations only: `input_boolean` (storage
helper, as created in the UI), `template` (set up through its real config flow, and the
equivalent YAML for comparison), `light` and an Adaptive Areas GlobalEntry with
"Arbeitszimmer" (accent group and ALL on the lamp, global lux sensor 117/123 lx,
`dark_on_bright_off`, activation on occupancy) and the Meta Area "global".

No MockLight or PushLight stands in for the lamp. No Context is set or passed on by the
tests, except a user Context where a person's action is modelled (T11, T12).

Default start order: the `binary_sensor` component is set up before Adaptive Areas, as it
is on a real Home Assistant instance with other binary sensors. That order makes the
presence platform restore the Area states before the light groups write their first state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
import threading
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_CALL_SERVICE,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import Context, CoreState, Event, HomeAssistant, State, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.adaptive_areas import light as aa_light
from custom_components.adaptive_areas.area_config import validate_area_options
from custom_components.adaptive_areas.const import (
    CONF_ACCENT_LIGHTS,
    CONF_ACCENT_LIGHTS_ACTIVATION,
    CONF_ACCENT_LIGHTS_BRIGHTNESS,
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    DOMAIN,
    GLOBAL_ENTRY_UNIQUE_ID,
    LIGHT_GROUP_ACTIVATION_OCCUPIED,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.dashboard import (
    build_decision_trace,
    build_light_runtime_status,
)
from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
from custom_components.adaptive_areas.helpers.light_origin import request_for_context

LUX = "sensor.lux"
BOOL = "input_boolean.licht"
LAMP = "light.test_leuchte"
MOTION = "binary_sensor.motion_arbeitszimmer"
SLUG = "arbeitszimmer"
GROUP = f"light.adaptive_areas_light_groups_{SLUG}_accent_lights"
ALL = f"light.adaptive_areas_light_groups_{SLUG}_all_lights"
SWITCH = f"switch.adaptive_areas_light_groups_{SLUG}_light_control"
PRESENCE = f"binary_sensor.adaptive_areas_presence_tracking_{SLUG}_area_state"
META_ALL = "light.adaptive_areas_light_groups_global_all_lights"
# T14: a second Area with its own template light.
BOOL_2 = "input_boolean.licht_wohnzimmer"
LAMP_2 = "light.lampe_wohnzimmer"
MOTION_2 = "binary_sensor.motion_wohnzimmer"
GROUP_2 = "light.adaptive_areas_light_groups_wohnzimmer_accent_lights"
ALL_2 = "light.adaptive_areas_light_groups_wohnzimmer_all_lights"
SWITCH_2 = "switch.adaptive_areas_light_groups_wohnzimmer_light_control"

DARK = "98"  # below the turn-on limit 117 lx
BRIGHT = "130"  # above the turn-off limit 123 lx
BAND = "120"  # between the limits: no change

GROUPS = (GROUP, ALL, META_ALL)


def _template(name: str, boolean: str) -> dict[str, Any]:
    """Return the user's template light: state from the boolean, actions switch it."""
    return {
        "name": name,
        "state": f"{{{{ states('{boolean}') }}}}",
        "turn_on": [
            {"action": "input_boolean.turn_on", "target": {"entity_id": boolean}}
        ],
        "turn_off": [
            {"action": "input_boolean.turn_off", "target": {"entity_id": boolean}}
        ],
    }


async def _create_template_helper(hass: HomeAssistant, name: str, boolean: str) -> None:
    """Create the template light through the real template config flow (UI helper)."""
    result = await hass.config_entries.flow.async_init(
        "template", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "light"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _template(name, boolean)
    )
    assert result["type"] == "create_entry", result


def _area_config(motion: str, lamp: str) -> dict[str, Any]:
    config, errors = validate_area_options(
        {"type": "interior"},
        {
            "include_entities": [motion],
            "features": {
                "light": {"turn_on_below": 117.0, "turn_off_above": 123.0},
                "light_groups": {
                    CONF_ACCENT_LIGHTS: [lamp],
                    CONF_ACCENT_LIGHTS_ACTIVATION: LIGHT_GROUP_ACTIVATION_OCCUPIED,
                    CONF_ACCENT_LIGHTS_BRIGHTNESS: LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
                },
            },
        },
    )
    assert config is not None, errors
    return config


async def _setup(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    *,
    variant: str = "entry",
    motion: str = STATE_ON,
    lux: str = BRIGHT,
    restore: list[State] | None = None,
    preload_binary_sensor: bool = True,
    second_area: bool = False,
    switch: str = STATE_ON,
    floor: bool = False,
    before_start: Callable[[], Awaitable[None]] | None = None,
) -> MockConfigEntry:
    """Cold start: input_boolean helper, template light, Adaptive Areas GlobalEntry.

    `before_start` runs after the entry is set up and before Home Assistant has started
    (the native light groups are not available yet).
    """
    items = [{"id": "licht", "name": "Licht"}]
    if second_area:
        items.append({"id": "licht_wohnzimmer", "name": "Licht Wohnzimmer"})
    hass_storage["input_boolean"] = {
        "version": 1,
        "minor_version": 1,
        "key": "input_boolean",
        "data": {"items": items},
    }
    mock_restore_cache(hass, [State(SWITCH, switch), *(restore or [])])
    hass.set_state(CoreState.not_running)
    hass.states.async_set(LUX, lux, {"unit_of_measurement": "lx"})
    if preload_binary_sensor:
        assert await async_setup_component(hass, "binary_sensor", {})
    areas = ar.async_get(hass)
    floor_id = fr.async_get(hass).async_create("OG").floor_id if floor else None
    area = areas.async_create("Arbeitszimmer", floor_id=floor_id)
    assert await async_setup_component(hass, "input_boolean", {})
    if variant == "entry":
        await _create_template_helper(hass, "Test Leuchte", BOOL)
        if second_area:
            await _create_template_helper(hass, "Lampe Wohnzimmer", BOOL_2)
    else:
        lights = [_template("Test Leuchte", BOOL)]
        if second_area:
            lights.append(_template("Lampe Wohnzimmer", BOOL_2))
        assert await async_setup_component(
            hass, "template", {"template": [{"light": lights}]}
        )
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    if registry.async_get(LAMP) is not None:
        registry.async_update_entity(LAMP, area_id=area.id)
    hass.states.async_set(MOTION, motion, {"device_class": "motion"})
    area_options = {
        area.id: {**_area_config(MOTION, LAMP), "id": area.id, "name": "Arbeitszimmer"},
    }
    if second_area:
        area_2 = areas.async_create("Wohnzimmer")
        hass.states.async_set(MOTION_2, STATE_ON, {"device_class": "motion"})
        area_options[area_2.id] = {
            **_area_config(MOTION_2, LAMP_2),
            "id": area_2.id,
            "name": "Wohnzimmer",
        }
    meta, errors = validate_area_options(
        {"type": "meta"}, {"features": {"light_groups": {}}}
    )
    assert meta is not None, errors
    area_options["global"] = {**meta, "id": "global", "name": "Global", "type": "meta"}
    if floor_id is not None:
        area_options[floor_id] = {**meta, "id": floor_id, "name": "OG", "type": "meta"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        minor_version=AdaptiveConfigEntryVersion.MINOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX},
            CONF_AREAS: area_options,
        },
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    if before_start is not None:
        await before_start()
    await hass.async_start()
    await hass.async_block_till_done()
    if second_area:
        await hass.services.async_call(
            "switch", "turn_on", {ATTR_ENTITY_ID: SWITCH_2}, blocking=True
        )
        await hass.async_block_till_done()
    return entry


def _area(hass: HomeAssistant, slug: str = SLUG):
    return next(
        a for a in iter_runtime_areas(hass) if not a.is_meta() and a.slug == slug
    )


def _override(hass: HomeAssistant, entity_id: str = GROUP) -> bool:
    return hass.states.get(entity_id).attributes.get("manual_override") is True


def _no_override(hass: HomeAssistant, *entity_ids: str) -> None:
    for entity_id in entity_ids or GROUPS:
        assert _override(hass, entity_id) is False, entity_id


async def _lux(hass: HomeAssistant, value: str) -> None:
    hass.states.async_set(LUX, value, {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()


async def _advance(hass: HomeAssistant, freezer, minutes: float) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def _clear(hass: HomeAssistant, freezer) -> None:
    """Motion stops; the clear timeout (1 min) runs out and the Area becomes free."""
    hass.states.async_set(MOTION, STATE_OFF, {"device_class": "motion"})
    await hass.async_block_till_done()
    await _advance(hass, freezer, 2)
    assert not _area(hass).is_occupied()


class Calls:
    """Every light and input_boolean service call, with its Context as Home Assistant set it."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Start recording."""
        self.items: list[tuple[str, Any, Context]] = []
        hass.bus.async_listen(EVENT_CALL_SERVICE, self._listener)

    @callback
    def _listener(self, event: Event) -> None:
        if event.data.get("domain") in ("light", "input_boolean"):
            target = event.data.get("service_data", {}).get(ATTR_ENTITY_ID)
            if isinstance(target, list) and len(target) == 1:
                target = target[0]
            self.items.append(
                (
                    f"{event.data['domain']}.{event.data['service']}",
                    target,
                    event.context,
                )
            )

    def plain(self) -> list[tuple[str, Any]]:
        """Return service and target of every call."""
        return [(service, target) for service, target, _ in self.items]

    def booleans(self) -> list[str]:
        """Return the input_boolean services called."""
        return [service for service, _, _ in self.items if service.startswith("input_")]


def _chain(service: str) -> list[tuple[str, Any]]:
    """Return the native chain of one command: group, template light, boolean."""
    return [
        (f"light.{service}", GROUP),
        (f"light.{service}", LAMP),
        (f"input_boolean.{service}", BOOL),
    ]


def _override_starts(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        entry
        for entry in build_decision_trace(_area(hass))["entries"]
        if entry["decision"] == "manual_override_started"
    ]


# T01, T02, T03, T15: automatic ON and OFF on the native template chain ----------------


@pytest.mark.parametrize("variant", ["entry", "yaml"])
async def test_t01_t02_t03_automatic_on_off_on_through_the_template_chain(
    hass: HomeAssistant, hass_storage, variant: str
) -> None:
    """T01/T02/T03/T15: DARK -> BRIGHT -> DARK gives ON/OFF/ON without an override.

    The Context of each automatic command is the registered group Context and reaches the
    boolean, the template light and both groups unchanged (no parent, no user).
    """
    entry = await _setup(hass, hass_storage, variant=variant)
    try:
        calls = Calls(hass)
        contexts: dict[str, list[Context]] = {}

        @callback
        def _states(event: Event) -> None:
            if event.data["entity_id"] in (BOOL, LAMP, GROUP, ALL):
                contexts.setdefault(event.data["entity_id"], []).append(event.context)

        hass.bus.async_listen("state_changed", _states)
        assert _area(hass).is_occupied()
        await _lux(hass, DARK)
        assert hass.states.get(BOOL).state == STATE_ON
        assert hass.states.get(LAMP).state == STATE_ON
        assert hass.states.get(GROUP).state == STATE_ON
        await _lux(hass, BRIGHT)
        assert hass.states.get(BOOL).state == STATE_OFF
        assert hass.states.get(LAMP).state == STATE_OFF
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        assert calls.plain() == _chain("turn_on") + _chain("turn_off") + _chain(
            "turn_on"
        )
        own = [context for _, _, context in calls.items]
        for index in range(0, 9, 3):
            context = own[index]
            assert own[index : index + 3] == [context] * 3
            assert context.parent_id is None and context.user_id is None
            assert request_for_context(_area(hass), context.id) is not None
        for entity_id in (BOOL, LAMP, GROUP, ALL):
            # Every state change of the chain carries one of the three own Contexts.
            assert {c.id for c in contexts[entity_id]} <= {c.id for c in own}, entity_id
        _no_override(hass)
        assert _override_starts(hass) == []
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_t15_ui_helper_and_yaml_template_differ_only_in_the_registry(
    hass: HomeAssistant, hass_storage
) -> None:
    """T15: the UI helper has a registry entry (Area assignable); YAML without unique_id not.

    The YAML side is covered by the parametrized T01-T03 test: same calls, same Contexts.
    """
    entry = await _setup(hass, hass_storage, variant="entry")
    try:
        registry_entry = er.async_get(hass).async_get(LAMP)
        assert registry_entry is not None
        assert registry_entry.platform == "template"
        assert registry_entry.config_entry_id is not None
        assert registry_entry.area_id == _area(hass).id
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_t15_yaml_template_without_unique_id_is_still_controlled(
    hass: HomeAssistant, hass_storage
) -> None:
    """T15: without a registry entry the explicitly configured member is still controlled."""
    entry = await _setup(hass, hass_storage, variant="yaml")
    try:
        assert er.async_get(hass).async_get(LAMP) is None
        assert hass.states.get(GROUP).attributes["lights"] == [LAMP]
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        _no_override(hass)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# T04, T05: repeated changes, accent group and ALL together ----------------------------


async def test_t04_t05_repeated_brightness_changes_never_block(
    hass: HomeAssistant, hass_storage, freezer
) -> None:
    """T04/T05: five DARK/BRIGHT cycles with band values in between; extended presence.

    Accent group and ALL are both loaded; neither blocks the other.
    """
    entry = await _setup(hass, hass_storage)
    try:
        calls = Calls(hass)
        await _advance(hass, freezer, 6)  # extended_time (5 min) passes while occupied
        # Extended is evaluated on the next presence update (no timer of its own).
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion", "seq": 1})
        await hass.async_block_till_done()
        assert _area(hass).has_state("extended")
        for _cycle in range(5):
            await _lux(hass, DARK)
            assert hass.states.get(LAMP).state == STATE_ON
            await _lux(hass, BAND)
            assert hass.states.get(LAMP).state == STATE_ON
            await _lux(hass, BRIGHT)
            assert hass.states.get(LAMP).state == STATE_OFF
            await _lux(hass, BAND)
            assert hass.states.get(LAMP).state == STATE_OFF
        assert (
            calls.booleans() == ["input_boolean.turn_on", "input_boolean.turn_off"] * 5
        )
        # Only the accent group sends commands; ALL sends no OFF while occupied.
        assert {target for _, target in calls.plain() if target != LAMP} <= {
            GROUP,
            BOOL,
        }
        _no_override(hass)
        # Extended timeout (10 min) ends the occupancy; nothing is left running.
        hass.states.async_set(MOTION, STATE_OFF, {"device_class": "motion"})
        await hass.async_block_till_done()
        await _advance(hass, freezer, 11)
        assert not _area(hass).is_occupied()
        # The Meta Area was extended too and runs its own extended timeout.
        await _advance(hass, freezer, 11)
        assert not any(a.is_occupied() for a in iter_runtime_areas(hass))
        _no_override(hass)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# T06: CLEAR switches ALL off ---------------------------------------------------------


async def test_t06_clear_all_off_is_not_an_override(
    hass: HomeAssistant, hass_storage, freezer
) -> None:
    """T06: CLEAR sends exactly one ALL OFF; then a new occupancy switches on again."""
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        calls = Calls(hass)
        await _clear(hass, freezer)
        assert hass.states.get(BOOL).state == STATE_OFF
        assert calls.plain() == [
            ("light.turn_off", ALL),
            ("light.turn_off", LAMP),
            ("input_boolean.turn_off", BOOL),
        ]
        _no_override(hass)
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion"})
        await hass.async_block_till_done()
        assert hass.states.get(LAMP).state == STATE_ON
        _no_override(hass)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# T07, T08, T09, T10: reload, restart, restore -----------------------------------------


async def test_t07_reload_during_occupancy_creates_no_override(
    hass: HomeAssistant, hass_storage
) -> None:
    """T07: a reload while occupied and on sends nothing and sets no override."""
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        calls = Calls(hass)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert calls.booleans() == []
        assert hass.states.get(LAMP).state == STATE_ON
        _no_override(hass)
        await _lux(hass, BRIGHT)
        await _lux(hass, DARK)
        assert calls.booleans() == ["input_boolean.turn_off", "input_boolean.turn_on"]
        _no_override(hass)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("preload_binary_sensor", [True, False])
@pytest.mark.parametrize("variant", ["entry", "yaml"])
async def test_t08_t09_t10_restart_with_restored_helpers_is_not_an_override(
    hass: HomeAssistant, hass_storage, variant: str, preload_binary_sensor: bool
) -> None:
    """T08/T09/T10: full restart, boolean restored ON, template light and groups restored.

    The boolean restores `on`; the template light goes unknown -> on with a Context of its
    own start, not of a call. Neither start order of the platforms sets an override.
    """
    entry = await _setup(
        hass,
        hass_storage,
        variant=variant,
        lux=DARK,
        preload_binary_sensor=preload_binary_sensor,
        restore=[
            State(BOOL, STATE_ON),
            State(LAMP, STATE_ON),
            State(PRESENCE, STATE_ON, {"states": ["occupied", "extended", "dark"]}),
            State(GROUP, STATE_ON, {"manual_override": False, "controlling": True}),
            State(ALL, STATE_ON, {"manual_override": False, "controlling": True}),
        ],
    )
    try:
        assert hass.states.get(BOOL).state == STATE_ON
        assert hass.states.get(LAMP).state == STATE_ON
        _no_override(hass)
        calls = Calls(hass)
        await _lux(hass, BRIGHT)
        await _lux(hass, DARK)
        assert calls.booleans() == ["input_boolean.turn_off", "input_boolean.turn_on"]
        _no_override(hass)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# T11, T12: real manual and external changes keep the existing rules -------------------


async def test_t11_manual_operation_of_the_template_light_sets_the_override(
    hass: HomeAssistant, hass_storage
) -> None:
    """T11: a user switches the template light; the existing override rule applies."""
    entry = await _setup(hass, hass_storage)
    try:
        user = await hass.auth.async_create_user("phase-j2", group_ids=["system-admin"])
        await hass.services.async_call(
            "light",
            "turn_on",
            {ATTR_ENTITY_ID: LAMP},
            blocking=True,
            context=Context(user_id=user.id),
        )
        await hass.async_block_till_done()
        assert hass.states.get(BOOL).state == STATE_ON
        assert _override(hass, GROUP) and _override(hass, ALL)
        assert set(_override_starts(hass)[0]["reason_codes"]) == {
            "manual_on",
            "origin_user_account",
        }
        calls = Calls(hass)
        await _lux(hass, DARK)
        await _lux(hass, BRIGHT)
        assert calls.booleans() == []  # J18: no automatic OFF during the override
        assert hass.states.get(LAMP).state == STATE_ON
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("user", "origin"), [(True, "origin_user_account"), (False, "origin_unattributed")]
)
async def test_t12_external_change_of_the_boolean_sets_the_override(
    hass: HomeAssistant, hass_storage, user: bool, origin: str
) -> None:
    """T12: the boolean is switched directly; the template light follows; rule applies."""
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        context = None
        if user:
            account = await hass.auth.async_create_user(
                "phase-j2-b", group_ids=["system-admin"]
            )
            context = Context(user_id=account.id)
        await hass.services.async_call(
            "input_boolean",
            "turn_off",
            {ATTR_ENTITY_ID: BOOL},
            blocking=True,
            context=context,
        )
        await hass.async_block_till_done()
        assert hass.states.get(LAMP).state == STATE_OFF
        assert _override(hass, GROUP)
        assert set(_override_starts(hass)[0]["reason_codes"]) == {"manual_off", origin}
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# T16: brightness during a valid override -----------------------------------------------


async def test_t16_brightness_changes_keep_a_valid_override(
    hass: HomeAssistant, hass_storage
) -> None:
    """T16: after a user OFF while dark and occupied, DARK/BRIGHT changes send nothing."""
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        user = await hass.auth.async_create_user(
            "phase-j2-c", group_ids=["system-admin"]
        )
        await hass.services.async_call(
            "light",
            "turn_off",
            {ATTR_ENTITY_ID: LAMP},
            blocking=True,
            context=Context(user_id=user.id),
        )
        await hass.async_block_till_done()
        assert _override(hass, GROUP)
        calls = Calls(hass)
        for value in (BRIGHT, DARK, BRIGHT, DARK):
            await _lux(hass, value)
        assert calls.booleans() == []
        assert hass.states.get(LAMP).state == STATE_OFF
        assert _override(hass, GROUP)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# T14: several Areas and the Meta ALL group --------------------------------------------


async def test_t14_two_areas_and_meta_all_do_not_influence_each_other(
    hass: HomeAssistant, hass_storage
) -> None:
    """T14: commands of Arbeitszimmer never reach Wohnzimmer; no group gets an override."""
    entry = await _setup(hass, hass_storage, second_area=True)
    try:
        assert {LAMP, LAMP_2} <= set(
            hass.states.get(META_ALL).attributes["entity_id"]
        ) or {
            GROUP,
            GROUP_2,
        } <= set(
            hass.states.get(META_ALL).attributes["entity_id"]
        )
        calls = Calls(hass)
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        assert hass.states.get(LAMP_2).state == STATE_ON
        await _lux(hass, BRIGHT)
        assert hass.states.get(LAMP).state == STATE_OFF
        assert hass.states.get(LAMP_2).state == STATE_OFF
        for service, target, context in calls.items:
            if target in (BOOL, LAMP, GROUP):
                assert request_for_context(_area(hass), context.id) is not None
            if target in (BOOL_2, LAMP_2, GROUP_2):
                assert request_for_context(_area(hass, "wohnzimmer"), context.id)
                assert request_for_context(_area(hass), context.id) is None, service
        assert not [c for c in calls.plain() if c[1] == META_ALL]
        _no_override(hass, GROUP, ALL, GROUP_2, ALL_2, META_ALL)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# Thread race of Phase J: listeners run on the event loop ------------------------------


async def test_light_group_listeners_run_on_the_event_loop(
    hass: HomeAssistant, hass_storage, monkeypatch
) -> None:
    """Group state and Area state listeners run on the loop, never in an executor thread.

    Deterministic: on RC.4 both listeners ran in Home Assistant's executor (they were not
    callbacks) and read and wrote the group's override and decision state from there.
    """
    threads: dict[str, set[bool]] = {
        "group_state": set(),
        "area_state": set(),
        "registry_write": set(),
        "registry_read": set(),
    }
    own_context = aa_light.AreaLightGroup._is_own_context
    decide = aa_light.AreaLightGroup._apply_decision_event
    register, lookup = aa_light.new_light_group_context, aa_light.request_for_context

    def _register(*args, **kwargs):
        threads["registry_write"].add(threading.get_ident() == hass.loop_thread_id)
        return register(*args, **kwargs)

    def _lookup(*args, **kwargs):
        threads["registry_read"].add(threading.get_ident() == hass.loop_thread_id)
        return lookup(*args, **kwargs)

    def _own(self, context):
        threads["group_state"].add(threading.get_ident() == hass.loop_thread_id)
        return own_context(self, context)

    def _decide(self, trigger):
        threads["area_state"].add(threading.get_ident() == hass.loop_thread_id)
        return decide(self, trigger)

    monkeypatch.setattr(aa_light.AreaLightGroup, "_is_own_context", _own)
    monkeypatch.setattr(aa_light.AreaLightGroup, "_apply_decision_event", _decide)
    monkeypatch.setattr(aa_light, "new_light_group_context", _register)
    monkeypatch.setattr(aa_light, "request_for_context", _lookup)
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        await _lux(hass, BRIGHT)
        # Presence activity (same Area state, new report) runs the decision path too.
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion", "seq": 1})
        await hass.async_block_till_done()
        assert threads == {
            "group_state": {True},
            "area_state": {True},
            "registry_write": {True},
            "registry_read": {True},
        }
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# Group-specific diagnosis --------------------------------------------------------------


async def test_dashboard_shows_override_and_last_decision_per_group(
    hass: HomeAssistant, hass_storage
) -> None:
    """An ALL override is shown on ALL only; the accent group shows its own state."""
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        all_group = next(
            group
            for group in _area(hass).hass.data["light"].entities
            if group.entity_id == ALL
        )
        # The ALL group alone is overridden (as after a restore of only that group).
        all_group._set_manual_override(True)
        all_group.async_write_ha_state()
        status = build_light_runtime_status(hass, _area(hass))
        groups = {
            group["category"]: group
            for group in status["light"]["control_path"]["groups"]
        }
        accent, everything = groups["accent_lights"], groups["all_lights"]
        assert accent["entity_id"] == GROUP and accent["state"] == STATE_ON
        assert accent["manual_override"] is False and accent["controlling"] is True
        assert accent["last_decision"]["decision"] == "turn_on"
        assert accent["last_decision"]["outcome"] == "executed"
        assert everything["entity_id"] == ALL
        assert everything["manual_override"] is True
        assert everything["last_decision"]["reason_codes"] == ["automatic_on_disabled"]
        assert groups["overhead_lights"]["manual_override"] is None
        assert groups["overhead_lights"]["last_decision"] is None
        assert status["light"]["override"] == {"mode": "MANUAL", "groups": [ALL]}
        traced = build_decision_trace(_area(hass))["entries"]
        assert {
            entry["group"] for entry in traced if entry["feature"] == "light_groups"
        } <= {
            "accent_lights",
            "all_lights",
        }
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# HAOS deviation: the template helper is edited (its config entry reloads) while on ----


@pytest.mark.parametrize("lamp_on", [True, False])
async def test_template_helper_reload_while_occupied_is_not_an_override(
    hass: HomeAssistant, hass_storage, lamp_on: bool
) -> None:
    """Saving the template helper reloads its entry; the light restarts without a call."""
    entry = await _setup(hass, hass_storage)
    try:
        if lamp_on:
            await _lux(hass, DARK)
            assert hass.states.get(LAMP).state == STATE_ON
        (template_entry,) = hass.config_entries.async_entries("template")
        assert await hass.config_entries.async_reload(template_entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(LAMP).state == (STATE_ON if lamp_on else STATE_OFF)
        _no_override(hass)
        calls = Calls(hass)
        await _lux(hass, BRIGHT if lamp_on else DARK)
        await _lux(hass, DARK if lamp_on else BRIGHT)
        assert calls.booleans() == (
            ["input_boolean.turn_off", "input_boolean.turn_on"]
            if lamp_on
            else ["input_boolean.turn_on", "input_boolean.turn_off"]
        )
        _no_override(hass)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
