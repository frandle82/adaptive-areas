---
name: migrations
description: >-
  Data and schema migration guidelines for Adaptive Areas config entries and backward compatibility.
  Use when modifying stored entry structures or handling legacy options.
---

# Migrations & Backward Compatibility

Instructions for handling data migrations and legacy settings in `adaptive-areas`.

## Related Files & Structure

```text
custom_components/adaptive_areas/
├── __init__.py           # Contains async_migrate_entry implementation
├── const.py              # Version constants (CONF_VERSION, minor versions) & option keys
└── config_flow.py        # Updates entries to latest schema during options flow
tests/
├── test_init.py          # Unit tests verifying entry lifecycle and async_migrate_entry
└── test_light_group_migration.py # Specific migration tests for legacy data structures
```

## Key Code References

* **Entry Migration Handler:** [`custom_components/adaptive_areas/__init__.py`](custom_components/adaptive_areas/__init__.py) (`async_migrate_entry`)
* **Version Constants:** [`custom_components/adaptive_areas/const.py`](custom_components/adaptive_areas/const.py) (`CONF_VERSION`, etc.)
* **Migration Unit Tests:** [`tests/test_init.py`](tests/test_init.py), [`tests/test_light_group_migration.py`](tests/test_light_group_migration.py)

## Best Practices & Rules

* **Preserve Legacy Options:** Never drop historical configuration keys without a tested migration path in `async_migrate_entry`.
* **Version Bumping:** Increment `minor_version` or `version` in `custom_components/adaptive_areas/const.py` / `__init__.py` when stored entry schemas or data layouts change.
* **Safe In-Place Mutation:** Construct updated data/options dictionaries without mutating original references prematurely.
* **Verification:** Always write and run unit tests in `tests/test_init.py` or dedicated migration tests verifying that legacy config entries upgrade cleanly to the new schema without data loss.
