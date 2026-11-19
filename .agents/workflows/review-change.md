# Workflow: Review Change

Perform a thorough quality and security review of recent changes before proposing a commit or final response.

## Steps

1. Check current git status:
   ```bash
   git status --short --branch
   ```
2. Analyze the full diff:
   ```bash
   git diff
   ```
3. Apply the **`code-reviewer`** skill checklist:
   - Home Assistant core standards (`_attr_has_entity_name`, `translation_key`, `EntityDescription`)
   - Async & resource safety (listeners/timers detached, no blocking I/O)
   - State resilience (`None`, `STATE_UNKNOWN`, `STATE_UNAVAILABLE`)
   - Backward compatibility (unique IDs, schema migrations)
   - Performance and scalability
4. Run static analysis:
   ```bash
   scripts/lint
   ```
5. Run target test suites for modified components:
   ```bash
   .tox/ha-stable/bin/pytest -q tests/test_<affected_module>.py
   ```
6. Summarize findings, test results, and status in German for Andreas.
