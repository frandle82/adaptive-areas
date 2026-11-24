"""D04 to D06: defaults of new regular Areas, one source for every configuration path.

The schema defaults are the single backend source: the default domains, the default
device classes and the default release time (minutes). Stored values are not replaced.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.adaptive_areas.const import (
    DEFAULT_CLEAR_TIMEOUT,
    DEFAULT_PRESENCE_DEVICE_PLATFORMS,
    DEFAULT_PRESENCE_DEVICE_SENSOR_CLASS,
    REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA,
)


def test_d04_default_domains_are_binary_sensor_and_media_player() -> None:
    """D04: the default presence domains are binary_sensor and media_player."""
    assert sorted(DEFAULT_PRESENCE_DEVICE_PLATFORMS) == [
        "binary_sensor",
        "media_player",
    ]
    defaults = REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA({})
    assert sorted(defaults["presence_device_platforms"]) == [
        "binary_sensor",
        "media_player",
    ]


def test_d05_default_device_classes_are_motion_and_occupancy() -> None:
    """D05: the default device classes are motion and occupancy."""
    assert list(DEFAULT_PRESENCE_DEVICE_SENSOR_CLASS) == [
        BinarySensorDeviceClass.MOTION,
        BinarySensorDeviceClass.OCCUPANCY,
    ]
    defaults = REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA({})
    assert defaults["presence_sensor_device_class"] == [
        BinarySensorDeviceClass.MOTION,
        BinarySensorDeviceClass.OCCUPANCY,
    ]


def test_d06_default_release_time_is_one_minute() -> None:
    """The stored value is in minutes; the default is one minute (60 seconds)."""
    assert DEFAULT_CLEAR_TIMEOUT == 1
    defaults = REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA({})
    assert defaults["clear_timeout"] == 1


def test_stored_user_values_are_kept_including_an_empty_domain_choice() -> None:
    """An explicitly stored empty choice is not replaced by the defaults."""
    stored = REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA(
        {
            "presence_device_platforms": [],
            "presence_sensor_device_class": [],
            "clear_timeout": 5,
        }
    )
    assert stored["presence_device_platforms"] == []
    assert stored["presence_sensor_device_class"] == []
    assert stored["clear_timeout"] == 5
