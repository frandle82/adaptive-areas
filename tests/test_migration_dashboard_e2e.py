"""Dashboard WebSocket regression coverage for the global-entry migration."""

from types import SimpleNamespace
from datetime import timedelta

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.util.dt import utcnow

from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    DOMAIN,
)
from custom_components.adaptive_areas.migration import (
    MigrationPhase,
    get_global_entries,
)
from custom_components.adaptive_areas.repairs import (
    SingleGlobalEntryMigrationRepairFlow,
    async_evaluate_single_global_entry_migration,
)
from custom_components.adaptive_areas.websocket import async_register_websocket_commands
from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
)
from tests.mocks import MockBinarySensor

REGULAR_AREAS = (
    MockAreaIds.KITCHEN,
    MockAreaIds.LIVING_ROOM,
    MockAreaIds.MASTER_BEDROOM,
)
META_AREAS = (MockAreaIds.FIRST_FLOOR, MockAreaIds.GLOBAL)


class _Connection:
    """Minimal registered WebSocket connection for read-only commands."""

    user = SimpleNamespace(is_admin=True)

    def __init__(self) -> None:
        self.result = None
        self.events = []
        self.subscriptions = {}

    def send_result(self, _message_id, result=None) -> None:
        self.result = result

    def send_event(self, _message_id, event) -> None:
        self.events.append(event)


async def _call(hass, command: str, **data):
    """Use the registered production handler and its schema."""
    connection = _Connection()
    handler, schema = hass.data["websocket_api"][command]
    message = {"id": 1, "type": command, **data}
    handler(hass, connection, message if schema is False else schema(message))
    await hass.async_block_till_done()
    return connection


async def _dashboard_snapshot(hass) -> dict:
    """Capture only public dashboard data, omitting expected container ownership."""
    overview = (await _call(hass, "adaptive_areas/get_overview")).result
    details = {
        area["id"]: (
            await _call(hass, "adaptive_areas/get_area", area_id=area["id"])
        ).result
        for area in overview["areas"]
    }
    configuration = (await _call(hass, "adaptive_areas/get_area_configuration")).result[
        "areas"
    ]
    return {
        "overview": overview,
        "details": details,
        "configuration": [
            {key: value for key, value in item.items() if key != "entry_id"}
            for item in configuration
        ],
    }


def _source_ids(snapshot: dict, area_id: str) -> set[str]:
    """Return public detail source identities for one logical Area."""
    return {source["entity_id"] for source in snapshot["details"][area_id]["sources"]}


def _assert_kitchen_subscription(events: list[dict]) -> None:
    """Assert a Kitchen source updates only Meta parents, not sibling Areas."""
    area_ids = [event["area"]["id"] for event in events]
    assert MockAreaIds.KITCHEN.value in area_ids
    assert set(area_ids) <= {
        MockAreaIds.KITCHEN.value,
        MockAreaIds.FIRST_FLOOR.value,
        MockAreaIds.GLOBAL.value,
    }
    assert len({repr(event) for event in events}) == len(events)


async def test_repair_migration_preserves_dashboard_read_model(hass) -> None:
    """Dashboard reads retain logical Areas through Repair migration and reload."""
    sources = {
        area: [
            MockBinarySensor(
                name=f"motion_{area.value}",
                unique_id=f"motion_{area.value}",
                device_class=BinarySensorDeviceClass.MOTION,
            )
        ]
        for area in REGULAR_AREAS
    }
    await setup_mock_entities(hass, "binary_sensor", sources)
    entries = []
    feature_sets = (
        {CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}},
        {CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}},
        {CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}},
    )
    for area, features in zip(REGULAR_AREAS, feature_sets, strict=True):
        data = get_basic_config_entry_data(area)
        data[CONF_ENABLED_FEATURES] = features
        entries.append(MockConfigEntry(domain=DOMAIN, data=data))
    for area in META_AREAS:
        data = get_basic_config_entry_data(area)
        data[CONF_ENABLED_FEATURES] = {
            CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
        }
        entries.append(MockConfigEntry(domain=DOMAIN, data=data))
    await init_integration(hass, entries, areas=list(REGULAR_AREAS))
    async_register_websocket_commands(hass)
    # Meta Areas reload after their child Areas have published their entities.
    async_fire_time_changed(hass, utcnow() + timedelta(seconds=4))
    await hass.async_block_till_done()

    legacy_entry_ids = {entry.entry_id for entry in entries}
    before = await _dashboard_snapshot(hass)
    assert {area["id"] for area in before["overview"]["areas"]} == {
        area.value for area in (*REGULAR_AREAS, *META_AREAS)
    }
    assert len(before["configuration"]) == 5
    floor_sources_before = _source_ids(before, MockAreaIds.FIRST_FLOOR.value)
    global_sources_before = _source_ids(before, MockAreaIds.GLOBAL.value)
    assert {
        "binary_sensor.adaptive_areas_aggregates_kitchen_aggregate_motion",
        "binary_sensor.adaptive_areas_aggregates_living_room_aggregate_motion",
    } <= floor_sources_before
    assert {
        f"binary_sensor.adaptive_areas_aggregates_{area.value}_aggregate_motion"
        for area in REGULAR_AREAS
    } <= global_sources_before

    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["type"] == "create_entry"
    (global_entry,) = get_global_entries(hass)
    assert (
        global_entry.options["migration"]["migration_phase"] == MigrationPhase.COMPLETE
    )
    assert hass.config_entries.async_entries(DOMAIN) == [global_entry]

    after = await _dashboard_snapshot(hass)
    assert after["configuration"] == before["configuration"]
    assert after["overview"] == before["overview"]
    assert after["details"] == before["details"]
    assert _source_ids(after, MockAreaIds.FIRST_FLOOR.value) == floor_sources_before
    assert _source_ids(after, MockAreaIds.GLOBAL.value) == global_sources_before
    assert all(entry_id not in str(after) for entry_id in legacy_entry_ids)
    assert len(after["overview"]["areas"]) == 5
    assert len({area["id"] for area in after["overview"]["areas"]}) == 5

    subscription = await _call(hass, "adaptive_areas/subscribe_updates")
    kitchen_motion = sources[MockAreaIds.KITCHEN][0].entity_id
    kitchen_attributes = dict(hass.states.get(kitchen_motion).attributes)
    hass.states.async_set(kitchen_motion, STATE_ON, kitchen_attributes)
    await hass.async_block_till_done()
    _assert_kitchen_subscription(subscription.events)
    subscription.subscriptions[1]()
    old_event_count = len(subscription.events)
    after_update = await _dashboard_snapshot(hass)

    assert await hass.config_entries.async_reload(global_entry.entry_id)
    await hass.async_block_till_done()
    restarted = await _dashboard_snapshot(hass)
    assert restarted == after_update
    assert hass.config_entries.async_entries(DOMAIN) == [global_entry]
    assert _source_ids(restarted, MockAreaIds.FIRST_FLOOR.value) == floor_sources_before
    assert _source_ids(restarted, MockAreaIds.GLOBAL.value) == global_sources_before

    restarted_subscription = await _call(hass, "adaptive_areas/subscribe_updates")
    hass.states.async_set(kitchen_motion, STATE_OFF, kitchen_attributes)
    await hass.async_block_till_done()
    assert len(subscription.events) == old_event_count
    _assert_kitchen_subscription(restarted_subscription.events)
