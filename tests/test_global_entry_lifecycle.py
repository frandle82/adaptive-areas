"""GlobalEntry lifecycle regressions found in the RC.3 field test (R01-R28).

Real Home Assistant, a real GlobalEntry with several logical Areas, the real entity,
device, area and floor registries, and the native light service calls. Nothing is
mocked except the physical test lights and motion sensors.

Defects these tests pin (each failed on unchanged 1.7.0-rc.3):

- Ownership by name parts: "bad" is part of "bad_og" and a floor "og" is part of
  both. A Meta Area's platform cleanup then removed the child's live entities, so
  every reload toggled them between present and absent (a device assignment, which
  reloads, made light control "work again").
- Configured light group members outside the Home Assistant Area created no groups.
- The light control switch was read through a composed entity ID.
- Deleting an Area left its entities and device in the registries.
- `reload_on_registry_change` of an Area was read from the GlobalEntry top level.
- One deleted Home Assistant Area stopped the whole GlobalEntry.
- A failed platform unload was reported as a successful unload.
- The GlobalEntry raised a false "missing area" Repair issue.
- Deleting the last Area of a migrated GlobalEntry failed its setup.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    EVENT_CALL_SERVICE,
    EVENT_HOMEASSISTANT_START,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
    STATE_ON,
)
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.adaptive_areas.area_config import (
    async_create_area,
    async_delete_area,
    validate_area_options,
)
from custom_components.adaptive_areas.const import (
    ADAPTIVE_DEVICE_ID_PREFIX,
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_MIGRATION,
    DOMAIN,
    GLOBAL_ENTRY_UNIQUE_ID,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.dashboard import build_light_runtime_status
from custom_components.adaptive_areas.helpers.area import (
    generated_entities_for_area,
    get_runtime_areas_for_entry,
)
from custom_components.adaptive_areas.migration import (
    MigrationPhase,
    MigrationState,
    async_run_single_global_entry_migration,
    get_global_entries,
)
from tests.helpers import setup_test_component_platform
from tests.mocks import MockBinarySensor, MockLight

LUX = "sensor.global_lux"
DARK_LUX = "50"
BRIGHT_LUX = "150"


def area_device_identifier(area_id: str) -> tuple[str, str]:
    """Return the persisted identifier of an Area's Adaptive Areas device."""
    return (DOMAIN, f"{ADAPTIVE_DEVICE_ID_PREFIX}{area_id}")


def _group(slug: str, category: str = "overhead_lights") -> str:
    return f"light.adaptive_areas_light_groups_{slug}_{category}"


def _switch(slug: str) -> str:
    return f"switch.adaptive_areas_light_groups_{slug}_light_control"


def _area_config(area_id: str, name: str, light: str, motion: str, **extra) -> dict:
    """One regular Area with one overhead group in mode dark_on_bright_off."""
    config, errors = validate_area_options(
        {"type": "interior"},
        {
            "include_entities": [motion],
            "features": {
                "light": {"turn_on_below": 90.0, "turn_off_above": 110.0},
                "light_groups": {
                    "overhead_lights": [light],
                    "overhead_lights_act_on": ["occupancy_change"],
                    "overhead_lights_states": ["occupied"],
                    "overhead_lights_brightness": "dark_on_bright_off",
                },
            },
            **extra,
        },
    )
    assert config is not None, errors
    return {**config, "id": area_id, "name": name}


def _meta_config(meta_id: str, name: str) -> dict:
    config, errors = validate_area_options(
        {"type": "meta"}, {"features": {"light_groups": {}}}
    )
    assert config is not None, errors
    return {**config, "id": meta_id, "name": name, "type": "meta"}


def _global_entry(areas: dict, **options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        minor_version=AdaptiveConfigEntryVersion.MINOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX},
            CONF_AREAS: areas,
            **options,
        },
    )


