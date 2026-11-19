# Adaptive Areas agent instructions

This is the shared baseline for Codex, Claude Code, Gemini, and human contributors.

## Safety and collaboration

- Before changing files, run `git status --short --branch` and inspect relevant diffs.
- Preserve work created by other people or agents. Never reset, clean, rebase, force-push, overwrite, or delete it without explicit approval.
- Restrict a change to its assigned task. Do not add unrelated refactors, dependencies, options, or application features.
- Do not commit, push, tag, release, open a pull request, create a branch, or modify `AGENTS.override.md` without explicit approval.
- Never put credentials, tokens, headers, personal data, or Home Assistant configuration in tracked files, logs, diagnostics, or documentation.
- Concurrent work uses separate Git branches and worktrees. One agent owns a file at a time; coordinate before editing a shared file.

## Project rules

- `custom_components/adaptive_areas/` and `tests/` are the source of truth. The stable integration domain is `adaptive_areas`.
- Follow Home Assistant conventions: asynchronous I/O, cleanup of listeners and timers, translations for user-facing text, and safe handling of `unknown` and `unavailable` states.
- Preserve config entries, entity/unique IDs, and stored schemas. A storage change needs an explicit migration and regression tests.
- Keep Magic Areas attribution and the MIT licence intact.
- Use English for code and repository documentation unless the existing target uses another language; communicate with Andreas in German.
- Keep each change to one topic per commit. Do not mix unrelated refactors with functional changes.
- Informational modules (for example the Cleaning Tracker) must never control devices.
- The Decision Trace is privacy-preserving: it must not contain personal or sensitive data.
- Use Home Assistant standards: Config Flow and Options Flow for settings, `entity_id` instead of `device_id`, and native mechanisms (Repairs, Diagnostics, System Health).

## Domain rules

Check which of these functional areas a change touches. Behaviour is documented in `docs/source/concepts/` and `docs/source/features/`.

- **Presence:** Per-area presence from several sources (motion, media players, device trackers, BLE beacons). Smart timeouts reset on new motion without abrupt switch-offs. Presence Hold forces presence manually. Wasp in a Box keeps lights on while someone is in the room, using door or garage sensors. BLE text sensors (ESPresense, Bermuda, Room Assistant) are converted into presence sensors.
- **Secondary states:** `dark`/`bright`, `sleep`, `extended`, `accented`.
- **Meta areas:** Areas are `interior` or `exterior` and belong to floors. Virtual meta areas (interior, exterior, global, floors) aggregate presence and states; logic and secondary states are inherited or calculated.
- **Smart control:** Light groups by purpose (overhead, task, accent, sleep); climate presets mapped from area states; automatically created fan groups driven by aggregates (temperature, humidity, CO₂); area-aware media player; sensor aggregates by `device_class` and unit; health sensors for gas, smoke, moisture, problem and safety.
- **Optional modules:** Area Climate is disabled by default. Missing dimensions stay `unknown` and are not estimated; outdoor areas provide only reduced reference values. The Cleaning Tracker reports only.
- **Diagnostics:** Native diagnostics, Repairs, System Health and the Decision Trace.
- **Unknown stays unknown:** Missing sensor data is never guessed or replaced with defaults.

## Commits, tests and documentation

- Commits follow Conventional Commits (`type(scope): description`) and are validated by `scripts/validate_commit.py` in CI. Write commit messages in English. Stage the files first and commit with `scripts/commit "type(scope): description"`. Do not use raw `git commit` for this repository. Details: `CONTRIBUTING.md`.
- A pre-release or release requires a changelog entry in `CHANGELOG.md`.
- New or changed domain logic (presence, states, meta areas, control) needs tests, especially for edge cases: timeouts, several sensor sources, doors and Wasp in a Box, missing data.
- Run `pre-commit` (see `.pre-commit-config.yaml`) and the tox environments before a commit. Tests live in `tests/`.
- Document new or changed features in `docs/source/` (concepts, features, how-to). Keep `CHANGELOG.md` and the README feature list consistent.
- Translations: new user-facing text is a translation key in `custom_components/adaptive_areas/translations/en.json`. Keep the other language files in sync where practical.

## Workflow

1. Read the affected code, tests, and the project documents in `docs/` before implementation. If present, use the local `.agents/` rules and knowledge as supplementary context; they never override this file.
2. For new features, architectural changes, or ambiguous work, clarify scope, non-goals, edge cases, migration impact, and verification before editing.
3. Reuse established project patterns and make the smallest complete change. Add or update tests for behavior changes.
4. Run the relevant checks from `docs/TESTING.md`; report executed and skipped checks truthfully.
5. Review the final diff for accidental changes, security/privacy exposure, backward compatibility, and documentation accuracy.
6. After substantial changes, update `docs/CURRENT_STATE.md` and `docs/HANDOVER.md`. Record accepted architectural decisions in `docs/DECISIONS.md`.

## Shared documentation

- `docs/PROJECT_CONTEXT.md` — scope, stack, and repository map.
- `docs/ARCHITECTURE.md` — verified data flow and boundaries.
- `docs/CURRENT_STATE.md` — verified current implementation state and known gaps.
- `docs/ROADMAP.md` — only approved/planned work; do not invent roadmap items.
- `docs/DECISIONS.md` — decision index and source links.
- `docs/HANDOVER.md` — concise next-agent handover.
- `docs/TESTING.md` — commands and test-selection guidance.
