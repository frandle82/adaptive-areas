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


async def test_r14_renaming_areas_and_floors_keeps_every_identity(hass) -> None:
    """Renaming a Home Assistant Area or floor changes no ID, also after a restart.

    1.6.18 and RC.3 derived the generated IDs from the current name, so a rename
    replaced every entity of the Area (and broke automations referring to them).
    The slug is now read back from the Area's registered entities.
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
    registry = er.async_get(hass)
    devices = dr.async_get(hass)

    def identities() -> dict:
        return {
            e.entity_id: (e.id, e.unique_id, e.device_id, e.config_entry_id)
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }

    before = identities()
    device_ids = {
        device.id
        for device in dr.async_entries_for_config_entry(devices, entry.entry_id)
    }
    areas.async_update(bad.id, name="Bad EG")
    fr.async_get(hass).async_update(og.floor_id, name="Obergeschoss")
    await hass.async_block_till_done()
    await _advance(hass, 5)
    assert identities() == before
    # Restart: unload and set up again.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert identities() == before
    assert {
        device.id
        for device in dr.async_entries_for_config_entry(devices, entry.entry_id)
    } == device_ids
    # The device shows the new name; control still uses the same entities.
    device = next(
        d
        for d in dr.async_entries_for_config_entry(devices, entry.entry_id)
        if area_device_identifier(bad.id) in d.identifiers
    )
    assert device.name == "Bad EG"
    await _enable(hass, _switch("bad"))
    calls = _record_calls(hass)
    await _motion(hass, m_bad, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("bad")) == 1
    # Deleting the renamed Area removes exactly its entities.
    bad_entities = {
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.device_id == device.id
    }
    assert await async_delete_area(hass, bad.id) == {}
    assert not bad_entities & set(identities())
    assert set(identities()) == set(before) - bad_entities


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


# Phase F: identity collisions --------------------------------------------------


def _presence(slug: str) -> str:
    return f"binary_sensor.adaptive_areas_presence_tracking_{slug}_area_state"


async def test_area_and_floor_with_the_same_slug_exist_independently(hass) -> None:
    """Floor "Keller" (ID keller) and Area "Keller" (ID keller_raum) coexist.

    On RC.3 both generated the same unique IDs; the registry refused the second.
    """
    keller = fr.async_get(hass).async_create("Keller")
    areas = ar.async_get(hass)
    raum = areas.async_create("Keller Raum", floor_id=keller.floor_id)
    areas.async_update(raum.id, name="Keller")
    (lamp,), (motion,) = await _devices(hass, ["keller"], {"keller": raum.id})
    entry = _global_entry(
        {
            raum.id: _area_config(raum.id, "Keller", lamp, motion),
            keller.floor_id: _meta_config(keller.floor_id, "Keller"),
        }
    )
    await _setup(hass, entry)
    runtime = {a.id: a for a in get_runtime_areas_for_entry(hass, entry)}
    assert runtime[raum.id].slug != runtime[keller.floor_id].slug
    for area in runtime.values():
        owned = generated_entities_for_area(hass, area)
        assert any(e.entity_id == area.area_state_entity_id() for e in owned)
        assert _live(hass, area.area_state_entity_id())
    unique_ids = [
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ]
    assert len(unique_ids) == len(set(unique_ids))
    before = {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    await _reload(hass, entry)
    assert {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    } == before


async def test_existing_area_keeps_its_ids_and_only_the_newcomer_changes(hass) -> None:
    """An Area added later with a colliding name leaves the existing Area untouched."""
    areas = ar.async_get(hass)
    first = areas.async_create("Bad OG")
    (lamp_a, lamp_b), (m_a, m_b) = await _devices(hass, ["a", "b"], {"a": first.id})
    entry = _global_entry({first.id: _area_config(first.id, "Bad OG", lamp_a, m_a)})
    await _setup(hass, entry)
    registry = er.async_get(hass)
    before = {
        e.entity_id: (e.id, e.unique_id)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    second = areas.async_create("Bad-OG")
    registry.async_update_entity(m_b, area_id=second.id)
    assert second.id != first.id
    _created, errors = await async_create_area(
        hass, second.id, _area_config(second.id, "Bad-OG", lamp_b, m_b)
    )
    assert errors == {}
    after = {
        e.entity_id: (e.id, e.unique_id)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert {k: v for k, v in after.items() if k in before} == before
    newcomer = next(
        a for a in get_runtime_areas_for_entry(hass, entry) if a.id == second.id
    )
    assert newcomer.slug == second.id
    assert _live(hass, _presence(second.id))
    assert _live(hass, _presence("bad_og"))
    await _enable(hass, _switch(second.id))
    calls = _record_calls(hass)
    await _lux(hass, BRIGHT_LUX)
    await _motion(hass, m_b, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group(second.id)) == 1
    assert _group_calls(calls, "turn_on", _group("bad_og")) == 0


# Phase F: Area Climate Health input ----------------------------------------------


def _climate_area(area_id: str, name: str, motion: str, moisture: str) -> dict:
    config, errors = validate_area_options(
        {"type": "interior"},
        {
            "include_entities": [motion, moisture],
            "features": {"environment": {}, "health": {}},
        },
    )
    assert config is not None, errors
    return {**config, "id": area_id, "name": name}


async def _climate_setup(hass, *, foreign_default: bool = False):
    hall = ar.async_get(hass).async_create("Hall")
    motion = MockBinarySensor(
        name="motion_hall", unique_id="motion_hall", device_class="motion"
    )
    moisture = MockBinarySensor(
        name="leak_hall", unique_id="leak_hall", device_class="moisture"
    )
    setup_test_component_platform(hass, "binary_sensor", [motion, moisture])
    assert await async_setup_component(
        hass, "binary_sensor", {"binary_sensor": {"platform": "test"}}
    )
    await hass.async_block_till_done()
    for entity in (motion, moisture):
        er.async_get(hass).async_update_entity(entity.entity_id, area_id=hall.id)
    motion = motion.entity_id
    if foreign_default:
        er.async_get(hass).async_get_or_create(
            "binary_sensor",
            "foreign",
            "takes_the_default_health_id",
            suggested_object_id="adaptive_areas_health_hall_health_problem",
        )
        hass.states.async_set(
            "binary_sensor.adaptive_areas_health_hall_health_problem", STATE_ON
        )
    entry = _global_entry(
        {hall.id: _climate_area(hall.id, "Hall", motion, moisture.entity_id)}
    )
    await _setup(hass, entry)
    return entry, moisture, get_runtime_areas_for_entry(hass, entry)[0]


async def test_climate_reads_the_registered_health_sensor(hass) -> None:
    """A real leak makes the Area's Health sensor ON; Area Climate reports it first."""
    _entry, moisture, area = await _climate_setup(hass)
    health = "binary_sensor.adaptive_areas_health_hall_health_problem"
    assert area.environment.health_entity == health
    assert area.environment.assessment["health_alert"] is False
    moisture.turn_on()
    await hass.async_block_till_done()
    await _advance(hass, 30)  # Area Climate debounces its evaluation natively.
    assert hass.states.get(health).state == STATE_ON
    assert area.environment.assessment["health_alert"] is True
    assert area.environment.assessment["dominant_decision"] == "health_alert"


