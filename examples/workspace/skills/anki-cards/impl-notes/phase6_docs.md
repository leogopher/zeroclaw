# Phase 6 — Documentation sweep

**Status:** complete.

## Files updated

- `workspace/AGENTS.md` — `## Anki Cards` section rewritten. LLM is now told **not** to reply to Anki-trigger messages; the dispatcher handles them deterministically. If an Anki-trigger message ever reaches the LLM, that signals the dispatcher is disabled or broken — the LLM responds with a pointer to the config flag instead of trying to add cards itself. `Fix Anki:` is still LLM-handled.

- `workspace/skills/anki-cards/SKILL.md` — full rewrite. Documents the two-phase (preview / confirm) flow, the pending state file, the new 7-field model with Disambiguation, the Card 1 template change, the regex triggers, and the `anki_dispatcher_enabled` kill switch. Removes all fire-and-forget wording.

- `.gitignore` — added `anki-pending/` so runtime pending-preview state never gets committed.

## Summary of the full change set

| Path | Scope |
|--|--|
| `<HOME>/.agents/zeroclaw/src/channels/telegram.rs` | Regex intercept + dispatcher subprocess + `with_anki_dispatcher` builder |
| `<HOME>/.agents/zeroclaw/src/channels/mod.rs` | Wire flag into both TelegramChannel build sites |
| `<HOME>/.agents/zeroclaw/src/config/schema.rs` | `anki_dispatcher_enabled: bool` field on `TelegramConfig` |
| `<HOME>/.agents/zeroclaw/src/config/mod.rs` | Test fixture literal |
| `<HOME>/.agents/zeroclaw/src/daemon/mod.rs` | 3 test fixture literals |
| `<HOME>/.agents/zeroclaw/src/integrations/registry.rs` | Test fixture literal |
| `<HOME>/.agents/zeroclaw/src/onboard/wizard.rs` | Onboarding wizard literal |
| `<HOME>/.zeroclaw/config.toml` | `anki_dispatcher_enabled = true` |
| `<HOME>/.zeroclaw/workspace/skills/anki-cards/lookup.py` | Rewrite to multi-sense |
| `<HOME>/.zeroclaw/workspace/skills/anki-cards/ankiconnect.py` | Disambiguation field, multi-card add, model migration |
| `<HOME>/.zeroclaw/workspace/skills/anki-cards/dispatcher.py` | NEW — preview/confirm/cancel |
| `<HOME>/.zeroclaw/workspace/skills/anki-cards/SKILL.md` | Rewrite |
| `<HOME>/.zeroclaw/workspace/AGENTS.md` | Anki section updated |
| `<HOME>/.zeroclaw/.gitignore` | Ignore `anki-pending/` |

## Non-obvious design choices worth remembering

- `anki_dispatcher_enabled` lives under `[channels_config.telegram]`, not top-level. The dispatcher is Telegram-specific (it relies on `send_text_chunks`), so the flag is too.
- Dispatcher errors always intercept — they do NOT fall through to the LLM. The alternative (fall-through on error) would let the LLM improvise a broken Anki reply, which is exactly the reliability problem the dispatcher was built to solve.
- Audio is stored once per word (`zc_pace.mp3`), shared across all senses of that word. Different senses of `pace` all reference the same MP3 — no duplicate downloads, no AnkiWeb media bloat.
- `Disambiguation` uses Mustache `{{#…}}…{{/…}}` — when empty, the entire `(label)` wrapper disappears. Single-sense entries render exactly like they did pre-migration.
