---
description: Scan staged and unstaged changes for secrets before committing
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git ls-files:*)
---
Follow @SECURITY.md. Review `git status`, `git diff`, and `git diff --staged` for API keys, tokens, passwords, private keys, `.env` content, or personal data. Also confirm no tracked file matches a pattern in `.gitignore` (`git ls-files -ci --exclude-standard`). Report findings with file and line, never printing the secret value itself. If clean, say so.
