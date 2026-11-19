# Testing

## Commands

| Purpose | Command |
| --- | --- |
| Stable Home Assistant suite | `scripts/test stable` |
| Beta Home Assistant suite | `scripts/test beta` |
| Stable and beta suites | `scripts/test both` |
| Lint and pre-commit checks | `scripts/lint` |
| Targeted stable test | `.tox/ha-stable/bin/pytest -q tests/test_<area>.py` |
| JSON validation | `python3 scripts/validate_json.py` |

Tox environments use Python 3.14. `scripts/lint` needs `tox` only. `scripts/test beta` needs `curl` and `jq` to look up the newest beta release on PyPI; stable runs do not need network access.

## Home Assistant compatibility

- The supported stable target is Home Assistant 2026.10.4. It is the default of `HA_STABLE_VERSION` in `tox.ini` (`ha-stable`) and is pinned in the `test-stable` CI job. `pytest-homeassistant-custom-component` 0.13.375 pins that version exactly and resolves through it.
- The newest Home Assistant stable release (2026.11.x) has no matching test harness release yet. Do not run or pin it until a harness release supports it.
- Override the default only for experiments, for example `HA_STABLE_VERSION=2026.8.1 tox -e ha-stable`.
- Verified: the full suite passes with Home Assistant 2026.8.1 (532 passed, 1 skipped) and 2026.10.4 with harness 0.13.375 (533 passed).

## Selection rules

- Behavior changes require affected tests and, for broad changes, `scripts/test stable`.
- Config Flow, persisted options, or migrations require config/migration regression coverage.
- Panel, frontend, or flow changes require interactive UI verification when a Home Assistant test instance is available.
- Documentation-only changes need link/path and diff review; they do not require Home Assistant integration tests.
- Report commands actually run and any checks skipped, including the reason.
