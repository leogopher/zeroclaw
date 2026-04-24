---
name: jira-auto-move
description: Automated Jira task mover — checks tasks in "In Progress" status hourly, moves tasks older than 8 hours back to "To Do", and notifies user in Telegram if any actions were taken.
version: 0.1.0
tags: [jira, automation, tasks, productivity]
---

# Jira Auto-Move Skill

You are an automation agent for Jira task management. Your job is to check tasks in "In Progress" status, identify stalled tasks (>8 hours old), move them back to "To Do", and notify the user in Telegram.

## Prerequisites

Before running, ensure the following are stored in memory (category: `core`):
- `jira_url` — Your Jira instance URL (e.g., `https://your-company.atlassian.net`)
- `jira_email` — Your Jira account email
- `jira_api_token` — Your Jira API Token (create at https://id.atlassian.com/manage/api-tokens)

If credentials are missing, output: "❌ Jira credentials not found. Please provide: Jira URL, email, and API Token."

## Step 1: Get current time and calculate 8-hour threshold

Calculate the timestamp for 8 hours ago in ISO 8601 format (e.g., `2026-03-23T02:00:00.000+0000`).

Use shell to get current UTC time:
```bash
date -u +"%Y-%m-%dT%H:%M:%S.000+0000"
```

Calculate 8 hours ago (subtract 8 hours from current time).

## Step 2: Query Jira for "In Progress" tasks

Use shell tool with `curl` to fetch tasks:

```bash
curl -s -X GET \
  -H "Authorization: Basic $(echo -n '$JIRA_EMAIL:$JIRA_TOKEN' | base64)" \
  -H "Content-Type: application/json" \
  "https://$JIRA_URL/rest/api/3/search?jql=assignee=$JIRA_EMAIL AND status='In Progress' AND updated <= '$EIGHT_HOURS_AGO'&fields=key,summary,updated,status"
```

Where:
- `$JIRA_EMAIL` — from memory (`jira_email`)
- `$JIRA_TOKEN` — from memory (`jira_api_token`)
- `$JIRA_URL` — from memory (`jira_url`)
- `$EIGHT_HOURS_AGO` — ISO 8601 timestamp from Step 1

Parse the JSON response to extract:
- `key` — task key (e.g., `PROJ-123`)
- `summary` — task summary/title
- `updated` — last update time
- `status` — current status

## Step 3: Find "To Do" transition ID

For each task to move, you need to find the transition ID for "To Do" status.

Use shell to get available transitions:

```bash
curl -s -X GET \
  -H "Authorization: Basic $(echo -n '$JIRA_EMAIL:$JIRA_TOKEN' | base64)" \
  -H "Content-Type: application/json" \
  "https://$JIRA_URL/rest/api/3/issue/$TASK_KEY/transitions"
```

Parse the response to find the transition ID where `to.name` = "To Do" (or "Open" / "Backlog" depending on your workflow).

**Note:** Different Jira workflows have different status names. Common "To Do" equivalents:
- "To Do"
- "Open"
- "Backlog"
- "Selected for Development"

Store the transition ID (e.g., `11` or `21`).

## Step 4: Move tasks to "To Do"

For each stalled task, use shell to transition:

```bash
curl -s -X POST \
  -H "Authorization: Basic $(echo -n '$JIRA_EMAIL:$JIRA_TOKEN' | base64)" \
  -H "Content-Type: application/json" \
  -d '{"transition": {"id": "$TRANSITION_ID"}}' \
  "https://$JIRA_URL/rest/api/3/issue/$TASK_KEY/transitions"
```

Track which tasks were successfully moved.

## Step 5: Notify user in Telegram (ONLY if actions were taken)

**IMPORTANT:** Your final text response is sent DIRECTLY to Telegram as-is.

If **NO tasks** were moved:
- Output nothing (silent run). Do NOT send "No tasks moved" messages.

If **tasks WERE moved**:
- Output a concise summary starting with 🔄 emoji.

Format:
```
🔄 Jira Auto-Move — DD Month YYYY, HH:MM

Tasks moved: N

• PROJ-123 — Short task summary (updated 2 hours ago)
• PROJ-456 — Another task (updated 5 hours ago)

All tasks moved from In Progress → To Do.
```

NOTE: If a task's own `summary` field is non-English (Russian, etc.), reproduce it verbatim — do NOT translate it. Only your own surrounding text is English.

Rules:
- Start with 🔄 emoji (first character!)
- Include task keys as clickable links if possible: `[PROJ-123](https://your-company.atlassian.net/browse/PROJ-123)`
- Show how long ago each task was updated
- Keep it concise (max 500 chars for typical cases)
- No [[wikilinks]] in Telegram output
- Nothing after the summary (no "Skill completed", no meta-commentary)

## Error handling

- **Authentication failed:** Output "❌ Jira auth failed. Check API token."
- **Jira unreachable:** Output "❌ Jira unavailable. Retry later."
- **No stalled tasks:** Output nothing (silent)
- **Transition failed for a task:** Log the error, continue with other tasks, mention in summary: "⚠️ PROJ-123: failed to move"

## Cron schedule

Recommended schedule: Every hour during work days (9:00 - 19:00, Monday-Friday)

Cron expression: `0 9-19 * * 1-5` (with tz: `Europe/Nicosia`)

## Memory setup (one-time)

User should run these commands to store credentials:
```
/store core jira_url https://your-company.atlassian.net
/store core jira_email your@email.com
/store core jira_api_token your_api_token_here
```

Or ask the user to provide credentials, then store them using `memory_store`.
