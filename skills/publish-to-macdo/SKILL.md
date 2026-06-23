---
name: publish-to-macdo
description: Publish a local AI-built project to mac.do by inspecting the project type, collecting or inferring metadata, choosing the right public entrypoint URL, obtaining or using a mac.do publishing credential, and submitting it to the mac.do API. Use when the user asks to publish, showcase, share, submit, list, ship, or register a local AI-built tool, app, CLI, API, library, plugin, workflow, bot, agent, extension, mobile app, desktop app, dataset, or document on mac.do. Chinese trigger phrasings include 发布到 mac.do, 展示到 mac.do, and 分享到 mac.do.
---

# Publish To mac.do

Use this skill to submit an existing local AI-built project to mac.do.

## User Experience

The user should not be told to run the Python script manually. The expected
interaction is:

1. The user opens their AI coding agent (Claude Code, Codex, Cursor, …) in the
   local project workspace.
2. The user says something like "publish this to mac.do".
3. The agent uses this skill, inspects the project, asks only for missing values,
   and runs the bundled script internally.

The project directory is the current workspace root when it contains the thing
being published. If the workspace is a monorepo, identify the app/package
directory that contains the relevant project manifest such as `package.json`,
`pyproject.toml`, `pom.xml`, `Cargo.toml`, `go.mod`, `pubspec.yaml`,
`manifest.json`, framework config, or `index.html`; ask only if multiple
plausible publishable projects exist.

## Requirements

- A reachable public `primary_url` for the project. Depending on type, this can
  be a live demo, landing page, documentation page, package page, store listing,
  source repository, API docs, or other public entrypoint. It must be an
  absolute `http` or `https` URL and cannot point to localhost, a private IP, or
  include URL credentials. `demo_url` is a backwards-compatible alias for web
  projects.
- A mac.do publishing credential. Prefer browser/device authorization to the
  creator's mac.do account. `MACDO_API_KEY` remains an internal/admin fallback
  for local development and smoke tests.
- A mac.do API base URL in `MACDO_API_BASE`; defaults to `https://app-api.mac.do`.
  Set it to a local URL such as `http://localhost:8080` only when developing
  against your own instance.

Do not print credentials. Do not commit credentials into project files.

## Workflow

1. Inspect the local project.
2. Generate the manifest submission payload from project metadata, package
   metadata, supplied URLs, and the minimum missing user answers.
3. The script keeps per-project state (the tool id for precise updates and the
   prior manifest) in `~/.macdo/projects.json`, keyed by the project path — it no
   longer writes anything into the project directory. Re-publishing the same
   project updates the existing tool. Never require the creator to prepare metadata by hand.
4. If required fields are missing, ask only for the missing values.
5. Obtain a scoped mac.do publishing credential through browser/device
   authorization when no cached token, `MACDO_PUBLISHING_TOKEN`, or
   `MACDO_API_KEY` exists.
6. Run `scripts/macdo_publish.py` from this skill directory internally; do not
   present this command as the user's primary interface.
7. Submit the generated payload with bearer authentication and an
   `Idempotency-Key`.
8. Report the submission id, status URL, review URL, and eventual public URL.
9. If the user asks for progress later, run the script with `--status-id`.

## Collected Information

Collect automatically from the project directory when possible:

- Project name and description from project manifests such as `package.json`,
  `pyproject.toml`, `pom.xml`, `Cargo.toml`, `go.mod`, `pubspec.yaml`, and
  browser extension `manifest.json`.
- Project type, including `web`, `mobile`, `desktop`, `browser_extension`,
  `cli`, `api`, `library`, `plugin`, `workflow`, `bot`, `agent`, `dataset`,
  `document`, or `other`.
- Framework/runtime from manifests, dependencies, and config files. Examples:
  Next.js, Astro, Vite, React, static HTML, FastAPI, Flask, Django, Spring Boot,
  Electron, Tauri, Flutter, React Native, browser extension, Python package,
  Java package, Rust crate, Go module, Node CLI, or AI agent frameworks.