async def test_climate_follows_a_renamed_health_sensor(hass) -> None:
    """After a rename and reload, the renamed Health sensor is the input."""
    entry, moisture, _area = await _climate_setup(hass)
    er.async_get(hass).async_update_entity(
        "binary_sensor.adaptive_areas_health_hall_health_problem",
        new_entity_id="binary_sensor.hall_leak_alarm",
    )
    await hass.async_block_till_done()
    await _reload(hass, entry)
    area = get_runtime_areas_for_entry(hass, entry)[0]
    assert area.environment.health_entity == "binary_sensor.hall_leak_alarm"
    moisture.turn_on()
    await hass.async_block_till_done()
    await _advance(hass, 30)  # Area Climate debounces its evaluation natively.
    assert area.environment.assessment["health_alert"] is True


async def test_climate_never_reads_a_foreign_entity_at_the_default_id(hass) -> None:
    """A foreign ON entity holding the default Health ID raises no alert."""
    _entry, _moisture, area = await _climate_setup(hass, foreign_default=True)
    assert area.environment.health_entity.endswith("_health_problem_2")
    assert area.environment.assessment["health_alert"] is False


async def test_climate_without_a_health_sensor_has_no_health_input(hass) -> None:
    """No distress sensor, no Health entity: no alert and the dimension is unknown."""
    hall = ar.async_get(hass).async_create("Hall")
    (_lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    config, _errors = validate_area_options(
        {"type": "interior"},
        {"include_entities": [motion], "features": {"environment": {}, "health": {}}},
    )
    entry = _global_entry({hall.id: {**config, "id": hall.id, "name": "Hall"}})
    await _setup(hass, entry)
    area = get_runtime_areas_for_entry(hass, entry)[0]
    assert area.environment.health_entity == ""
    assert area.environment.assessment["health_alert"] is False


# Phase F: cleanup safety ---------------------------------------------------------


async def _orphan_fixture(hass, **options):
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry(
        {hall.id: _area_config(hall.id, "Hall", lamp, motion)}, **options
    )
    entry.add_to_hass(hass)
    gone = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={area_device_identifier("gone")}
    )
    orphan = er.async_get(hass).async_get_or_create(
        "switch",
        DOMAIN,
        "adaptive_areas_light_groups_switch_gone_light_control",
        config_entry=entry,
        device_id=gone.id,
    )
    return entry, gone, orphan