async def _devices(
    hass: HomeAssistant, names: list[str], area_ids: dict[str, str | None] | None = None
) -> tuple[list[str], list[str]]:
    """Physical test lights and motion sensors, optionally in a Home Assistant Area."""
    lights = [
        MockLight(name=f"lamp_{name}", state="off", unique_id=f"lamp_{name}")
        for name in names
    ]
    motions = [
        MockBinarySensor(
            name=f"motion_{name}", unique_id=f"motion_{name}", device_class="motion"
        )
        for name in names
    ]
    setup_test_component_platform(hass, "light", lights)
    setup_test_component_platform(hass, "binary_sensor", motions)
    assert await async_setup_component(hass, "light", {"light": {"platform": "test"}})
    assert await async_setup_component(
        hass, "binary_sensor", {"binary_sensor": {"platform": "test"}}
    )
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for name, light, motion in zip(names, lights, motions, strict=True):
        area_id = (area_ids or {}).get(name)
        if area_id is not None:
            registry.async_update_entity(light.entity_id, area_id=area_id)
            registry.async_update_entity(motion.entity_id, area_id=area_id)
    return [light.entity_id for light in lights], [m.entity_id for m in motions]


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _record_calls(hass: HomeAssistant) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []

    def _record(event) -> None:
        if event.data.get("domain") != "light":
            return
        raw = event.data.get("service_data", {}).get("entity_id")
        targets = [raw] if isinstance(raw, str) else list(raw or [])
        calls.append((event.data["service"], targets))

    hass.bus.async_listen(EVENT_CALL_SERVICE, _record)
    return calls


async def _lux(hass: HomeAssistant, value: str) -> None:
    hass.states.async_set(LUX, value, {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()


async def _motion(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state, {"device_class": "motion"})
    await hass.async_block_till_done()


async def _enable(hass: HomeAssistant, switch_entity_id: str) -> None:
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch_entity_id}, blocking=True
    )
    await hass.async_block_till_done()


def _group_calls(calls, service: str, group: str) -> int:
    return sum(1 for svc, targets in calls if svc == service and targets == [group])


def _registered(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    return {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    }


def _live(hass: HomeAssistant, entity_id: str) -> bool:
    state = hass.states.get(entity_id)
    return state is not None and not state.attributes.get("restored")


async def _reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def _advance(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


# R01, R06, R07 ------------------------------------------------------------------


async def test_r01_cold_start_controls_lights_without_registry_change(hass) -> None:
    """Set up before Home Assistant runs: DARK switches on, BRIGHT switches off.

    Starting Home Assistant schedules no reload of the GlobalEntry: the Meta Areas
    share the entry with their children and need none.
    """
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry(
        {
            hall.id: _area_config(hall.id, "Hall", lamp, motion),
            "global": _meta_config("global", "Global"),
        }
    )
    mock_restore_cache(hass, [State(_switch("hall"), STATE_ON)])
    hass.set_state(CoreState.not_running)
    await _setup(hass, entry)
    with patch.object(
        hass.config_entries,
        "async_schedule_reload",
        wraps=hass.config_entries.async_schedule_reload,
    ) as reload:
        # Native start order: START (groups begin tracking), then running and STARTED.
        hass.bus.async_fire(EVENT_HOMEASSISTANT_START)
        await hass.async_block_till_done()
        hass.set_state(CoreState.running)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        await _advance(hass, 10)
        assert reload.call_count == 0

        calls = _record_calls(hass)
        await _motion(hass, motion, STATE_ON)
        await _lux(hass, DARK_LUX)
        assert _group_calls(calls, "turn_on", _group("hall")) == 1
        assert ("turn_on", [lamp]) in calls
        await _lux(hass, BRIGHT_LUX)
        assert _group_calls(calls, "turn_off", _group("hall")) == 1
        assert _group_calls(calls, "turn_on", _group("hall")) == 1
        assert reload.call_count == 0


# R02 ------------------------------------------------------------------------------


async def test_r02_configured_members_outside_the_ha_area_create_groups(hass) -> None:
    """A valid, explicitly configured lamp in no Home Assistant Area is controlled."""
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"])
    er.async_get(hass).async_update_entity(motion, area_id=hall.id)
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)

    assert _live(hass, _group("hall"))
    assert _live(hass, _group("hall", "all_lights"))
    await _enable(hass, _switch("hall"))
    calls = _record_calls(hass)
    await _motion(hass, motion, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("hall")) == 1
    assert ("turn_on", [lamp]) in calls


# R03, R04, R05 ---------------------------------------------------------------------


async def test_r03_renamed_control_switch_is_the_switch_that_counts(hass) -> None:
    """A renamed light control switch still enables and disables the automation."""
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    registry = er.async_get(hass)
    registry.async_update_entity(_switch("hall"), new_entity_id="switch.hall_auto")
    await hass.async_block_till_done()
    await _enable(hass, "switch.hall_auto")
    calls = _record_calls(hass)
    await _motion(hass, motion, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("hall")) == 1
    status = build_light_runtime_status(
        hass, get_runtime_areas_for_entry(hass, entry)[0]
    )
    assert status["light"]["control_path"]["control_switch"] == {
        "entity_id": "switch.hall_auto",
        "enabled": True,
    }

    # Disabling the renamed switch stops the automation.
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.hall_auto"}, blocking=True
    )
    await _lux(hass, BRIGHT_LUX)
    assert _group_calls(calls, "turn_off", _group("hall")) == 0

    # The rename survives a reload, and so does control.
    await _reload(hass, entry)
    assert registry.async_get("switch.hall_auto") is not None
    assert registry.async_get(_switch("hall")) is None
    await _enable(hass, "switch.hall_auto")
    calls.clear()
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("hall")) == 1


