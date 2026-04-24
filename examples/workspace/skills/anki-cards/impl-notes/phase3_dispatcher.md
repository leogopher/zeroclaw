# Phase 3 — dispatcher.py (preview/confirm/cancel)

**Status:** complete, local preview run verified.

## CLI

```
dispatcher.py preview <chat_id> <message_text>
dispatcher.py confirm <chat_id> <reply_text>
dispatcher.py cancel  <chat_id> [<text>]
```

Writes response to stdout. The Rust Telegram handler pipes stdout to
`send_text_chunks` verbatim.

## State

- Dir: `~/.zeroclaw/anki-pending/<chat_id>.json`
- TTL: 10 min (`PENDING_TTL_SEC = 600`)
- `_purge_expired_pending()` runs at the top of each `preview`.
- `_read_pending()` returns `None` for missing or stale files (and deletes the stale file).

## Preview flow

1. Strip trigger prefix (case-insensitive regex), split remainder on newlines + semicolons, drop numbered markers, dedup preserving order.
2. For each term: `lookup.lookup(term)` — NDJSON already cached.
3. Flag `existing_sense_indices`: `findNotes "Word:<term>"`, `notesInfo`, compare each sense's normalized meaning against every existing note's `Meaning` field.
4. Write pending JSON with `{created_at, terms: [..., existing_sense_indices]}`.
5. Emit preview (see `_format_preview`). Adds `⚠️ no audio` to header if term has no audio, `↺ Already in deck` next to each matching sense.

## Confirm flow

1. `_read_pending()`; on missing/expired → English error and exit 0.
2. `parse_reply(reply_text)` → `{"pace": [1, 3], "trait": [1]}` (1-based as typed).
3. Validate: unknown terms, out-of-range sense nums → English error, zero added.
4. For each pick: build entry `{word, label, meaning, ipa, example, example_cloze, audio_url}` (cloze from `cloze.cloze`).
5. Re-picks of already-in-deck senses are allowed — included in entries but flagged in the confirmation message.
6. `ank.add_entries(entries)` → AnkiConnect add + disambiguation refresh.
7. Delete pending file. Emit `✅ Added N cards:` summary with `(label)` hint per card.

## Cancel flow

- Delete pending file, emit `❌ Cancelled.` — or `❌ Nothing pending to cancel.` if no file.

## Error philosophy

- All errors surface as English one-liners to stdout (so Telegram gets something useful).
- Top-level `main()` wraps every subcommand in try/except → on unexpected crash, prints the standard `⚠️ Anki dispatcher error — see logs.` and exits 1. Rust will still see non-zero and log the stderr traceback.

## Local smoke test

```
$ dispatcher.py preview <OWNER_TELEGRAM_ID> "New Anki Cards: pace; trait"
```

Returned a formatted 8-sense preview in English, wrote `~/.zeroclaw/anki-pending/<OWNER_TELEGRAM_ID>.json`, flagged `pace` sense 1 and `trait` sense 1 as already in deck (correctly — those are the pre-existing notes).

Confirm path NOT exercised yet — deferred to Phase 5 with real Telegram input to avoid mutating the deck twice.