async def test_no_cleanup_during_an_unfinished_migration(hass) -> None:
    """While a migration is not complete, nothing is removed."""
    entry, gone, orphan = await _orphan_fixture(
        hass,
        **{
            CONF_MIGRATION: MigrationState(
                1, MigrationPhase.VERIFY, [], None, []
            ).as_dict()
        },
    )
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(orphan.entity_id) is not None
    assert dr.async_get(hass).async_get(gone.id) is not None


async def test_no_cleanup_with_an_inconsistent_area_configuration(hass) -> None:
    """An Area entry whose stored ID does not match its key stops the cleanup."""
    entry, gone, orphan = await _orphan_fixture(hass)
    areas = dict(entry.options[CONF_AREAS])
    (key,) = areas
    areas[key] = {**areas[key], "id": "something_else"}
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_AREAS: areas}
    )
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(orphan.entity_id) is not None
    assert dr.async_get(hass).async_get(gone.id) is not None


async def test_disabled_generated_entity_survives_reload_and_cleanup(hass) -> None:
    """A generated entity the user disabled keeps its registry entry and setting."""
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    registry = er.async_get(hass)
    registry.async_update_entity(
        _group("hall", "all_lights"), disabled_by=er.RegistryEntryDisabler.USER
    )
    await hass.async_block_till_done()
    await _reload(hass, entry)
    await _reload(hass, entry)
    assert (
        registry.async_get(_group("hall", "all_lights")).disabled_by
        is er.RegistryEntryDisabler.USER
    )


# Phase F: light sequence, options flow, reload count ----------------------------


async def test_dark_bright_dark_sequence_before_and_after_reload(hass) -> None:
    """dark_on_bright_off: ON, OFF, ON with native forwarding, twice around a reload."""
    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry({hall.id: _area_config(hall.id, "Hall", lamp, motion)})
    await _setup(hass, entry)
    await _enable(hass, _switch("hall"))
    await _motion(hass, motion, STATE_ON)
    await _lux(hass, BRIGHT_LUX)
    calls = _record_calls(hass)
    for cycle in range(2):
        for lux, service, lamp_state in (
            (DARK_LUX, "turn_on", STATE_ON),
            (BRIGHT_LUX, "turn_off", "off"),
            (DARK_LUX, "turn_on", STATE_ON),
        ):
            calls.clear()
            await _lux(hass, lux)
            assert calls == [(service, [_group("hall")]), (service, [lamp])], cycle
            assert hass.states.get(lamp).state == lamp_state, cycle
        await _lux(hass, BRIGHT_LUX)
        await _reload(hass, entry)
        await _lux(hass, BRIGHT_LUX)


async def test_global_entry_offers_no_per_area_options_flow(hass) -> None:
    """The native "Configure" of the GlobalEntry is not offered (it crashed on RC.3)."""
    entry = _global_entry({})
    await _setup(hass, entry)
    assert entry.supports_options is False


