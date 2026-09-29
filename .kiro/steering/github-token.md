---
inclusion: manual
---

# GitHub Access

This project has a GitHub Personal Access Token available for interacting with
the GitHub repository (creating repos, pushing, managing secrets, setting up
Actions, etc.).

## Where the token lives

- The token is stored in the `.env` file at the project root under the key
  `GITHUB_TOKEN`.
- `.env` is git-ignored (see `.gitignore`) — the token is **never** committed.

## How to use it

Load it from the environment at runtime. Never hardcode, echo, or print the
token value, and never write it into any committed file.

```bash
# Load the token into the shell environment (values stay out of logs)
set -a; source .env; set +a

# Authenticate the GitHub CLI non-interactively
echo "$GITHUB_TOKEN" | gh auth login --with-token

# Or pass it directly to gh / API calls via the GH_TOKEN env var
GH_TOKEN="$GITHUB_TOKEN" gh repo view

# Or call the REST API directly
curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user
```

## Rules

- Reference the token only by its env var name (`GITHUB_TOKEN`), never its value.
- Do not echo the token in command output, logs, or committed files.
- When configuring CI/CD, store credentials as GitHub repository **secrets**
  (e.g. via `gh secret set`), not in workflow YAML or source.
- Prefer `gh` CLI or the REST API with the token loaded from `.env`.