async def test_r04_suffixed_control_switch_never_reads_a_foreign_entity(hass) -> None:
    """The default switch ID is taken: the suffixed real switch counts, not the other."""
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    er.async_get(hass).async_get_or_create(
        "switch",
        "foreign",
        "occupies_the_default_id",
        suggested_object_id=_switch("hall")[7:],
    )
    hass.states.async_set(_switch("hall"), STATE_ON)
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    real = _switch("hall") + "_2"
    assert _live(hass, real)

    calls = _record_calls(hass)
    await _motion(hass, motion, STATE_ON)
    await _lux(hass, DARK_LUX)
    # The foreign entity is ON, the real switch is OFF: nothing is switched.
    assert _group_calls(calls, "turn_on", _group("hall")) == 0
    await _enable(hass, real)
    assert _group_calls(calls, "turn_on", _group("hall")) == 1


async def test_r05_switch_registered_after_the_groups_enables_control(hass) -> None:
    """The restored-ON switch arrives after the groups: one ON, no waiting or polling."""
    from custom_components.adaptive_areas import switch as switch_platform

    await _lux(hass, DARK_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    await _motion(hass, motion, STATE_ON)
    mock_restore_cache(hass, [State(_switch("hall"), STATE_ON)])
    group_added = asyncio.Event()

    def _watch(event) -> None:
        if event.data["entity_id"] == _group("hall"):
            group_added.set()

    hass.bus.async_listen(EVENT_STATE_CHANGED, _watch)
    original = switch_platform._async_setup_area

    async def _late(hass_, area, add_entities) -> None:
        await group_added.wait()
        await original(hass_, area, add_entities)

    calls = _record_calls(hass)
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    with patch.object(switch_platform, "_async_setup_area", _late):
        await _setup(hass, entry)
    assert _group_calls(calls, "turn_on", _group("hall")) == 1


# R08, R13, R14 ---------------------------------------------------------------------


async def test_r13_bad_bad_og_and_floor_og_keep_their_entities(hass) -> None:
    """Similar names and a floor named like an Area suffix never share ownership.

    On RC.3 every reload removed the live entities of "Bad OG" (owned by the floor
    "OG" and by "Bad" through name parts) and the next reload brought them back.
    """
    await _lux(hass, BRIGHT_LUX)
    og = fr.async_get(hass).async_create("OG")
    areas = ar.async_get(hass)
    bad = areas.async_create("Bad", floor_id=og.floor_id)
    bad_og = areas.async_create("Bad OG", floor_id=og.floor_id)
    (lamp_bad, lamp_og), (m_bad, m_og) = await _devices(
        hass, ["bad", "bad_og"], {"bad": bad.id, "bad_og": bad_og.id}
    )
    entry = _global_entry(
        {
            bad.id: _area_config(bad.id, "Bad", lamp_bad, m_bad),
            bad_og.id: _area_config(bad_og.id, "Bad OG", lamp_og, m_og),
            og.floor_id: _meta_config(og.floor_id, "OG"),
        }
    )
    await _setup(hass, entry)
    expected = {
        _group("bad"),
        _group("bad_og"),
        _switch("bad"),
        _switch("bad_og"),
        "binary_sensor.adaptive_areas_presence_tracking_bad_og_area_state",
    }
    for cycle in range(3):
        assert expected <= _registered(hass, entry), cycle
        assert all(_live(hass, entity_id) for entity_id in expected), cycle
        runtime = {area.id: area for area in get_runtime_areas_for_entry(hass, entry)}
        owned = {
            area_id: {e.entity_id for e in generated_entities_for_area(hass, area)}
            for area_id, area in runtime.items()
        }
        assert _group("bad_og") in owned[bad_og.id]
        assert _group("bad_og") not in owned[bad.id] | owned[og.floor_id]
        assert not owned[bad.id] & owned[bad_og.id]
        await _reload(hass, entry)

    # Generated entities get their own Home Assistant Area, never a similar one.
    registry = er.async_get(hass)
    assert registry.async_get(_switch("bad_og")).area_id == bad_og.id
    assert registry.async_get(_switch("bad")).area_id == bad.id

    # And control of "Bad OG" works after these reloads.
    await _enable(hass, _switch("bad_og"))
    calls = _record_calls(hass)
    await _motion(hass, m_og, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("bad_og")) == 1
    assert _group_calls(calls, "turn_on", _group("bad")) == 0


async def test_r08_device_assignment_after_setup_needs_no_initialisation(hass) -> None:
    """Assigning a device reloads once; control worked before and works after."""
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp, extra), (motion, _m2) = await _devices(
        hass, ["hall", "extra"], {"hall": hall.id}
    )
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    await _enable(hass, _switch("hall"))
    calls = _record_calls(hass)
    await _motion(hass, motion, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("hall")) == 1
    before = {
        e.entity_id: e.id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }

    er.async_get(hass).async_update_entity(extra, area_id=hall.id)
    await hass.async_block_till_done()
    await _advance(hass, 5)
    after = {
        e.entity_id: e.id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert after == before
    await _lux(hass, BRIGHT_LUX)
    assert _group_calls(calls, "turn_off", _group("hall")) == 1


async def test_r14_renaming_an_area_moves_nothing_to_another_area(hass) -> None:
    """A rename keeps every other Area untouched; the renamed Area keeps one set.

    The slug in the generated IDs follows the Home Assistant Area name (unchanged
    since 1.6.18). The old set is cleaned up as the Area's own, not as anyone else's.
    """
    await _lux(hass, BRIGHT_LUX)
    areas = ar.async_get(hass)
    bad = areas.async_create("Bad")
    bad_og = areas.async_create("Bad OG")
    (lamp_bad, lamp_og), (m_bad, m_og) = await _devices(
        hass, ["bad", "bad_og"], {"bad": bad.id, "bad_og": bad_og.id}
    )
    entry = _global_entry(
        {
            bad.id: _area_config(bad.id, "Bad", lamp_bad, m_bad),
            bad_og.id: _area_config(bad_og.id, "Bad OG", lamp_og, m_og),
        }
    )
    await _setup(hass, entry)
    registry = er.async_get(hass)
    og_before = {
        e.entity_id: (e.id, e.unique_id)
        for e in registry.entities.values()
        if e.platform == DOMAIN and "bad_og" in e.entity_id
    }
    areas.async_update(bad.id, name="Bad EG")
    await hass.async_block_till_done()
    await _advance(hass, 5)
    og_after = {
        e.entity_id: (e.id, e.unique_id)
        for e in registry.entities.values()
        if e.platform == DOMAIN and "bad_og" in e.entity_id
    }
    assert og_after == og_before
    renamed = [
        e.entity_id
        for e in registry.entities.values()
        if e.platform == DOMAIN
        and e.config_entry_id == entry.entry_id
        and e.entity_id.startswith("switch.adaptive_areas_light_groups_bad_")
        and "bad_og" not in e.entity_id
    ]
    assert renamed == [_switch("bad_eg")]


# R09, R10, R11, R12, R24 ----------------------------------------------------------


async def test_r09_r10_r24_deleting_an_area_removes_only_its_generated_entities(
    hass,
) -> None:
    """Delete one of two Areas: its entities and device go, everything else stays."""
    await _lux(hass, BRIGHT_LUX)
    areas = ar.async_get(hass)
    hall = areas.async_create("Hall")
    office = areas.async_create("Office")
    (lamp_hall, lamp_office), (m_hall, m_office) = await _devices(
        hass, ["hall", "office"], {"hall": hall.id, "office": office.id}
    )
    entry = _global_entry(
        {
            hall.id: _area_config(hall.id, "Hall", lamp_hall, m_hall),
            office.id: _area_config(office.id, "Office", lamp_office, m_office),
        }
    )
    await _setup(hass, entry)
    registry = er.async_get(hass)
    office_before = {
        e.entity_id: e.id for e in registry.entities.values() if "office" in e.entity_id
    }
    hall_generated = {e for e in _registered(hass, entry) if "_hall" in e}
    assert hall_generated

    assert await async_delete_area(hass, hall.id) == {}

    assert not hall_generated & _registered(hass, entry)
    assert not any(hass.states.get(e) for e in hall_generated)
    assert not [
        device
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
        if area_device_identifier(hall.id) in device.identifiers
    ]
    # Physical devices of the deleted Area and the other Area are unchanged.
    assert registry.async_get(lamp_hall) is not None
    assert registry.async_get(m_hall) is not None
    office_after = {
        e.entity_id: e.id for e in registry.entities.values() if "office" in e.entity_id
    }
    assert office_after == office_before
    await _enable(hass, _switch("office"))
    calls = _record_calls(hass)
    await _motion(hass, m_office, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("office")) == 1


async def test_r11_r12_delete_last_area_and_create_it_again(hass) -> None:
    """The GlobalEntry stays loaded without Areas; re-creating gives one clean set."""
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    # A completed migration keeps its metadata in the options.
    entry = _global_entry(
        {hall.id: _area_config(hall.id, "Hall", lamp, motion)},
        **{
            CONF_MIGRATION: MigrationState(
                1, MigrationPhase.COMPLETE, [], None, []
            ).as_dict()
        },
    )
    await _setup(hass, entry)
    first = sorted(_registered(hass, entry))
    assert await async_delete_area(hass, hall.id) == {}
    assert entry.state is ConfigEntryState.LOADED
    assert _registered(hass, entry) == set()
    assert get_runtime_areas_for_entry(hass, entry) == []

    _created, errors = await async_create_area(
        hass, hall.id, _area_config(hall.id, "Hall", lamp, motion)
    )
    assert errors == {}
    again = sorted(_registered(hass, entry))
    assert again == first
    assert not [e for e in again if e.rsplit("_", 1)[-1].isdigit()]


# R16, R17, R27 ---------------------------------------------------------------------


async def test_r16_r17_orphaned_area_devices_are_removed_ambiguous_entities_stay(
    hass,
) -> None:
    """Leftovers of an Area deleted earlier are removed; an ownerless entity stays."""
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    gone = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={area_device_identifier("gone")}
    )
    orphan = registry.async_get_or_create(
        "switch",
        DOMAIN,
        "adaptive_areas_light_groups_switch_gone_light_control",
        config_entry=entry,
        device_id=gone.id,
    )
    ambiguous = registry.async_get_or_create(
        "switch", DOMAIN, "adaptive_areas_unknown_switch_legacy", config_entry=entry
    )
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert registry.async_get(orphan.entity_id) is None
    assert devices.async_get(gone.id) is None
    assert registry.async_get(ambiguous.entity_id) is not None
    assert _live(hass, _switch("hall"))


