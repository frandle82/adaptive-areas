# Project context

## Purpose

Adaptive Areas is an MIT-licensed Home Assistant custom integration distributed through HACS. It makes Home Assistant Areas presence-aware and provides area-oriented automation for lights, climate, fans, media, sensor aggregates, and related diagnostics.

## Verified technology stack

- Python 3.14; Home Assistant `>=2026.8.0`.
- Home Assistant Config Entries, entities, services, diagnostics, repairs, system health, and WebSocket APIs.
- HACS integration metadata in `hacs.json` and the integration manifest.
- Pytest with `pytest-homeassistant-custom-component`, tox, coverage, Ruff, Black, and pre-commit.
- GitHub Actions for tests, linting, Hassfest/HACS validation, conventional commits, and releases.

## Repository map

| Path | Responsibility |
| --- | --- |
| `custom_components/adaptive_areas/` | Integration runtime, config flow, entities, helpers, panel and WebSocket API |
| `custom_components/adaptive_areas/frontend/` | Home Assistant custom-panel JavaScript |
| `tests/` | Unit and integration tests with HA fixtures |
| `docs/source/` | Published MkDocs user documentation |
| `docs/` | Maintainer and agent context documents; not part of the MkDocs navigation |
| `.github/workflows/` | CI, validation, release and commit-message automation |
| `scripts/` | Development, linting, testing and release helpers |

See [ARCHITECTURE.md](ARCHITECTURE.md), [TESTING.md](TESTING.md), and [CURRENT_STATE.md](CURRENT_STATE.md) for operational details.
