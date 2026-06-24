# publish-to-macdo

Publish a local AI-built project to **[mac.do](https://app.mac.do)** straight from your coding agent.

Tell your agent **“publish to mac.do”** and it inspects your project, collects metadata,
authorizes against your mac.do account, and submits your tool for review.

## Install (Claude Code)

```
/plugin marketplace add macdo-app/publish-to-macdo
/plugin install publish-to-macdo@macdo
```

Then, in your project, tell Claude Code: **publish to mac.do**.

## Codex / Cursor

These agents have no plugin marketplace, so install the skill into their skills directory:

```
scripts/install-codex.sh         # copies the skill into ~/.codex/skills/publish-to-macdo
scripts/install-codex.sh <dir>   # or into a custom skills dir
```

Then open your agent in the project and say **publish to mac.do**.

## What it does

- Inspects project type, framework, package manager, and build command.
- Generates a mac.do manifest and submits it through the publishing API.
- Uses browser/device authorization to your mac.do account — no API key to manage.
- Defaults to `https://app-api.mac.do`; set `MACDO_API_BASE` to target a local instance.

## Links

- Platform: <https://app.mac.do>
