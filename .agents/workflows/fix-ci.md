# Workflow: Fix CI

Diagnose and resolve failed GitHub Actions CI runs using the `gh-fix-ci` skill.

## Steps

1. Inspect recent runs:
   ```bash
   gh run list --limit 5
   ```
2. Fetch failure logs:
   ```bash
   gh run view <run_id> --log-failed
   ```
3. Classify the failure:
   - **`test-stable` / `test-beta`:** Pytest test failures or HA API regressions.
   - **`ruff` / `lint`:** Ruff, black, or pylint code style violations.
   - **`validation.yaml`:** Manifest, brands, or JSON translation issues.
   - **`commitlint`:** Non-standard commit message.
4. Reproduce locally:
   - For tests: `.tox/ha-stable/bin/pytest -q tests/test_<module>.py -k "<failed_test>"`
   - For lint: `scripts/lint`
   - For JSON: `python3 scripts/validate_json.py`
5. Implement the minimal fix.
6. Re-verify locally:
   ```bash
   scripts/lint
   .tox/ha-stable/bin/pytest -q tests/test_<module>.py
   ```
7. Review changes with the **`code-reviewer`** checklist.
8. Report diagnosis and fix to Andreas (request approval before pushing).
