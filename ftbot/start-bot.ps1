# start-bot.ps1 — one-shot quick launch for the paper-trading bot.
# Pulls the latest main (preserving your local config edits: telegram
# token, jwt secrets) and starts ClaudeBreakout in dry-run mode.
#
# Usage:  double-click start-bot.bat, or run from PowerShell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File ftbot\start-bot.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

git checkout main
git fetch origin main

# Stash local config edits (secrets) only if the file is dirty, so the
# pull can't clobber or conflict with them.
$configDirty = -not [string]::IsNullOrEmpty((git status --porcelain ftbot/config.dry.json))
if ($configDirty) {
    git stash push -m "ftbot-local-config" -- ftbot/config.dry.json | Out-Null
}

git merge --ff-only origin/main

if ($configDirty) {
    # If this pop ever conflicts (upstream changed the same config lines),
    # resolve by keeping your token/secrets plus the new upstream keys.
    git stash pop | Out-Null
}

freqtrade trade --userdir ftbot --config ftbot/config.dry.json --strategy ClaudeBreakout
