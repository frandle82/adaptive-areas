# Decisions

This is an index of verified architectural decisions. It does not replace detailed, accepted ADRs.

| Decision | Status | Source |
| --- | --- | --- |
| Home Assistant Custom Integration with Config Entry-based setup | Implemented | `custom_components/adaptive_areas/__init__.py`, `config_flow.py` |
| Python runtime is source of truth; dashboard uses DTOs and WebSocket transport | Implemented | `dashboard.py`, `websocket.py`, `frontend/adaptive-areas-panel.js` |
| Environment entities expose qualitative public data while detailed recommendations remain internal | Accepted | ADR: [adrs/001-public-environment-presentation.md](adrs/001-public-environment-presentation.md) |
| Shared agent baseline is `AGENTS.md`; Claude imports it via `CLAUDE.md` | Accepted | `AGENTS.md`, `CLAUDE.md` |

Record a new decision here only after it is accepted. Include context, decision, consequences, migration implications, and test impact; link a detailed ADR when one exists.
