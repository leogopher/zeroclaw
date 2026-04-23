# Phase 1 — Rust pre-LLM dispatcher

**Status:** code in place, release binary built, daemon NOT yet restarted.

## Files changed

- `src/config/schema.rs` — added `anki_dispatcher_enabled: bool` field (with `#[serde(default)]`) to `TelegramConfig`. Updated six existing struct-literal sites (three in schema.rs itself, one in config/mod.rs, one in onboard/wizard.rs, one in integrations/registry.rs, one in channels/mod.rs test, three in daemon/mod.rs tests).
- `src/channels/telegram.rs`:
  - Added constants `ANKI_DISPATCHER_PYTHON`, `ANKI_DISPATCHER_SCRIPT`, `ANKI_PENDING_DIR`, `ANKI_DISPATCHER_TIMEOUT_SECS`.
  - Added `LazyLock<regex::Regex>` statics for the three patterns (preview / confirm / cancel).
  - Added private enum `AnkiDispatchKind` (Preview / Confirm / Cancel).
  - Added `anki_dispatcher_enabled: bool` field to `TelegramChannel` struct + `with_anki_dispatcher(bool)` builder.
  - Added inherent methods: `split_reply_target()`, `classify_anki_message()`, `try_handle_anki_message()`.
  - Wired call into `listen()` right after the "typing" indicator, before `tx.send(msg)`.
- `src/channels/mod.rs` — both `TelegramChannel` construction sites now chain `.with_anki_dispatcher(tg.anki_dispatcher_enabled)`.
- `<HOME>/.zeroclaw/config.toml` — added `anki_dispatcher_enabled = true` under `[channels_config.telegram]`.

## Safety properties

- Preview regex matches only the three exact prefixes at start of message; Russian/Polish/etc. text with similar meaning won't match.
- Confirm + cancel fire only when `~/.zeroclaw/anki-pending/<chat_id>.json` exists. So bare "cancel" or "foo 5" in normal chat falls through to the LLM.
- Subprocess: 30s timeout, stdin null, `kill_on_drop(true)` so a runaway child gets cleaned up if the daemon drops.
- Any spawn / I/O / timeout / non-zero-exit error → logged + user gets `⚠️ Anki dispatcher error — see logs.` (still counts as intercepted; message does NOT fall through to LLM on error — by design, to avoid the LLM making up Anki replies).
- Flag `anki_dispatcher_enabled = false` disables the feature entirely without a rebuild.

## Build

`cargo build --release` completed in 11m00s with 0 errors, 2 warnings (one preexisting in `cron/scheduler.rs`, one fixed in my code). Binary at `<HOME>/.agents/zeroclaw/target/release/zeroclaw`.

## Deploy

NOT yet deployed. Need to: (1) verify the systemd unit points at the release binary, (2) `systemctl --user restart zeroclaw.service`, (3) verify with `journalctl`. Deferred to Phase 5 testing, once dispatcher.py exists — restarting now would break the current LLM-driven flow since dispatcher.py is not yet written.

## Next

Phase 2 (lookup.py multi-sense) — DONE in parallel. Phase 3 (dispatcher.py) is next.
