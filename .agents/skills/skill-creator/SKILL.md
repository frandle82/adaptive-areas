---
name: skill-creator
description: >-
  Standardized creation, structure, and maintenance of reusable agent skills.
  Use when turning successful multi-step workflows or domain procedures into persistent SKILL.md files.
---

# Skill Creator & Workflow Standardization (skill-creator)

Guidelines and conventions for turning successful agent sessions, custom debugging patterns, and repetitive development workflows into robust, reusable skills under `.agents/skills/`.

## Purpose

The `skill-creator` standardizes knowledge extraction. Whenever a complex problem is solved, a non-obvious architecture pattern is established, or a multi-step workflow is repeated, this skill guides packaging that capability into a persistent `SKILL.md` file.

## Skill Architecture & Anatomy

Every skill in `adaptive-areas` lives in its own subdirectory inside `.agents/skills/`:

```text
.agents/skills/<skill-name>/
├── SKILL.md              # Mandatory: Main instruction file with YAML frontmatter
├── scripts/              # Optional: Helper shell or Python scripts
└── references/           # Optional: Reference docs, schema samples, or templates
```

### Mandatory SKILL.md Format

```markdown
---
name: <lowercase-kebab-case-name>
description: >-
  <Short, high-level summary of what this skill does and WHEN the agent should activate it. Keep under 3 lines.>
---

# <Human-Readable Skill Title>

<1-2 sentences summarizing core purpose.>

## Purpose & Mindset
<Why this skill exists, core benefits, and mental model.>

## When to Trigger
<Explicit conditions, tasks, and file patterns that warrant activating this skill.>

## Related Files & Structure
<Relevant repository paths, entry points, or directory trees.>

## Step-by-Step Workflow
<Actionable, numbered instructions with exact CLI commands, code snippets, or verification checks.>

## Best Practices & Pitfalls
<Known edge cases, common errors, and strict rules to follow.>
```

## Step-by-Step Creation Workflow

### 1. Identify Reusable Pattern
* Has this procedure been performed more than once?
* Does it involve non-obvious domain knowledge (e.g. HA async lifecycle, HACS release rules, specific tox environments)?
* Does it prevent recurring mistakes or save significant debugging time?

### 2. Choose Concise Kebab-Case Name
* Use clear, imperative or descriptive names (e.g., `grill-me`, `gh-fix-ci`, `config-flow`).
* Avoid redundant prefixes like `adaptive-areas-skill-`.

### 3. Draft the YAML Frontmatter
* The `description` field is critical: the agent uses this description to decide when to invoke the skill.
* Clearly specify both what the skill does AND triggering criteria (`"Use when..."`).

### 4. Ground in Real Code & Commands
* Always include absolute or workspace-relative file paths with markdown links.
* Provide exact, copy-pasteable terminal commands (e.g. `scripts/lint`, `.tox/ha-stable/bin/pytest ...`).
* Detail specific expected outputs or failure modes.

### 5. Validate & Register
* Check syntax and formatting.
* No manual registration is needed: every directory under `.agents/skills/` is discovered automatically (Claude Code via the `.claude/skills` symlink, other agents via their own skill discovery). Keep `name` in the frontmatter equal to the directory name.
* Add any related workflows to `.agents/workflows/` if a user-facing action sequence is needed.

## Skill Quality Checklist
* [ ] Does the YAML frontmatter parse cleanly?
* [ ] Is the description specific enough to trigger automatically at the right moment?
* [ ] Are all CLI commands tested and functional in the local repository environment?
* [ ] Are HA conventions (`async`, typing, translations) preserved?
* [ ] Is the skill registered in `AGENTS.md`?
