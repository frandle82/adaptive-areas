
# Adaptive Areas – Claude Code

## Shared project instructions

@AGENTS.md
@.agents/rules/project.md
@.agents/rules/git-safety.md
@.agents/rules/quality.md
@.agents/knowledge/README.md

## Shared agent architecture

Adaptive Areas is developed using Claude Code, OpenAI
Codex and Google Antigravity.

The `.agents/` directory is the single source of truth
for shared agent instructions, skills, workflows and
project knowledge.

- Skills: `.agents/skills/`
- Rules: `.agents/rules/`
- Workflows: `.agents/workflows/`
- Knowledge: `.agents/knowledge/`

Claude-specific integrations must not duplicate the
canonical skill definitions.

## Project identity

Adaptive Areas is a Home Assistant custom integration
distributed through HACS.

- Stable domain: `adaptive_areas`
- Implementation: `custom_components/adaptive_areas/`
- Tests: `tests/`

Implementation and tests are the primary sources of
truth. Verify documentation against actual code.

## Mandatory development process

Before modifying any code:

1. Run `git status --short --branch`.
2. Identify and preserve existing changes.
3. Analyze the affected behavior and root cause.
4. Select and apply the relevant project skills.
5. Consult project knowledge and relevant ADRs.
6. Clarify ambiguous requirements using `grill-me`.
7. Define the implementation and verification plan.

After modifying code:

1. Run relevant checks using the `testing` skill.
2. Review changes using the `code-reviewer` skill.
3. Verify backward compatibility.
4. Update project knowledge when appropriate.
5. Report changes, test results and remaining risks.

## Skill selection

Use project skills proactively whenever their
descriptions match the current task.

Read the complete SKILL.md before applying a skill.
Use multiple skills when a task spans several domains.

### Core integration

- home-assistant
- adaptive-features
- config-flow
- migrations
- translations

### Analysis and quality

- grill-me
- knowledge
- testing
- code-reviewer
- gh-fix-ci
- skill-creator

### Dashboard development

For new dashboard phases or major redesigns, use:

1. codebase-analysis
2. adaptive-areas-dashboard-context
3. information-architect
4. dashboard-ui-structure
5. homeassistant-dashboard-designer
6. frontend-design
7. ui-ux-pro-max

Apply playwright-interactive when browser-based
verification is required and available.

For narrow dashboard bugfixes, use only the relevant
subset while preserving existing architecture.

## Project knowledge

Consult `.agents/knowledge/README.md` and relevant
documents in:

- architecture/
- specs/
- adrs/
- notes/

Do not introduce a separate conflicting knowledge base.

## Workflows

Apply the relevant workflow from `.agents/workflows/`:

- add-platform-feature.md
- review-change.md
- prepare-release.md
- fix-ci.md
- test-change.md

## Git safety

Do not create commits, pushes, branches, tags,
releases or pull requests without explicit user approval.

Never overwrite unrelated user or agent changes.
Never execute destructive Git operations.

## Collaboration

Do not assume access to Codex or Antigravity
conversation history.

Use repository files, Git history and existing
project knowledge to establish the current state.

Maintain shared skills in `.agents/skills/` only.

If a skill requires unavailable tools, explain the
limitation and propose an equivalent verification
method. Never claim that an unexecuted test passed.

Communicate with the user in German.

# Claude Code additions

- Do not use `--dangerously-skip-permissions`.
- Keep Claude Code's permission prompts enabled. Do not add broad command allowlists.
- Repository documentation and code remain in English unless the target file uses another language. Communicate with Andreas in German.
