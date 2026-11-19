---
name: adaptive-features
description: >-
  Domain logic, algorithms, and adaptive feature calculations for Adaptive Areas.
  Use when implementing or modifying lighting profiles, presence algorithms (wasp-in-a-box, BLE), sensor aggregates, climate/fan automation, or room usage tracking.
---

# Adaptive Features & Domain Logic Guidelines

Detailed guide to the computational models, state machines, and domain logic in `adaptive-areas`.

## Core Domains & Components

### 1. Adaptive Lighting Engine
* **Files:** [`custom_components/adaptive_areas/light.py`](custom_components/adaptive_areas/light.py), [`custom_components/adaptive_areas/helpers/light_groups.py`](custom_components/adaptive_areas/helpers/light_groups.py), [`custom_components/adaptive_areas/base/adaptive.py`](custom_components/adaptive_areas/base/adaptive.py)
* **Mechanics:**
  * Calculates dynamic brightness and correlated color temperature (CCT in Kelvin/Mireds) based on solar elevation, time of day, and ambient illuminance.
  * Supports lighting profiles (`sleep`, `relax`, `focus`, `energetic`, `night`, `day`).
  * Manages manual overrides, transition times, and sleep/night mode state transitions.
* **Testing:** `tests/test_light.py`, `tests/test_light_group_migration.py`

### 2. Presence & Occupancy Detection
* **Files:** [`custom_components/adaptive_areas/binary_sensor/presence.py`](custom_components/adaptive_areas/binary_sensor/presence.py), [`custom_components/adaptive_areas/binary_sensor/wasp_in_a_box.py`](custom_components/adaptive_areas/binary_sensor/wasp_in_a_box.py), [`custom_components/adaptive_areas/binary_sensor/ble_tracker.py`](custom_components/adaptive_areas/binary_sensor/ble_tracker.py), [`custom_components/adaptive_areas/switch/presence_hold.py`](custom_components/adaptive_areas/switch/presence_hold.py)
* **Mechanics:**
  * **Multi-sensor fusion:** Combines PIR motion detectors, mmWave radar sensors, media playback status, and BLE beacon trackers.
  * **Wasp-in-a-box algorithm:** Uses door/contact sensors ("box") with motion sensors ("wasp") to latch presence when the door is closed after motion was detected until the door opens again.
  * **Presence Hold:** Manual toggle switch preventing off-delays during special scenarios.
* **Testing:** `tests/test_wasp_in_a_box.py`, `tests/test_ble_tracker_monitor.py`

### 3. Environment & Sensor Aggregation
* **Files:** [`custom_components/adaptive_areas/helpers/environment.py`](custom_components/adaptive_areas/helpers/environment.py), [`custom_components/adaptive_areas/sensor/__init__.py`](custom_components/adaptive_areas/sensor/__init__.py)
* **Mechanics:**
  * Aggregates physical sensor readings across area entities (temperature, humidity, illuminance, air quality/WAQI, CO2, pressure).
  * Computes statistical aggregations: Average, Min, Max, Median, Sum.
  * Supports hierarchical **Meta-Areas** combining child areas into zone aggregates.
  * Computes derived indices: Dew point temperature, mold risk indicator, comfort levels.
* **Testing:** `tests/test_environment.py`, `tests/test_aggregates.py`, `tests/test_meta_aggregates.py`

### 4. Climate & Fan Automation
* **Files:** [`custom_components/adaptive_areas/switch/climate_control.py`](custom_components/adaptive_areas/switch/climate_control.py), [`custom_components/adaptive_areas/switch/fan_control.py`](custom_components/adaptive_areas/switch/fan_control.py), [`custom_components/adaptive_areas/fan.py`](custom_components/adaptive_areas/fan.py)
* **Mechanics:**
  * Auto-adjusts thermostat target temperatures and HVAC modes based on area occupancy, target comfort ranges, and window open/close states.
  * Humidity-triggered and presence-triggered ventilation fan speed modulation with hysteresis control.
* **Testing:** `tests/test_climate_control.py`, `tests/test_fan.py`

### 5. Room Usage & Cleaning Tracker
* **Files:** [`custom_components/adaptive_areas/helpers/room_usage.py`](custom_components/adaptive_areas/helpers/room_usage.py)
* **Mechanics:**
  * Tracks cumulative presence duration and calculates room utilization metrics.
  * Triggers cleaning / maintenance recommendations when utilization exceeds configured thresholds.
* **Testing:** `tests/test_cleaning_tracker.py`

## Implementation Guidelines

1. **State Isolation:** Ensure sensor aggregation methods handle invalid or NaN floats gracefully.
2. **Decision Tracing:** Use `DecisionTrace` ([`custom_components/adaptive_areas/helpers/decision_trace.py`](custom_components/adaptive_areas/helpers/decision_trace.py)) when calculating state changes to keep decisions inspectable in diagnostics.
3. **Threshold Precision:** Utilize shared constants and threshold helpers defined in [`const.py`](custom_components/adaptive_areas/const.py) and [`threshold.py`](custom_components/adaptive_areas/threshold.py).