async def test_r27_unavailable_configured_lamp_keeps_its_group(hass) -> None:
    """A configured lamp that is temporarily unavailable is no reason to clean up."""
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    group_entry = er.async_get(hass).async_get(_group("hall"))
    hass.states.async_set(lamp, "unavailable")
    await _reload(hass, entry)
    assert er.async_get(hass).async_get(_group("hall")).id == group_entry.id
    assert _live(hass, _group("hall"))


# R15 ------------------------------------------------------------------------------


async def test_r15_migration_of_bad_and_bad_og_keeps_identities(hass) -> None:
    """Legacy entries for "Bad" and "Bad OG" migrate without identity changes."""
    from tests.helpers import get_basic_config_entry_data
    from tests.const import MockAreaIds

    areas = ar.async_get(hass)
    bad = areas.async_create("Bad")
    bad_og = areas.async_create("Bad OG")
    legacy = []
    for area in (bad, bad_og):
        data = get_basic_config_entry_data(MockAreaIds.KITCHEN)
        data.update({"id": area.id, "name": area.name})
        legacy.append(MockConfigEntry(domain=DOMAIN, data=data))
    for entry in legacy:
        entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    before = {
        e.entity_id: e.unique_id
        for entry in legacy
        for e in registry.entities.get_entries_for_config_entry_id(entry.entry_id)
    }
    assert before

    state = await async_run_single_global_entry_migration(hass)

    assert state.migration_phase is MigrationPhase.COMPLETE
    (global_entry,) = get_global_entries(hass)
    after = {
        e.entity_id: e.unique_id
        for e in registry.entities.get_entries_for_config_entry_id(
            global_entry.entry_id
        )
    }
    assert after == before
    assert (
        registry.async_get(
            "binary_sensor.adaptive_areas_presence_tracking_bad_og_area_state"
        ).area_id
        == bad_og.id
    )


