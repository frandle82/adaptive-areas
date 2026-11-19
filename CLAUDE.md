# Adaptive Areas – Claude Code

Shared project instructions for all agents:

@AGENTS.md

Project context is versioned in `docs/`: `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `CURRENT_STATE.md`, `DECISIONS.md` (with `adrs/`), `TESTING.md` and `HANDOVER.md`.

Local, unversioned tooling may exist under `.agents/`. The repository does not depend on it.

## Claude Code specifics

- Do not use `--dangerously-skip-permissions`.
- Keep Claude Code's permission prompts enabled. Do not add broad command allowlists.
- Communicate with Andreas in German. Code and repository documentation stay in English unless the target file uses another language.
