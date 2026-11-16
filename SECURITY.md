# Security Rules for Claude

These rules apply to every commit, push, and pull request in this repository.

## Never commit or push

- API keys, access tokens, secrets, passwords, private keys, certificates
- `.env` files and any other credential/config files holding secrets
- Session cookies, auth headers, OAuth client secrets
- Personal data (emails, phone numbers, addresses, financial details)
- Anything else sensitive that was pasted into the conversation

## How to apply

- Before every `git add`/`commit`/`push`, check the staged diff (`git diff --staged`) for sensitive values. If any are found, stop and tell the user instead of committing.
- Never hardcode secrets in source files. Read them from environment variables or an untracked config file.
- Sensitive files must be listed in `.gitignore` before they are created.
- Never use `git add -A` or `git add .` blindly; stage specific files.
- If a secret was already committed, tell the user immediately. Removing it from history does not make it safe, so the secret must be rotated.
- Never echo secrets back in commit messages, PR descriptions, or logs.