# R18, R20, R23 ---------------------------------------------------------------------


async def test_r18_repeated_reloads_send_one_command_per_event(hass) -> None:
    """Three reload cycles: one ON per DARK transition, no leaked listener."""
    await _lux(hass, BRIGHT_LUX)
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    await _enable(hass, _switch("hall"))
    await _motion(hass, motion, STATE_ON)
    calls = _record_calls(hass)
    listeners = []
    for cycle in range(3):
        await _reload(hass, entry)
        listeners.append(dict(hass.bus.async_listeners()))
        calls.clear()
        await _lux(hass, DARK_LUX)
        assert _group_calls(calls, "turn_on", _group("hall")) == 1, cycle
        await _lux(hass, BRIGHT_LUX)
        assert _group_calls(calls, "turn_off", _group("hall")) == 1, cycle
    assert listeners[1:] == [listeners[1]] * 2


async def test_r20_failed_platform_unload_is_not_a_successful_unload(hass) -> None:
    """The entry reports FAILED_UNLOAD, keeps its runtime; deletion reports an error."""
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    generated = _registered(hass, entry)
    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ):
        errors = await async_delete_area(hass, hall.id)
    assert errors and "base" in errors
    assert entry.state is ConfigEntryState.FAILED_UNLOAD
    assert get_runtime_areas_for_entry(hass, entry)
    # Nothing was removed from the registries.
    assert _registered(hass, entry) == generated
    # Let the debounced Repair evaluation of the still-loaded runtime finish.
    await _advance(hass, 5)


