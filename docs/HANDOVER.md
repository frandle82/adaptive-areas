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

## Before handing over substantial work

- Update `CURRENT_STATE.md` with verified state and unresolved risks.
- Update this file with concise next steps, executed checks, and skipped checks.
- Add accepted architecture decisions to `DECISIONS.md`.
- Do not include secrets, full chat transcripts, or unnecessary personal data.
