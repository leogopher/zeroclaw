---
name: anki-cards
description: Multi-sense English vocabulary → Anki flashcards. Triggered by "New Anki Cards", "Anki Cards", or "Add to Anki". Handled entirely by a deterministic Python dispatcher invoked BEFORE the LLM — no model prompting, no hallucinated previews. User picks which sense(s) of each word to learn; multiple cards per word are supported with a disambiguation label on Card 1.
version: 0.2.0
tags: [anki, english, vocabulary, flashcards]
---

# Anki Cards Skill

This skill is **LLM-free at runtime**. The zeroclaw Rust daemon intercepts
Anki-trigger messages in `src/channels/telegram.rs` and spawns
`dispatcher.py` directly. The LLM never sees these messages, so it can't
fabricate a reply or skip a step.

## Trigger patterns

All matched case-insensitively at the **start** of the message:

| Pattern | Subcommand | Fires when |
|--|--|--|
| `new anki cards`, `anki cards`, `add to anki` (prefix + optional colon) | `preview` | always |
| `<word> <digits>[,<digits>...][;<word> <digits>...]` | `confirm` | pending file exists |
| `cancel` | `cancel` | pending file exists |

The `confirm` and `cancel` regexes only fire when
`~/.zeroclaw/anki-pending/<chat_id>.json` exists. A bare "cancel" or a
stray "5 apples" in normal chat falls through to the LLM.

## Two-phase flow

### Phase A — Preview (LLM-free)

1. User sends `New Anki Cards: pace; trait`.
2. Dispatcher parses term list, calls `lookup.py` for each term (up to 5
   senses per term from Cambridge, with Free Dictionary API fallback).
3. For each sense, checks if an existing deck note already has that
   meaning → flags `↺ Already in deck`.
4. Writes `~/.zeroclaw/anki-pending/<chat_id>.json` (TTL 10 min).
5. Prints preview to Telegram:

   ```
   🗂 Preview — reply to add

   1. pace /peɪs/
      (1) [noun] the speed at which someone or something moves…  ↺ Already in deck
          _a slow / fast pace_
      (2) [noun] while moving quickly
          _It can be scary for a defender when you see an attacker…_
      (3) [noun] the rate at which something happens
      …

   2. trait /treɪt/
      (1) [noun] a particular characteristic that can produce…
          _His sense of humour is one of his better traits._
      …

   Reply like: `pace 1,3; trait 1;`
   Or `cancel` to drop.
   ```

### Phase B — Confirm or cancel (LLM-free)

- **Confirm** — user replies `pace 1,3; trait 1;`. Dispatcher parses, builds
  one card per picked sense, and calls `ankiconnect.add_entries`. When a
  word has ≥2 notes in the deck, Card 1 shows `pace (speed)` / `pace (step)`
  etc.; when exactly 1, the `(label)` hint is hidden. Emits:

   ```
   ✅ Added 3 cards:
    • pace (speed)
    • pace (rate)
    • trait
   ```

- **Cancel** — user replies `cancel`. Pending file dropped. Emits
  `❌ Cancelled.`.

## Paths

- Skill dir: `<HOME>/.zeroclaw/workspace/skills/anki-cards/`
- Venv python: `.venv/bin/python` (BeautifulSoup, requests)
- Helpers: `lookup.py`, `dispatcher.py`, `ankiconnect.py`, `cloze.py`
- Lookup cache: `~/.zeroclaw/cache/anki/v2_<slug>.json` (30-day TTL)
- Pending state: `~/.zeroclaw/anki-pending/<chat_id>.json` (10-min TTL)

## Anki model

`ZeroClaw English 3-Card` — 7 fields:
`Word`, `Meaning`, `IPA`, `Example`, `ExampleCloze`, `Audio`, `Disambiguation`

Three templates:

| Card | Front | Back |
|--|--|--|
| 1 Recognition | Word (+ disambig hint) + Audio | IPA, Meaning, Example |
| 2 Production | Meaning + cloze | Word, IPA, Audio |
| 3 Listening | Audio | Word, IPA, Meaning |

`Disambiguation` renders only when non-empty — polysemous entries (e.g.
`pace (speed)` vs `pace (step)`) and single-sense entries render cleanly.

## Fix Anki (legacy LLM path)

`Fix Anki:` is **NOT** routed through the dispatcher — it still goes to
the LLM. The LLM should call:

```
.venv/bin/python ankiconnect.py update "<term>" "<Field>" "<new value>"
```

Valid fields: `Word`, `Meaning`, `IPA`, `Example`, `ExampleCloze`, `Audio`, `Disambiguation`.

If multiple notes share the same `Word`, the update touches every matching
note — warn the user if they need to disambiguate (and instruct them to
delete the wrong card manually via Anki GUI).

## Disabling the dispatcher

Set `anki_dispatcher_enabled = false` under `[channels_config.telegram]`
in `<HOME>/.zeroclaw/config.toml`, restart the daemon. All Anki
messages then go to the LLM — which, without an updated skill definition,
will reply conversationally. (There is no up-to-date LLM fallback for
the new flow; disable at your own risk.)

## One-time setup

Anki runs in Docker on the Pi. See `docker/README.md`. After initial
container build, VNC into `127.0.0.1:5900` once to log in to AnkiWeb; the
daemon's `sync` calls after that will push automatically.

Health check:

```bash
.venv/bin/python ankiconnect.py ping
```

## Troubleshooting

- **`⚠️ Anki dispatcher error — see logs.`** — subprocess crashed or
  timed out (30 s). Check `journalctl -t zeroclaw` for the traceback.
- **`⚠️ sync pending: Sync status 2`** — Anki wants a full sync, which
  needs VNC login. Notes are saved locally; VNC in and resolve the sync
  conflict.
- **Preview shows only 1 sense when more expected** — Cambridge may be
  showing a simpler page (e.g. for inflected forms). Try the lemma.