- Package manager or build ecosystem from lockfiles and manifests: pnpm, yarn,
  bun, npm, pip, Poetry, Maven, Gradle, Cargo, Go, Flutter, Xcode, or Android
  Gradle.
- Build command when the project exposes one.
- Output directory when it is meaningful for that project type.
- The prior generated manifest from `~/.macdo/projects.json` (carried forward
  across re-publishes) only as optional input; never require the user to prepare it.
  A legacy project-local `macdo.json` is read once for migration, then left untouched.

Ask the user only for missing information that cannot be inferred:

- `primary_url` is required because mac.do indexes an already reachable public
  surface. For Web this is usually a demo URL; for non-Web it can be docs,
  package, store, source, or landing URL.
- `summary` or `description` only when package metadata cannot supply them.
- `name` only when the detected name is missing or clearly unsuitable.
- `source_url` only if the user wants to publish a source link.

Do not ask for creator identity when using a publishing token. The backend owns
the submission with the creator account that approved the device authorization.

## Agent Execution

Run the bundled script internally with the selected project directory. Example
shape:

```sh
python3 <skill_dir>/scripts/macdo_publish.py \
  --project <project_dir> \
  --api-base "${MACDO_API_BASE:-https://app-api.mac.do}" \
  --primary-url "https://example.com"
```

Check a previous submission internally:

```sh
python3 <skill_dir>/scripts/macdo_publish.py \
  --api-base "${MACDO_API_BASE:-https://app-api.mac.do}" \
  --status-id "<submission_id>"
```

Optional flags:

- `--name`
- `--summary`
- `--description`
- `--source-url`
- `--type`
- `--framework`
- `--package-manager`
- `--build-command`
- `--output-dir`
- `--creator-name`
- `--creator-url`
- `--status-id`
- `--idempotency-key`
- `--token-file`
- `--no-device-auth`
- `--primary-url`
- `--dry-run`

The script does not write into the project directory. It keeps per-project state
(the tool id and the prior manifest) in `~/.macdo/projects.json`, keyed by the
absolute project path; `--dry-run` builds and stores the manifest without
submitting. On a re-publish it sends the stored tool id as `X-Macdo-Tool-Id` so
the backend updates that exact tool — surviving URL or name changes — and records
the tool id the submission returns. It also generates a stable `Idempotency-Key`
from the manifest by default, so retrying an identical submission returns the same
submission instead of creating duplicates. Pass `--idempotency-key` only when
deliberately reusing a known retry key or forcing a separate submission. If the API
rejects the submission, report the returned request ID so server logs can be
searched quickly.

Credential lookup order:

1. `--api-key` or `MACDO_API_KEY` for admin/internal fallback.
2. `MACDO_PUBLISHING_TOKEN`.
3. Cached publishing token at `~/.macdo/publishing-token.json`, or
   `MACDO_TOKEN_FILE` / `--token-file`.
4. Browser/device authorization through mac.do. The script opens the returned
   verification URL when possible, prints the user code, polls the token
   endpoint, and stores the returned `mdo_pub_...` token outside the project.

Set `MACDO_NO_BROWSER=1` to print the authorization URL without trying to open a
browser. Use `--no-device-auth` in CI when an existing credential must be
provided.

## Safety Checks

Before submission, the script validates that:

- Only known top-level manifest fields are present.
- Required fields are present: schema, name, summary, description, type, and
  either `primary_url` or legacy `demo_url`.
- Type is one of the supported mac.do project types.
- Category, tag, permission, and created-with arrays stay within limits.
- Enumerated values such as pricing and China reachability are recognized.
- `primary_url`, legacy `demo_url`, `source_url`, and `creator.url` are absolute
  public `http(s)` URLs.
- URLs do not point to localhost, private IPs, bare local hostnames, or include
  username/password credentials.
- Submissions use an idempotency key to avoid duplicate publishes on retry.

## Scope

This skill does not need to be narrow: use model judgment to understand many
project types and choose the appropriate publishing path. The current API still
requires a public entrypoint URL. If there is no reachable URL yet, help the
user produce one appropriate to the project type, then submit the listing.
