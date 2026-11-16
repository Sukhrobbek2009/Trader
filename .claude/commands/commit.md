---
description: Safely commit current changes with a clear message
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git log:*)
---
1. Run the checks from /secrets-check. Stop and report if anything sensitive is found.
2. Look at `git status`, `git diff`, and recent `git log` to match message style.
3. Stage specific files by name (never `git add -A` or `git add .`).
4. Commit with a concise message explaining why. Do not push.

Extra instructions: $ARGUMENTS
