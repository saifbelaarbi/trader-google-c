# watch-bot.ps1 — run the paper bot AND auto-redeploy it when main advances.
#
# Freqtrade loads strategy code into memory at startup and has no hot-reload,
# so "auto-update" means: watch origin/main, and when a new commit touches the
# bot (anything under ftbot/), fast-forward and restart the process. Dry-run
# trades are persisted in sqlite, so a restart resumes open positions cleanly —
# nothing is lost.
#
# Your local config secrets (telegram token, jwt) are stashed/restored around
# every pull, exactly like start-bot.ps1.
#
# Usage:  double-click watch-bot.bat, or:
#   powershell -NoProfile -ExecutionPolicy Bypass -File ftbot\watch-bot.ps1
#   powershell ... -File ftbot\watch-bot.ps1 -PollSeconds 120   # check every 2 min
#
# To stop everything: press Ctrl+C in this window (kills the bot and watcher).
#
# ⚠ REAL MONEY: once you switch off dry-run, prefer the one-shot start-bot.bat
# so a push can never silently change live trading behavior without your eyes
# on it. Auto-deploy is for the paper-trading phase.

param(
    [int]$PollSeconds = 300
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Sync-Main {
    # Fast-forward local main to origin/main, preserving local config secrets.
    $configDirty = -not [string]::IsNullOrEmpty((git status --porcelain ftbot/config.dry.json))
    if ($configDirty) {
        git stash push -m "ftbot-local-config" -- ftbot/config.dry.json | Out-Null
    }
    git merge --ff-only origin/main
    if ($configDirty) {
        git stash pop | Out-Null
    }
}

function Start-Bot {
    Write-Host "[watch-bot] launching ClaudeBreakout ($(Get-Date -Format u))" -ForegroundColor Cyan
    return Start-Process freqtrade `
        -ArgumentList 'trade','--userdir','ftbot','--config','ftbot/config.dry.json','--strategy','ClaudeBreakout' `
        -PassThru -NoNewWindow
}

git checkout main
git fetch origin main --quiet
Sync-Main

while ($true) {
    $proc = Start-Bot
    $intentionalStop = $false

    # Inner loop: poll origin/main while the bot runs.
    while (-not $proc.HasExited) {
        Start-Sleep -Seconds $PollSeconds
        if ($proc.HasExited) { break }

        try {
            git fetch origin main --quiet 2>$null
        } catch {
            continue   # transient network blip — try again next cycle
        }

        $local  = (git rev-parse main).Trim()
        $remote = (git rev-parse origin/main).Trim()
        if ($local -eq $remote) { continue }

        # main advanced. Only a change under ftbot/ (strategy or config) needs a
        # restart; commits to cloud/, agent/ or docs do not touch the bot.
        $ftChanged = -not [string]::IsNullOrEmpty((git diff --name-only main origin/main -- ftbot/))
        Sync-Main

        if ($ftChanged) {
            Write-Host "[watch-bot] ftbot/ updated on main -> restarting bot" -ForegroundColor Yellow
            $intentionalStop = $true
            Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
            $proc.WaitForExit(15000) | Out-Null
            break   # relaunch with the new code
        } else {
            Write-Host "[watch-bot] main advanced but ftbot/ unchanged -> bot keeps running" -ForegroundColor DarkGray
        }
    }

    if (-not $intentionalStop) {
        # Bot exited on its own (crash, or you Ctrl+C'd just the bot). Pause to
        # avoid a tight crash loop, re-sync, then relaunch.
        Write-Host "[watch-bot] bot exited (code $($proc.ExitCode)); restarting in 30s" -ForegroundColor Red
        Start-Sleep -Seconds 30
        try { git fetch origin main --quiet; Sync-Main } catch {}
    }
}
