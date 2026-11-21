"""Dashboard presence semantics (V06-P1).

`occupied` stays the boolean decision of the existing automation. The explicit
`presence.state` distinguishes occupied, clear and unknown. A Physical Area is
clear only with an available presence source; a Meta-Area is clear only when
every loaded member is clear. Automation decisions are not changed.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
import pytest

from custom_components.adaptive_areas.const import AREA_STATE_OCCUPIED
from custom_components.adaptive_areas.websocket import async_register_websocket_commands


class _Connection:
    def __init__(self, *, is_admin: bool) -> None:
        self.user = SimpleNamespace(is_admin=is_admin)
        self.result = None

    def send_result(self, _msg_id, result=None) -> None:
        self.result = result

    def send_error(self, _msg_id, code, message) -> None:
        raise AssertionError(f"unexpected error {code}: {message}")

    def send_event(self, _msg_id, event) -> None:  # pragma: no cover
        pass


async def _call(hass: HomeAssistant, connection: _Connection, command: str, **data):
    handler, schema = hass.data["websocket_api"][command]
    message = {"id": 1, "type": command, **data}
    handler(hass, connection, message if schema is False else schema(message))
    await hass.async_block_till_done()
    return connection.result


def _area(hass: HomeAssistant, area_id: str):
    from custom_components.adaptive_areas.websocket import _get_area  # noqa: PLC0415

    return _get_area(hass, area_id)


@pytest.fixture
async def multi_area(
    hass: HomeAssistant,
    all_areas_with_meta_config_entry,
    entities_binary_sensor_motion_all_areas_with_meta,
    _setup_integration_all_areas_with_meta,
):
    """Return a map of Area id to its motion sensor entity IDs."""
    async_register_websocket_commands(hass)
    sensors = {}
    for area, items in entities_binary_sensor_motion_all_areas_with_meta.items():
        sensors[str(area.value)] = [item.entity_id for item in items]
    return sensors


async def _overview(hass: HomeAssistant, *, admin: bool = True) -> dict:
    return await _call(hass, _Connection(is_admin=admin), "adaptive_areas/get_overview")


def _by_id(payload: dict) -> dict:
    return {item["id"]: item for item in payload["areas"]}


async def test_available_source_reports_occupied_or_clear(hass, multi_area) -> None:
    """1. An available source decides between occupied and clear."""
    hass.states.async_set(multi_area["kitchen"][0], "on")
    hass.states.async_set(multi_area["dining_room"][0], "off")
    await hass.async_block_till_done()
    areas = _by_id(await _overview(hass))
    assert areas["kitchen"]["presence"]["state"] == "occupied"
    assert areas["kitchen"]["occupied"] is True
    assert areas["dining_room"]["presence"]["state"] == "clear"
    assert areas["dining_room"]["occupied"] is False


async def test_no_available_source_without_decision_is_unknown(
    hass, multi_area
) -> None:
    """2. No available source and no decision: unknown, never clear."""
    hass.states.async_set(multi_area["front_yard"][0], "unavailable")
    await hass.async_block_till_done()
    area = _by_id(await _overview(hass))["front_yard"]
    assert area["presence"]["state"] == "unknown"
    assert area["presence"]["available"] == 0
    # The boolean contract is unchanged: it still reflects the automation decision.
    assert area["occupied"] is False


async def test_valid_hold_is_kept_without_available_sources(hass, multi_area) -> None:
    """3. A decision from the automation (for example a Presence Hold) wins."""
    hass.states.async_set(multi_area["garage"][0], "unavailable")
    await hass.async_block_till_done()
    area_obj = _area(hass, "garage")
    if AREA_STATE_OCCUPIED not in area_obj.states:
        area_obj.states.append(AREA_STATE_OCCUPIED)
    await hass.async_block_till_done()
    area = _by_id(await _overview(hass))["garage"]
    assert area["presence"]["state"] == "occupied"
    assert area["occupied"] is True


async def test_automation_decision_is_unchanged(hass, multi_area) -> None:
    """10. Reading the overview does not change the automation's decision."""
    hass.states.async_set(multi_area["living_room"][0], "unavailable")
    await hass.async_block_till_done()
    area_obj = _area(hass, "living_room")
    before = (list(area_obj.states), area_obj.is_occupied())
    await _overview(hass)
    await _overview(hass, admin=False)
    assert (list(area_obj.states), area_obj.is_occupied()) == before


async def test_meta_area_is_clear_only_when_all_members_are_clear(
    hass, multi_area
) -> None:
    """6. Meta-Area with known and unknown members is unknown, not clear."""
    for area_id in ("kitchen", "dining_room", "living_room"):
        hass.states.async_set(multi_area[area_id][0], "off")
    await hass.async_block_till_done()
    areas = _by_id(await _overview(hass))
    assert areas["first_floor"]["presence"]["state"] == "clear"

    hass.states.async_set(multi_area["living_room"][0], "unavailable")
    await hass.async_block_till_done()
    areas = _by_id(await _overview(hass))
    assert areas["first_floor"]["presence"]["state"] == "unknown"


