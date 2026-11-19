---
name: gh-fix-ci
description: >-
  Automated debugging and analysis of failed GitHub Actions CI runs.
  Use when CI checks fail, to inspect logs via `gh`, isolate root causes, and prepare targeted fixes.
---

# GitHub Actions CI Debugging & Fixing (gh-fix-ci)

Instructions and automated workflows for diagnosing and resolving failed GitHub Actions CI pipeline runs in `adaptive-areas`.

## Purpose

The `gh-fix-ci` skill hooks into GitHub Actions runs using the GitHub CLI (`gh`), fetches and analyzes failure logs, isolates root causes, reproduces errors locally, and generates precise fixes.

## CI Matrix in Adaptive Areas

The repository uses the following GitHub Actions workflows:

| Workflow File | Job Name | Primary Tool / Command | Purpose |
|---|---|---|---|
| `.github/workflows/pytest.yml` | `test-stable` | `tox -e ha-stable` | Integration tests with the supported Home Assistant stable release (pinned, 2026.10.4) on Python 3.14 |
| `.github/workflows/pytest.yml` | `test-beta` | `tox -e ha-beta` | Integration tests with Home Assistant beta release |
| `.github/workflows/lint.yml` | `ruff` | `tox -e lint` | Code style, ruff, black, pylint, validate_json |
| `.github/workflows/commitlint.yml` | `commitlint` | `commitlint` | Conventional commit message compliance |
| `.github/workflows/validation.yaml` | `hassfest`, `hacs` | Hassfest & HACS action | Manifest, brand, and JSON schema validation |

## Workflow & Diagnosis Steps

### 0. Verify the repository context
`gh` may resolve a different repository than this clone (it has resolved an upstream project before). Verify it first:
```bash
gh repo view --json nameWithOwner -q .nameWithOwner   # must print frandle82/adaptive-areas
```
If it does not, run `gh repo set-default frandle82/adaptive-areas` or add `-R frandle82/adaptive-areas` to every command. Never analyse runs or commit SHAs from another repository.

### 1. Identify Failed Runs
List the most recent runs for the current branch:
```bash
gh run list --limit 5
```

Check the detailed status of the latest run or a specific run ID:
```bash
gh run view <run_id>
```

### 2. Extract Failed Logs
Retrieve failed log output directly without opening a browser:
```bash
gh run view <run_id> --log-failed
```

If specific job logs are needed:
```bash
gh run view <run_id> --job <job_id> --log
```

### 3. Categorize Root Causes

#### Category A: Pytest Failures (`test-stable` / `test-beta`)
* **Symptom:** Assertion errors, unexpected state, fixture failures, deprecation warnings treated as errors.
* **Local Reproduction:**
  ```bash
  # Reproduce with exact failed test file:
  .tox/ha-stable/bin/pytest -q tests/test_<module>.py -k "<failed_test_name>"
  # Or full stable suite:
  scripts/test stable
  ```
* **Resolution Strategy:**
  - Check whether HA core changed an API (e.g. state property, service call schema, async hook).
  - Verify mock setups in `tests/helpers.py` or `tests/mocks.py`.
  - Fix the underlying bug in `custom_components/adaptive_areas/` (or update outdated test expectations if HA APIs evolved, but never weaken behavioral assertions).

#### Category B: Linting & Code Style (`ruff` / `lint`)
* **Symptom:** Ruff errors, black formatting differences, pylint warnings, invalid JSON syntax.
* **Local Reproduction:**
  ```bash
  scripts/lint
  # Or JSON validation specifically:
  python3 scripts/validate_json.py
  ```
* **Resolution Strategy:**
  - Run ruff / black through the lint environment. `.tox/lint/bin/ruff` does not exist in this repository, so use the tox run and fix the reported findings:
    ```bash
    scripts/lint
    ```
  - Fix any syntax errors in translation files (`custom_components/adaptive_areas/translations/*.json`).

#### Category C: Hassfest / HACS Validation (`validation.yaml`)
* **Symptom:** Missing keys in `manifest.json`, missing translations for config flow steps, broken brand images, or invalid domain keys.
* **Local Reproduction:**
  ```bash
  python3 scripts/validate_json.py
  ```
* **Resolution Strategy:**
  - Verify all strings referenced in `config_flow.py` have corresponding entries in `translations/en.json`.
  - Verify requirements in `custom_components/adaptive_areas/manifest.json`.

#### Category D: Commitlint
* **Symptom:** Commit message does not match conventional commits format (e.g., `feat:`, `fix:`, `docs:`, `test:`).
* **Resolution Strategy:** Propose conventional commit format for future commits or amended commit messages.

### 4. Verify Fix Locally Before Pushing
Always verify the fix locally before committing or pushing:
```bash
# 1. Run lint
scripts/lint

# 2. Run targeted tests
.tox/ha-stable/bin/pytest -q tests/test_<module>.py

# 3. Check git diff
git diff
```

### 5. Report to Andreas
Report on German:
- The run ID and job that failed.
- The isolated root cause.
- The applied fix and local test verification results.
- Notice: Remind Andreas that pushing to remote requires his explicit approval (per `git-safety.md`).
