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

`scripts/test` and `scripts/lint` resolve current Home Assistant versions from PyPI and require `curl`, `jq`, `tox`, and network access. Tox environments use Python 3.14.

## Home Assistant compatibility

- The `test-stable` CI job is temporarily pinned to Home Assistant 2026.10.4. `pytest-homeassistant-custom-component` 0.13.375 pins that version exactly and is resolved through it.
- The newest Home Assistant stable release (2026.11.x) has no matching test harness release yet. Do not run or pin it until a harness release supports it.
- Scripts `scripts/test` and `scripts/lint` still resolve the latest stable release from PyPI, so they will fail until the harness supports it. Use `HA_STABLE_VERSION=2026.10.4 tox -e ha-stable` as the compatibility check.
- Verified: the full suite passes with Home Assistant 2026.8.1 (532 passed, 1 skipped) and 2026.10.4 with harness 0.13.375 (533 passed).

## Selection rules

- Behavior changes require affected tests and, for broad changes, `scripts/test stable`.
- Config Flow, persisted options, or migrations require config/migration regression coverage.
- Panel, frontend, or flow changes require interactive UI verification when a Home Assistant test instance is available.
- Documentation-only changes need link/path and diff review; they do not require Home Assistant integration tests.
- Report commands actually run and any checks skipped, including the reason.
