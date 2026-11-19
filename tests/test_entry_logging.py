"""Config entry logging must not depend on the legacy Area name key."""

import logging

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import ATTR_NAME

from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_SWITCH_GROUPS,
    CONF_GLOBAL_ENTRY,
    DOMAIN,
)


async def test_global_entry_switch_group_cleanup_logs_without_name(
    hass, caplog
) -> None:
    """A GlobalEntry without a name key cleans legacy switch groups without KeyError."""
    caplog.set_level(logging.INFO)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_AREAS: {},
            CONF_ENABLED_FEATURES: {CONF_FEATURE_SWITCH_GROUPS: {}},
        },
        version=2,
        minor_version=11,
    )
    assert ATTR_NAME not in entry.data
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "KeyError" not in caplog.text
    assert CONF_FEATURE_SWITCH_GROUPS not in entry.options.get(
        CONF_ENABLED_FEATURES, {}
    )


async def test_nameless_legacy_entry_migration_logs_without_key_error(
    hass, caplog
) -> None:
    """A legacy entry without a name key migrates without KeyError in logging."""
    caplog.set_level(logging.INFO)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={},
        version=2,
        minor_version=10,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "KeyError" not in caplog.text