async def test_r23_own_registry_changes_cause_no_reload_loop(hass) -> None:
    """Setup writes registry entries of its own; none of them schedules a reload."""
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    with patch.object(
        hass.config_entries,
        "async_schedule_reload",
        wraps=hass.config_entries.async_schedule_reload,
    ) as reload:
        await _setup(hass, entry)
        await _reload(hass, entry)
        await _advance(hass, 10)
        assert reload.call_count == 0
        # Renaming one of the Area's own entities reloads once, then settles.
        er.async_get(hass).async_update_entity(
            _switch("hall"), new_entity_id="switch.hall_auto"
        )
        await hass.async_block_till_done()
        await _advance(hass, 5)
        await _advance(hass, 10)
        assert reload.call_count == 1


# R21 ------------------------------------------------------------------------------


async def test_r21_deleting_a_meta_child_updates_meta_sources(hass) -> None:
    """The deleted child leaves the floor's child list and presence sources."""
    og = fr.async_get(hass).async_create("OG")
    areas = ar.async_get(hass)
    hall = areas.async_create("Hall", floor_id=og.floor_id)
    office = areas.async_create("Office", floor_id=og.floor_id)
    (lamp_h, lamp_o), (m_h, m_o) = await _devices(
        hass, ["hall", "office"], {"hall": hall.id, "office": office.id}
    )
    entry = _global_entry(
        {
            hall.id: _area_config(hall.id, "Hall", lamp_h, m_h),
            office.id: _area_config(office.id, "Office", lamp_o, m_o),
            og.floor_id: _meta_config(og.floor_id, "OG"),
        }
    )
    await _setup(hass, entry)
    assert await async_delete_area(hass, hall.id) == {}
    meta = next(a for a in get_runtime_areas_for_entry(hass, entry) if a.is_meta())
    assert meta.child_areas == ["office"]
    assert meta.get_presence_sensors() == [
        "binary_sensor.adaptive_areas_presence_tracking_office_area_state"
    ]
    await _motion(hass, m_o, STATE_ON)
    assert (
        hass.states.get(
            "binary_sensor.adaptive_areas_presence_tracking_og_area_state"
        ).state
        == STATE_ON
    )


# R22 ------------------------------------------------------------------------------