async def test_registry_event_for_two_areas_reloads_once(hass) -> None:
    """A device move between two Areas is one debounced GlobalEntry reload."""
    areas = ar.async_get(hass)
    a = areas.async_create("Hall")
    b = areas.async_create("Office")
    (lamp_a, lamp_b, spare), (m_a, m_b, _m) = await _devices(
        hass, ["hall", "office", "spare"], {"hall": a.id, "office": b.id}
    )
    registry = er.async_get(hass)
    registry.async_update_entity(spare, area_id=a.id)
    entry = _global_entry(
        {
            a.id: _area_config(a.id, "Hall", lamp_a, m_a),
            b.id: _area_config(b.id, "Office", lamp_b, m_b),
        }
    )
    await _setup(hass, entry)
    with patch.object(
        hass.config_entries,
        "async_schedule_reload",
        wraps=hass.config_entries.async_schedule_reload,
    ) as reload:
        registry.async_update_entity(spare, area_id=b.id)
        await hass.async_block_till_done()
        await _advance(hass, 5)
        assert reload.call_count == 1


async def test_outage_recovery_override_and_clear_in_a_global_entry(hass) -> None:
    """Sensor outage, recovery, CLEAR with ALL-OFF and manual override, natively."""
    from homeassistant.core import Context

    hall = ar.async_get(hass).async_create("Hall")
    (lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    entry = _global_entry(
        {hall.id: _area_config(hall.id, "Hall", lamp, motion, clear_timeout=0)}
    )
    await _setup(hass, entry)
    await _enable(hass, _switch("hall"))
    await _lux(hass, BRIGHT_LUX)
    await _motion(hass, motion, STATE_ON)
    calls = _record_calls(hass)
    await _lux(hass, DARK_LUX)
    assert calls == [("turn_on", [_group("hall")]), ("turn_on", [lamp])]

    # A sensor outage alone, and its recovery to the same band, send nothing.
    calls.clear()
    hass.states.async_set(LUX, "unavailable")
    await hass.async_block_till_done()
    await _lux(hass, DARK_LUX)
    assert calls == []

    # CLEAR: the ALL group switches off once.
    await _motion(hass, motion, "off")
    await _advance(hass, 5)
    assert _group_calls(calls, "turn_off", _group("hall", "all_lights")) == 1
    assert hass.states.get(lamp).state == "off"

    # Occupied again: ON. A user switches the lamp off: no automatic ON until CLEAR.
    calls.clear()
    await _motion(hass, motion, STATE_ON)
    assert _group_calls(calls, "turn_on", _group("hall")) == 1
    user = await hass.auth.async_create_user("phase-f")
    await hass.services.async_call(
        "light",
        "turn_off",
        {"entity_id": lamp},
        blocking=True,
        context=Context(user_id=user.id),
    )
    await hass.async_block_till_done()
    calls.clear()
    await _lux(hass, BRIGHT_LUX)
    await _lux(hass, DARK_LUX)
    assert not [c for c in calls if c[0] == "turn_on"]
    assert hass.states.get(_group("hall")).attributes["manual_override"] is True


async def test_shared_lamp_in_a_global_entry_is_never_switched(hass) -> None:
    """Negative safety test: a stored shared lamp blocks both Areas' groups."""
    areas = ar.async_get(hass)
    hall = areas.async_create("Hall")
    office = areas.async_create("Office")
    (lamp, _spare), (m_hall, m_office) = await _devices(
        hass, ["hall", "office"], {"hall": hall.id, "office": office.id}
    )
    # Stored directly: a save through the panel or options flow would refuse it.
    entry = _global_entry(
        {
            hall.id: _area_config(hall.id, "Hall", lamp, m_hall),
            office.id: _area_config(office.id, "Office", lamp, m_office),
        }
    )
    await _setup(hass, entry)
    await _enable(hass, _switch("hall"))
    await _enable(hass, _switch("office"))
    await _lux(hass, BRIGHT_LUX)
    calls = _record_calls(hass)
    await _motion(hass, m_hall, STATE_ON)
    await _motion(hass, m_office, STATE_ON)
    await _lux(hass, DARK_LUX)
    assert ("turn_on", [lamp]) not in calls
    assert hass.states.get(lamp).state == "off"


# Phase G: Meta Area ALL group on the first setup ---------------------------------


async def test_meta_all_group_exists_on_the_first_setup(hass) -> None:
    """A floor's ALL group is created by the very first setup, with native members.

    On RC.3 and up to 3acee62 it appeared only from the second setup on: the Meta
    Area read its children's light groups from the registry before they existed.
    """
    await _lux(hass, BRIGHT_LUX)
    og = fr.async_get(hass).async_create("OG")
    areas = ar.async_get(hass)
    hall = areas.async_create("Hall", floor_id=og.floor_id)
    office = areas.async_create("Office", floor_id=og.floor_id)
    (lamp_h, lamp_o), (m_h, m_o) = await _devices(
        hass, ["hall", "office"], {"hall": hall.id, "office": office.id}
    )
    entry = _global_entry(
        {
            hall.id: _area_config(hall.id, "Hall", lamp_h, m_h, clear_timeout=0),
            office.id: _area_config(office.id, "Office", lamp_o, m_o),
            og.floor_id: _meta_config(og.floor_id, "OG"),
        }
    )
    assert not er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    calls = _record_calls(hass)
    await _setup(hass, entry)
    meta_all = _group("og", "all_lights")
    assert _live(hass, meta_all)
    members = set(hass.states.get(meta_all).attributes["entity_id"])
    assert {
        _group("hall"),
        _group("hall", "all_lights"),
        _group("office"),
        _group("office", "all_lights"),
    } <= members
    assert not {lamp_h, lamp_o} & members

    # The Meta group is never switched automatically; the child's ALL-OFF is.
    await _enable(hass, _switch("hall"))
    await _motion(hass, m_h, STATE_ON)
    await _lux(hass, DARK_LUX)
    await _motion(hass, m_h, "off")
    await _advance(hass, 5)
    assert not [c for c in calls if meta_all in c[1]]
    assert _group_calls(calls, "turn_off", _group("hall", "all_lights")) == 1

    # Manual operation of the Meta group still works natively.
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": meta_all}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(lamp_o).state == STATE_ON

    # Reload: same set of entities, no duplicates.
    before = sorted(_registered(hass, entry))
    await _reload(hass, entry)
    assert sorted(_registered(hass, entry)) == before
    assert not [e for e in before if e.rsplit("_", 1)[-1].isdigit()]


async def test_meta_without_lit_children_has_no_all_group(hass) -> None:
    """A Meta Area whose children have no light groups gets no ALL group."""
    og = fr.async_get(hass).async_create("OG")
    hall = ar.async_get(hass).async_create("Hall", floor_id=og.floor_id)
    (_lamp,), (motion,) = await _devices(hass, ["hall"], {"hall": hall.id})
    config, _errors = validate_area_options(
        {"type": "interior"}, {"include_entities": [motion]}
    )
    entry = _global_entry(
        {
            hall.id: {**config, "id": hall.id, "name": "Hall"},
            og.floor_id: _meta_config(og.floor_id, "OG"),
        }
    )
    await _setup(hass, entry)
    await _reload(hass, entry)
    assert hass.states.get(_group("og", "all_lights")) is None
    assert entry.state is ConfigEntryState.LOADED


# Phase G: R26 dynamic native group membership in a GlobalEntry --------------------


async def test_r26_native_group_membership_change_in_a_global_entry(hass) -> None:
    """A real native light group (group helper) gains a lamp another Area owns.

    Negative safety test with a shared lamp. Membership changes through the helper's
    options, as a user would; the Adaptive Areas configuration is not written and no
    device is assigned. Hall owns the native group NESTED (lamp_hall), Office owns
    lamp_office, Dining owns lamp_dining and is never affected.
    """
    from homeassistant.core import Context

    from custom_components.adaptive_areas.dashboard import (
        build_light_runtime_status,
    )

    areas = ar.async_get(hass)
    hall, office, dining = (areas.async_create(n) for n in ("Hall", "Office", "Dining"))
    (lamp_h, lamp_o, lamp_d), (m_h, m_o, m_d) = await _devices(
        hass,
        ["hall", "office", "dining"],
        {"hall": hall.id, "office": office.id, "dining": dining.id},
    )
    helper = MockConfigEntry(
        domain="group",
        title="Nested hall",
        options={
            "group_type": "light",
            "name": "Nested hall",
            "entities": [lamp_h],
            "hide_members": False,
            "all": False,
        },
    )
    helper.add_to_hass(hass)
    assert await hass.config_entries.async_setup(helper.entry_id)
    await hass.async_block_till_done()
    nested = "light.nested_hall"
    assert hass.states.get(nested).attributes["entity_id"] == [lamp_h]

    entry = _global_entry(
        {
            hall.id: _area_config(hall.id, "Hall", nested, m_h, clear_timeout=0),
            office.id: _area_config(office.id, "Office", lamp_o, m_o, clear_timeout=0),
            dining.id: _area_config(dining.id, "Dining", lamp_d, m_d),
        }
    )
    await _setup(hass, entry)
    stored = dict(entry.options)
    for slug in ("hall", "office", "dining"):
        await _enable(hass, _switch(slug))
    await _lux(hass, BRIGHT_LUX)
    for motion in (m_h, m_o, m_d):
        await _motion(hass, motion, STATE_ON)
    calls = _record_calls(hass)
    await _lux(hass, DARK_LUX)
    for slug in ("hall", "office", "dining"):
        assert _group_calls(calls, "turn_on", _group(slug)) == 1, slug

    async def membership(members: list[str]) -> None:
        """Change the members through the group helper's native options flow."""
        flow = await hass.config_entries.options.async_init(helper.entry_id)
        result = await hass.config_entries.options.async_configure(
            flow["flow_id"],
            {"entities": members, "hide_members": False, "all": False},
        )
        assert result["type"] == "create_entry", result
        await hass.async_block_till_done()
        await _advance(hass, 5)

    def blocked() -> dict[str, bool]:
        return {
            f"{area.slug}:{group['category']}": group["ownership_blocked"]
            for area in get_runtime_areas_for_entry(hass, entry)
            for group in build_light_runtime_status(hass, area)["light"][
                "control_path"
            ]["groups"]
            if group["entity_id"] is not None
        }

    assert not any(blocked().values())

    # Conflict: the native group now also switches the Office lamp.
    await membership([lamp_h, lamp_o])
    assert set(hass.states.get(nested).attributes["entity_id"]) == {lamp_h, lamp_o}
    assert dict(entry.options) == stored
    state = blocked()
    assert state["hall:overhead_lights"] and state["hall:all_lights"]
    assert state["office:overhead_lights"] and state["office:all_lights"]
    assert not state["dining:overhead_lights"] and not state["dining:all_lights"]

    calls.clear()
    await _lux(hass, BRIGHT_LUX)
    await _lux(hass, DARK_LUX)
    # CLEAR in Office: its ALL-OFF would switch the shared lamp and is suppressed.
    await _motion(hass, m_o, "off")
    await _advance(hass, 5)
    shared = {_group("hall"), _group("hall", "all_lights"), nested, lamp_o}
    shared |= {_group("office"), _group("office", "all_lights")}
    assert not [c for c in calls if set(c[1]) & shared], calls
    assert _group_calls(calls, "turn_off", _group("dining")) == 1
    assert _group_calls(calls, "turn_on", _group("dining")) == 1

    # Manual operation stays possible.
    user = await hass.auth.async_create_user("phase-g")
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": lamp_o},
        blocking=True,
        context=Context(user_id=user.id),
    )
    assert hass.states.get(lamp_o).state == STATE_ON

    # Conflict removed: control returns on the next relevant event.
    await membership([lamp_h])
    assert not any(blocked().values())
    await _motion(hass, m_o, STATE_ON)
    calls.clear()
    await _lux(hass, BRIGHT_LUX)
    await _lux(hass, DARK_LUX)
    assert _group_calls(calls, "turn_on", _group("hall")) == 1
    assert _group_calls(calls, "turn_on", _group("dining")) == 1
    assert dict(entry.options) == stored


