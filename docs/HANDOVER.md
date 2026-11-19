# Handover

## Start here

1. Read `AGENTS.md`, then the relevant documents in `docs/`.
2. Run `git status --short --branch` before every change.
3. Inspect the affected implementation and test before editing.
4. Use a separate branch and worktree when another agent is active.

## Current handover

- The repository contains a shared Codex/Claude/Gemini workflow baseline.
- No application behavior is changed by this documentation setup.
- Dashboard behavior should be treated as configuration-capable for administrators until the README discrepancy in `CURRENT_STATE.md` is resolved by a separately approved task.
- Dashboard 2.0 Phase E: panel regressions fixed (Settings renderer, Area editor, light-group helpers), save rules verified with backend round-trip tests. Next: real Home Assistant visual review of all tabs, and decisions listed in [ROADMAP.md](ROADMAP.md) (open decisions).
- Checks run for this change: dashboard and area CRUD tests, global options tests, full suites on Home Assistant 2026.10.4 and 2026.8.1, pre-commit, `git diff --check`, local browser harness (40 checks).
- Not run: visual review in a real Home Assistant instance; Beta harness; Home Assistant 2026.11.x.

## Before handing over substantial work

- Update `CURRENT_STATE.md` with verified state and unresolved risks.
- Update this file with concise next steps, executed checks, and skipped checks.
- Add accepted architecture decisions to `DECISIONS.md`.
- Do not include secrets, full chat transcripts, or unnecessary personal data.
