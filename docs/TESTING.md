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

## Selection rules

- Behavior changes require affected tests and, for broad changes, `scripts/test stable`.
- Config Flow, persisted options, or migrations require config/migration regression coverage.
- Panel, frontend, or flow changes require interactive UI verification when a Home Assistant test instance is available.
- Documentation-only changes need link/path and diff review; they do not require Home Assistant integration tests.
- Report commands actually run and any checks skipped, including the reason.