# Phase G: identity edge cases -----------------------------------------------------


async def _renamable_area(hass):
    await _lux(hass, BRIGHT_LUX)
    bad = ar.async_get(hass).async_create("Bad")
    (lamp,), (motion,) = await _devices(hass, ["bad"], {"bad": bad.id})
    entry = _global_entry({bad.id: _area_config(bad.id, "Bad", lamp, motion)})
    await _setup(hass, entry)
    return bad, entry, motion


def _ids(hass, entry) -> dict:
    return {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_disabled_presence_entity_keeps_identity_on_rename(hass) -> None:
    """A disabled presence state entity still carries the Area's identity."""
    bad, entry, _motion_id = await _renamable_area(hass)
    er.async_get(hass).async_update_entity(
        _presence("bad"), disabled_by=er.RegistryEntryDisabler.USER
    )
    before = _ids(hass, entry)
    ar.async_get(hass).async_update(bad.id, name="Gästebad")
    await hass.async_block_till_done()
    await _advance(hass, 5)
    await _reload(hass, entry)
    assert _ids(hass, entry) == before


async def test_removed_presence_entity_does_not_change_the_identity(hass) -> None:
    """One missing registry entry is no reason for a new identity.

    The presence entity is removed from the registry, the Area is renamed: the
    other entities of its device still carry the slug, all IDs stay the same.
    """
    bad, entry, _motion_id = await _renamable_area(hass)
    registry = er.async_get(hass)
    before = _ids(hass, entry)
    registry.async_remove(_presence("bad"))
    await hass.async_block_till_done()
    ar.async_get(hass).async_update(bad.id, name="Gästebad")
    await hass.async_block_till_done()
    await _advance(hass, 5)
    await _reload(hass, entry)
    assert _ids(hass, entry) == before
    assert _live(hass, _presence("bad"))


async def test_fallback_id_part_that_is_taken_gets_a_unique_one(hass) -> None:
    """Name slug and Area ID of a newcomer are both taken: a type suffix is used."""
    areas = ar.async_get(hass)
    first = areas.async_create("Bad OG")  # bad_og
    newcomer = areas.async_create("Bad-OG")  # bad_og_2, slug bad_og
    third = areas.async_create("Bad OG 2")  # bad_og_2 as slug, other ID
    assert newcomer.id == "bad_og_2" and third.id != newcomer.id
    (l1, l2, l3), (m1, m2, m3) = await _devices(
        hass, ["a", "b", "c"], {"a": first.id, "b": newcomer.id, "c": third.id}
    )
    entry = _global_entry(
        {
            first.id: _area_config(first.id, "Bad OG", l1, m1),
            third.id: _area_config(third.id, "Bad OG 2", l3, m3),
        }
    )
    await _setup(hass, entry)
    before = _ids(hass, entry)
    _created, errors = await async_create_area(
        hass, newcomer.id, _area_config(newcomer.id, "Bad-OG", l2, m2)
    )
    assert errors == {}
    slugs = {a.id: a.slug for a in get_runtime_areas_for_entry(hass, entry)}
    assert slugs[first.id] == "bad_og" and slugs[third.id] == "bad_og_2"
    assert slugs[newcomer.id] == "bad_og_area"
    after = _ids(hass, entry)
    assert {k: v for k, v in after.items() if k in before} == before
    assert len(set(after.values())) == len(after)


async def test_no_cleanup_without_global_options(hass) -> None:
    """A GlobalEntry whose options lack the global structure removes nothing."""
    entry, gone, orphan = await _orphan_fixture(hass)
    options = dict(entry.options)
    options.pop(CONF_GLOBAL_OPTIONS)
    hass.config_entries.async_update_entry(entry, options=options)
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(orphan.entity_id) is not None
    assert dr.async_get(hass).async_get(gone.id) is not None


async def test_no_cleanup_of_a_device_with_two_area_identifiers(hass) -> None:
    """A device that names two Areas has no unambiguous owner and stays."""
    entry, gone, orphan = await _orphan_fixture(hass)
    dr.async_get(hass).async_update_device(
        gone.id,
        new_identifiers={
            area_device_identifier("gone"),
            area_device_identifier("also_gone"),
        },
    )
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(orphan.entity_id) is not None
    assert dr.async_get(hass).async_get(gone.id) is not None