async def test_r22_reload_on_registry_change_is_a_local_area_option(hass) -> None:
    """An Area that disabled registry reloads is not reloaded by its own devices."""
    areas = ar.async_get(hass)
    quiet = areas.async_create("Quiet")
    loud = areas.async_create("Loud")
    (lamp_q, lamp_l, spare_q, spare_l), (m_q, m_l, _a, _b) = await _devices(
        hass,
        ["quiet", "loud", "spare_q", "spare_l"],
        {"quiet": quiet.id, "loud": loud.id},
    )
    entry = _global_entry(
        {
            quiet.id: _area_config(
                quiet.id, "Quiet", lamp_q, m_q, reload_on_registry_change=False
            ),
            loud.id: _area_config(loud.id, "Loud", lamp_l, m_l),
        }
    )
    await _setup(hass, entry)
    registry = er.async_get(hass)
    with patch.object(
        hass.config_entries,
        "async_schedule_reload",
        wraps=hass.config_entries.async_schedule_reload,
    ) as reload:
        registry.async_update_entity(spare_q, area_id=quiet.id)
        await hass.async_block_till_done()
        await _advance(hass, 5)
        assert reload.call_count == 0
        registry.async_update_entity(spare_l, area_id=loud.id)
        await hass.async_block_till_done()
        await _advance(hass, 5)
        assert reload.call_count == 1


# R28 ------------------------------------------------------------------------------


async def test_r28_deleted_ha_area_keeps_other_areas_working(hass) -> None:
    """One deleted Home Assistant Area: the others run, a Repair names the entry."""
    await _lux(hass, BRIGHT_LUX)
    areas = ar.async_get(hass)
    hall = areas.async_create("Hall")
    office = areas.async_create("Office")
    (lamp_h, lamp_o), (m_h, m_o) = await _devices(
        hass, ["hall", "office"], {"hall": hall.id, "office": office.id}
    )
    entry = _global_entry(
        {
            hall.id: _area_config(hall.id, "Hall", lamp_h, m_h),
            office.id: _area_config(office.id, "Office", lamp_o, m_o),
        }
    )
    await _setup(hass, entry)
    issues = ir.async_get(hass)
    assert not [
        issue
        for (domain, _), issue in issues.issues.items()
        if domain == DOMAIN and issue.translation_key == "missing_area"
    ]
    hall_switch = er.async_get(hass).async_get(_switch("hall"))

    areas.async_delete(hall.id)
    await hass.async_block_till_done()
    await _advance(hass, 5)

    assert entry.state is ConfigEntryState.LOADED
    assert hall.id in entry.options[CONF_AREAS]
    assert [a.id for a in get_runtime_areas_for_entry(hass, entry)] == [office.id]
    # The skipped Area keeps its configuration and its generated entities.
    assert er.async_get(hass).async_get(_switch("hall")).id == hall_switch.id
    assert [
        issue
        for (domain, _), issue in issues.issues.items()
        if domain == DOMAIN and issue.translation_key == "missing_area"
    ]
    await _enable(hass, _switch("office"))
    calls = _record_calls(hass)
    await _motion(hass, m_o, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("office")) == 1


# Global options -------------------------------------------------------------------


async def test_global_light_sensor_comes_from_global_options(hass) -> None:
    """The brightness source of every Area is the GlobalEntry's global option."""
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    await _lux(hass, DARK_LUX)
    status = build_light_runtime_status(
        hass, get_runtime_areas_for_entry(hass, entry)[0]
    )
    assert status["light"]["illuminance"]["entity_id"] == LUX
    assert status["light"]["illuminance"]["value"] == float(DARK_LUX)


async def test_r24_orphaned_device_with_a_foreign_entity_is_left_alone(hass) -> None:
    """A removed Area's device that also holds another integration's entity stays."""
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    gone = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={area_device_identifier("gone")}
    )
    own = registry.async_get_or_create(
        "switch",
        DOMAIN,
        "adaptive_areas_light_groups_switch_gone_light_control",
        config_entry=entry,
        device_id=gone.id,
    )
    foreign = registry.async_get_or_create(
        "sensor", "foreign", "foreign_on_our_device", device_id=gone.id
    )
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert devices.async_get(gone.id) is not None
    assert registry.async_get(own.entity_id) is not None
    assert registry.async_get(foreign.entity_id) is not None
