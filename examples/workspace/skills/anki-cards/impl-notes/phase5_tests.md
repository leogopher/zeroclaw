# Phase 5 — Pi testing

**Status:** all locally-runnable tests pass. Live-Telegram leg awaits <OWNER_NAME>.

## Current deck state

After Phase 4+5:

| Word | Notes | Disambiguation labels |
|--|--|--|
| pace | 4 | speed, moving, progressing, make |
| trait | 2 | characterist, personality |
| cheerful | 1 | "" (empty — single-note, hidden by Mustache) |
| stubborn | 1 | "" |
| curious | 1 | "" |
| rebellious | 1 | "" |
| albeit | 1 | "" |
| serendipity | 1 | "" |
| quixotic | 1 | "" |
| hit the sack | 1 | "" |

10 pre-existing + 3 added during test 1 (pace moving, pace progressing, trait personality) + 1 added during test 2 (pace make) = 14 notes total.

## Test log

1. **Happy path** — `preview pace; trait` → 8 senses shown, `↺ Already in deck` on senses that match existing notes. `confirm pace 2,3; trait 2;` → 3 cards added. Labels `speed`/`moving`/`progressing` on pace (old + 2 new), `characterist`/`personality` on trait. ✅
2. **Retroactive** — `preview pace` again → senses 1-3 flagged `↺ Already in deck`. `confirm pace 4;` → 4th card added. All 4 pace notes retain distinct labels. ✅
3. **Already-in-deck flag** — visible in test 1 preview for pace sense 1 and trait sense 1; visible in test 2 for pace senses 1, 2, 3. ✅
4. **Cancel** — preview cheerful → pending file created. `cancel` → pending dropped, `❌ Cancelled.` emitted. ✅
5. **Expired pending** — preview → `touch -d "20 minutes ago"` the pending file → confirm → `⚠️ No pending preview (or expired).`, pending auto-deleted. ✅
6. **Polysemous cap** — `preview bank` → exactly 5 senses (Cambridge has more). ✅
7. **Single-sense** — `preview quixotic` → 2 senses (Cambridge has 2 sub-senses), preview hint is `quixotic 1;` / `quixotic 1,2;` — not `trait 1;`. ✅
8. **Migration** — existing 10 notes all got `Disambiguation=""` after `ensure_model` ran. Card 1 template now contains the Mustache conditional; empty Disambiguation renders identically to pre-migration. ✅
9. **Reliability (A1)** — NOT run. Would require deliberately killing GLM/OpenRouter endpoints; trusting the architecture (regex short-circuits before `tx.send(msg)`).
10. **Foreign-language safety** — NOT live-tested. Verified by inspection: the Rust preview regex `^(new anki cards|anki cards|add to anki)\b` is ASCII-only; "Новые Anki карточки:" cannot match, so the dispatcher is never invoked. Message falls through to LLM, which replies in English per AGENTS.md.

## Follow-up fixes during testing

- Initial `_fallback_label` in `ankiconnect.py` had a smaller stopword list than `lookup.py`, giving `trait` note a label of `can` instead of `characterist`. Fixed by importing `lookup.label_candidates` lazily inside `_fallback_label`. Re-ran refresh — label corrected in-place.
- Preview hint was hardcoded `"... trait 1;"` as the example second-term even when the preview only had one term. Fixed to adapt to the actual preview contents.
- `✅ Added 1 cards:` grammar — fixed to pluralize correctly.

## Pending <OWNER_NAME>-only test

Send via Telegram to the zeroclaw bot (chat <OWNER_TELEGRAM_ID>):

1. `New Anki Cards: bank` → expect preview with 5 senses.
2. Reply `bank 1,3;` → expect `✅ Added 2 cards: • bank (organization) • bank (sloping)`.
3. Send `cancel` outside any pending flow → LLM should receive it (not the dispatcher). The LLM's English reply is expected — proves the no-pending-file short-circuit.
4. Send `Новые Anki карточки: pace` → LLM receives it (not the dispatcher), because the regex is ASCII-only. The LLM's English reply is expected.
