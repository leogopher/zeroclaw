# Phase 0 — Scout findings

**Status:** complete.

## Hook point

- **File:** `<HOME>/.agents/zeroclaw/src/channels/telegram.rs`
- **Function:** `async fn listen(&self, tx: tokio::sync::mpsc::Sender<ChannelMessage>)` — starts at line 2528
- **Insertion window:** between line 2690 (after `ChannelMessage` is built by `parse_update_message`) and line 2713 (`tx.send(msg).await`), inside the `for update in results` loop.

## Available at that point

- `msg.content: String` — user text
- `msg.reply_target: String` — `"<chat_id>"` or `"<chat_id>:<thread_id>"` (see line 1319 for the format)
- `msg.thread_ts: Option<String>` — the thread_id if present (set at line 1349)
- `self.send_text_chunks(&text, &chat_id, thread_id.as_deref())` — async helper at line 1555 that posts to Telegram directly, bypassing the LLM dispatch path

## Bypass strategy

If regex matches: spawn `dispatcher.py`, pipe stdout to `send_text_chunks`, then `continue` the loop. Do NOT call `tx.send(msg)` — that is the channel that hands the message to the LLM runtime.

The typing indicator block at line 2702-2711 can stay as-is; Telegram showing "typing…" briefly while the Python subprocess runs is fine.

## Config flag location

Add `anki_dispatcher_enabled: bool` (with `#[serde(default)]`) to `TelegramConfig` at `src/config/schema.rs:4495`. Matches existing idiom (`mention_only`, `stream_mode`, `interrupt_on_new_message`).

TOML key: `[channels_config.telegram].anki_dispatcher_enabled = true`

## Test-path note

Running regex checks BEFORE `tx.send` keeps the change local to `telegram.rs` — no need to touch the runtime/dispatcher side. Non-Telegram channels remain on the LLM path.

## Dispatcher invocation plan

- Binary: `<HOME>/.zeroclaw/workspace/skills/anki-cards/.venv/bin/python`
- Script: `<HOME>/.zeroclaw/workspace/skills/anki-cards/dispatcher.py`
- Args: `preview <chat_id> <text>`, `confirm <chat_id> <text>`, or `cancel <chat_id>`
- Timeout: 30 s (tokio::time::timeout around the subprocess wait)
- On timeout or non-zero exit: send `⚠️ Anki dispatcher error — see logs.`
