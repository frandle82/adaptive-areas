# Workflow: Test Change

Execute testing, code quality checks, and optional UI verification.

## Steps

1. Identify affected components and determine corresponding test files in `tests/`.
2. Run target pytest command:
   ```bash
   .tox/ha-stable/bin/pytest -q tests/test_<bereich>.py
   # Or with global/virtual environment pytest:
   pytest -q tests/test_<bereich>.py
   ```
3. For UI, Config Flow, or Options Flow changes, conduct interactive browser validation:
   - Use the **`playwright-interactive`** skill to step through screens, check field rendering, and capture recordings/screenshots.
4. For functional changes, run linting & formatting checks:
   ```bash
   scripts/lint
   ```
5. For broader modifications, run the stable integration test suite:
   ```bash
   scripts/test stable
   ```
6. Report exact test results and explicitly note any unexecuted checks in German.
