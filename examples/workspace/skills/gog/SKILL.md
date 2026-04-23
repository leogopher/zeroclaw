---
name: gog
description: Google Calendar & Tasks. Invoke this skill whenever the user asks about their calendar, schedule, events, meetings, agenda, or Google Tasks. Account is already authorized as <OWNER_EMAIL>. Scope is calendar + tasks only.
version: 0.3.0
tags: [google, calendar, tasks]
---

# gog — Google Calendar & Tasks

The Google account is already authenticated. Do NOT call `google-lev__*` (those tools are removed). Do NOT ask the user to authenticate.

## CRITICAL: how to actually run commands

You reach `gog` and `agenda` ONLY by calling the `shell` tool. Never type the command as your reply — that is useless to the user. Invoke the tool.

### Correct tool call (JSON the runtime expects)

```json
{
  "tool": "shell",
  "arguments": {
    "command": "agenda today"
  }
}
```

After the tool returns, take its **stdout** and send that (verbatim) as the Telegram message. Do not add a preamble, do not paraphrase, do not wrap in code fences.

**Your reply must start with the first character of the tool output** (for `agenda` that's the 📅 emoji). Never begin with `thought`, `thinking`, `Here is`, `I'll`, `Sure`, or any other meta-commentary. The first token of your Telegram message MUST be 📅 (or `_No events._` if the tool returned that). If you catch yourself about to write a preamble, delete it and emit only the stdout.

### Wrong behavior (do not do this)

- ❌ Replying with the literal text `agenda today` — that is a command, not an answer.
- ❌ Replying "I'll check your calendar" without calling the tool.
- ❌ Replying "I couldn't connect to Google" — the tool has not been tried yet. Always call `shell` first; only report an error if the tool itself returned a non-zero exit.

## Reading the calendar — always `agenda`

The `agenda` wrapper already spans every calendar, normalizes times to <OWNER_COUNTRY> local (EEST/EET), groups by day, and returns ready-to-send Markdown.

Map the user's question to **one** `shell` call:

| User asks | `command` |
| --- | --- |
| "agenda" / "calendar" / "schedule" / "my events" (no timeframe specified) | `agenda today` |
| "what's today" / "what's today?" / "today" / "today?" — **always treat as a calendar query, never just the date** | `agenda today` |
| "my schedule" / "today's events" / "events today" / "list of events for today" | `agenda today` |
| "tomorrow" / "what's tomorrow" | `agenda tomorrow` |
| "this week" / "the week" | `agenda week` |
| "next 7 days" / "next N days" | `agenda days 7` |
| "between <date> and <date>" | `agenda from 2026-04-23 to 2026-04-30` |

If stdout is `📅 **Today — ...**` with bullet events, send exactly that. If stdout contains `_No events._`, send exactly that with its header.

**VERBATIM MEANS VERBATIM.** Do not translate, localize, or paraphrase any part of the stdout — not the header, not the weekday/month abbreviations, not the event summaries. If an event title is in Russian/Greek/Chinese/etc., pass it through byte-for-byte; that is the actual calendar data. Your English-only rule applies to *your own writing*, never to tool output you are forwarding. Writing `Сегодня — Чт 23 Апр` when the tool emitted `Today — Thu 23 Apr` is a bug.

**ALWAYS re-run the `shell` tool for every new calendar question.** Never reuse or paraphrase a prior turn's answer. Calendars change between messages; the only correct source is the tool output for this turn.

## Listing calendars

`shell` tool, `command: "gog calendar calendars --plain"`. Send the TSV as-is or reformat to a short list of `Name — role`. Do not invent calendar names.

## Creating / updating / deleting events

Still via the `shell` tool, but **confirm with the user before the call**. Parse their request, reply in plain words ("Thu 23 Apr, 14:00–15:30 <OWNER_CITY> time — add to primary calendar?"), wait for explicit OK. Then call:

```
gog calendar create primary \
  --summary "Visit Dermatologist" \
  --from 2026-04-23T14:00:00+03:00 \
  --to   2026-04-23T15:30:00+03:00 \
  --location "<OWNER_CITY>" \
  --reminder popup:30m
```

Rules for the `--from` / `--to` timestamps:
- <OWNER_COUNTRY> summer (EEST, last Sunday of March → last Sunday of October): offset `+03:00`.
- <OWNER_COUNTRY> winter (EET): offset `+02:00`.
- All-day: date-only `--from` / `--to` plus `--all-day`.
- Non-primary calendar: replace `primary` with the ID from `gog calendar calendars`.
- Uncertain about flag parsing? Add `-n` / `--dry-run` first.

Update: `gog calendar update <eventId> --summary "..." --from ... --to ...`
Delete: `gog calendar delete <eventId>` (confirm first).

## Tasks

Also via the `shell` tool:

- `gog tasks lists --plain` — list task lists
- `gog tasks list --plain` — items in the default list
- `gog tasks list --list <listID> --plain` — items in a specific list
- `gog tasks add --title "Buy milk" --notes "..."`
- `gog tasks complete <taskID>` (confirm first)
- `gog tasks delete <taskID>` (confirm first)

Format a task list as Markdown checkboxes:

```
📝 **Tasks**

- [ ] Buy milk
- [x] Submit timesheet
- ⚠️ [ ] Pay rent (overdue)
```

## Guardrails

- `GOG_ACCOUNT=<OWNER_EMAIL>` is preset — omit `--account`.
- Gmail, Drive, Contacts, Sheets, Docs subcommands exist in `gog` but are **out of scope** for this install. If asked, tell the user those aren't wired up.
- If a `shell` call returns `aes.KeyUnwrap(): integrity check failed`, surface it: `GOG_KEYRING_PASSWORD` is out of sync. Don't try to repair silently.
- Never fabricate events, calendars, or task items. Only report what the tool actually returned.