async def test_meta_area_with_an_occupied_member_is_occupied(hass, multi_area) -> None:
    """6b. One occupied member makes the Meta-Area occupied."""
    hass.states.async_set(multi_area["kitchen"][0], "on")
    hass.states.async_set(multi_area["dining_room"][0], "off")
    hass.states.async_set(multi_area["living_room"][0], "unavailable")
    await hass.async_block_till_done()
    areas = _by_id(await _overview(hass))
    assert areas["first_floor"]["presence"]["state"] == "occupied"


async def test_admin_and_non_admin_get_the_same_presence_state(
    hass, multi_area
) -> None:
    """8. Redaction keeps the presence state identical for both roles."""
    hass.states.async_set(multi_area["front_yard"][0], "unavailable")
    await hass.async_block_till_done()
    admin = _by_id(await _overview(hass, admin=True))["front_yard"]
    user = _by_id(await _overview(hass, admin=False))["front_yard"]
    assert admin["presence"]["state"] == user["presence"]["state"] == "unknown"
    assert admin["occupied"] == user["occupied"] is False


async def test_detail_matches_overview(hass, multi_area) -> None:
    """7. The Area detail reports the same presence state as the overview."""
    hass.states.async_set(multi_area["garage"][0], "unavailable")
    await hass.async_block_till_done()
    overview = _by_id(await _overview(hass))["garage"]
    detail = await _call(
        hass,
        _Connection(is_admin=True),
        "adaptive_areas/get_area",
        area_id="garage",
    )
    assert overview["presence"]["state"] == "unknown"
    assert detail["presence"]["state"] == overview["presence"]["state"]


async def test_subscription_payload_reflects_state_change(hass, multi_area) -> None:
    """9. A state change is visible in the next overview (subscriptions re-read it)."""
    hass.states.async_set(multi_area["kitchen"][0], "off")
    await hass.async_block_till_done()
    assert _by_id(await _overview(hass))["kitchen"]["presence"]["state"] == "clear"
    hass.states.async_set(multi_area["kitchen"][0], "unavailable")
    await hass.async_block_till_done()
    assert _by_id(await _overview(hass))["kitchen"]["presence"]["state"] == "unknown"


async def test_physical_counts_match_the_area_cards(hass, multi_area) -> None:
    """Physical counts use the same presence semantics as the Area cards."""
    hass.states.async_set(multi_area["kitchen"][0], "on")
    hass.states.async_set(multi_area["dining_room"][0], "off")
    hass.states.async_set(multi_area["front_yard"][0], "unavailable")
    await hass.async_block_till_done()
    payload = await _overview(hass)
    physical = [area for area in payload["areas"] if area["type"] != "meta"]
    counts = payload["counts"]
    card_occupied = sum(area["presence"]["state"] == "occupied" for area in physical)
    card_clear = sum(area["presence"]["state"] == "clear" for area in physical)
    card_unknown = sum(area["presence"]["state"] == "unknown" for area in physical)
    assert counts["physical_occupied"] == card_occupied
    assert counts["physical_clear"] == card_clear
    assert counts["physical_unknown"] == card_unknown
    assert (
        counts["physical_occupied"]
        + counts["physical_clear"]
        + counts["physical_unknown"]
        == len(physical)
        == counts["areas"]
    )


async def test_physical_counts_exclude_meta_areas(hass, multi_area) -> None:
    """Negative check: the legacy `occupied` count includes Meta-Areas, the physical count does not."""
    hass.states.async_set(multi_area["kitchen"][0], "on")
    await hass.async_block_till_done()
    counts = (await _overview(hass))["counts"]
    assert counts["occupied"] > counts["physical_occupied"]
    assert counts["physical_occupied"] == 1


async def test_unknown_area_is_not_counted_as_clear(hass, multi_area) -> None:
    """Negative check: a physical Area without a source is unknown, never clear."""
    hass.states.async_set(multi_area["garage"][0], "unavailable")
    await hass.async_block_till_done()
    counts = (await _overview(hass))["counts"]
    areas = _by_id(await _overview(hass))
    assert areas["garage"]["presence"]["state"] == "unknown"
    assert counts["physical_unknown"] >= 1
    assert counts["physical_clear"] == sum(
        1
        for area in areas.values()
        if area["type"] != "meta" and area["presence"]["state"] == "clear"
    )


async def test_counts_are_identical_for_admin_and_non_admin(hass, multi_area) -> None:
    """Role redaction does not change the counts."""
    hass.states.async_set(multi_area["kitchen"][0], "on")
    await hass.async_block_till_done()
    admin = (await _overview(hass, admin=True))["counts"]
    user = (await _overview(hass, admin=False))["counts"]
    assert admin == user
