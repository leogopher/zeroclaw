# Anki Cards — Multi-Sense Implementation Plan

**Status:** approved, not started
**Owner:** <OWNER_FULL_NAME>
**Target:** zeroclaw daemon + anki-cards skill

---

## Context

The current anki-cards skill has two problems:

1. **Reliability.** The LLM (Gemma 26B or GLM-5) sometimes emits a stub reply (`🗂 I've processed your new Anki cards...`) instead of the full preview defined in `SKILL.md`. Cards still get added, but the user never sees which meaning/example was chosen for each term. This is a model-capability issue, not a prompt issue.

2. **No sense review.** `lookup.py` returns only the first Cambridge sense. Words like `pace` (speed / step / rate / to walk) or `bank` (finance / riverside / to rely on / ...) have many valid meanings; the user wants to pick which sense(s) to learn, possibly creating multiple cards for the same word.

## Solution summary

- **Problem 1 → A1:** Patch zeroclaw Rust daemon with a pre-LLM regex filter that intercepts Anki-trigger messages and routes them to a deterministic Python dispatcher. LLM never sees those messages; can't hallucinate.
- **Problem 2 → B1–B5:** Upgrade lookup to multi-sense, add a preview/confirm UX, allow multiple cards per word with a disambiguation label on Card 1 only.

---

## Phase 0 — Scout zeroclaw source (30 min)

**Goal:** find the hook point for pre-LLM message interception.

**Steps:**
1. Read `<HOME>/.agents/zeroclaw/src/` tree.
2. Locate the Telegram channel handler (likely `channels/telegram.rs` or similar).
3. Identify the function that forwards a user message to the LLM dispatcher.
4. Decide on a clean insertion point for a regex filter that can short-circuit the LLM path.

**Deliverable:** note in this file — exact file + line number of the hook point. If the code is monolithic and there is no clean insertion point, STOP and surface options before cutting code.

---

## Phase 1 — A1: Rust pre-LLM dispatcher (≈ 2 hrs)

**Goal:** messages matching Anki triggers never reach the LLM.

**Triggers (case-insensitive):**
- Preview: `^(new anki cards|anki cards|add to anki)\b`
- Confirm reply: `^[a-z][a-z \-]* \d+(,\d+)*(\s*;\s*[a-z][a-z \-]* \d+(,\d+)*)*;?\s*$`
- Cancel: `^cancel\s*$`

**Behaviour:**
1. On Telegram message arrival, run regex checks BEFORE LLM dispatch.
2. If preview trigger → spawn `dispatcher.py preview <chat_id> <text>`, send stdout to Telegram.
3. If confirm trigger AND `~/.zeroclaw/anki-pending/<chat_id>.json` exists → spawn `dispatcher.py confirm <chat_id> <text>`, send stdout to Telegram.
4. If cancel trigger AND pending exists → delete pending, reply `❌ Cancelled.`
5. If no match → existing LLM path, unchanged.

**Safety:**
- Add a config flag (e.g. `anki_dispatcher_enabled = true` in `config.toml`) so the feature can be disabled without a rebuild.
- Dispatcher process timeout: 30 s. On timeout or non-zero exit, log and send `⚠️ Anki dispatcher error — see logs.`

**Files:**
- `<HOME>/.agents/zeroclaw/src/**` — patch (exact file determined in Phase 0)
- `<HOME>/.zeroclaw/config.toml` — add feature flag

---

## Phase 2 — B1: Multi-sense lookup (≈ 1 hr)

**Goal:** `lookup.py` returns up to 5 senses per term with POS tags and short labels.

**Changes to `workspace/skills/anki-cards/lookup.py`:**

1. Parse ALL `.pos-block` containers on a Cambridge page, not just the first.
2. For each definition block within a pos-block, extract:
   - `pos` — part of speech (`noun`, `verb`, `adjective`, ...)
   - `meaning` — definition text, cleaned (strip `infml`, `fml`, `UK`, `US` labels)
   - `example` — first `.dexamp` under that definition
   - `label` — short tag auto-extracted from `meaning` (algorithm below)
3. Cap total senses per term at 5. Preserve Cambridge's order (already frequency-ranked).
4. Keep IPA and audio at the TOP level (same across senses).

**Label extraction algorithm:**
- Take the first 80 chars of `meaning`.
- Strip leading `a `, `an `, `the `, `to be `, `to `.
- Tokenize by whitespace + punctuation.
- Drop stopwords (`of, at, which, that, when, where, who, someone, something, person, place, thing, ...`).
- Return first remaining token, lowercased, max 12 chars.
- Fallbacks: if empty → use `sense <N>` (e.g. `sense 2`).

Examples:
| Meaning | Label |
|--|--|
| "the speed at which someone or something moves" | `speed` |
| "a single step when walking or running" | `step` |
| "the rate at which something happens" | `rate` |
| "to walk back and forth because you are worried" | `walk` |

**New output schema (NDJSON, one line per term):**
```json
{
  "term": "pace",
  "ipa_us": "peɪs",
  "audio_url": "https://...",
  "source": "cambridge",
  "senses": [
    {"pos": "noun", "meaning": "the speed at which...", "example": "She set a fast pace...", "label": "speed"},
    {"pos": "noun", "meaning": "a single step...",      "example": "He took two paces...",    "label": "step"},
    {"pos": "noun", "meaning": "the rate at which...",  "example": "The pace of change...",   "label": "rate"},
    {"pos": "verb", "meaning": "to walk back and forth...", "example": "He paced the floor...", "label": "walk"}
  ]
}
```

**Cache:**
- Bump cache key prefix to `v2_` so old single-sense entries are invalidated.
- Cache dir unchanged: `~/.zeroclaw/cache/anki/`.

**Fallbacks (unchanged paths, updated shape):**
- Free Dictionary API: up to 3 senses, same schema, `source: "freedict"`.
- Nothing found: `senses: []`, `source: "none"`, `partial: true`. Dispatcher handles this case in the preview.

---

## Phase 3 — Dispatcher preview/confirm flow (≈ 2 hrs)

**New file:** `workspace/skills/anki-cards/dispatcher.py`

**Subcommand `preview <chat_id> <message_text>`:**

1. Parse terms from `message_text` (existing logic: split on `;`, numbered markers, newlines).
2. For each term, call `lookup.py`.
3. For each sense, query Anki: `findNotes "Word:<term>"`, compare Meaning against existing notes. If exact match → flag that sense `already_in_deck: true`.
4. Write `~/.zeroclaw/anki-pending/<chat_id>.json`:
   ```json
   {
     "created_at": "2026-04-23T...",
     "terms": [
       {"term": "pace", "ipa_us": "peɪs", "audio_url": "...",
        "senses": [...],
        "existing_sense_indices": [0]}
     ]
   }
   ```
5. Emit preview to stdout (format below).

**Preview format (English only, per AGENTS.md):**

```
🗂 Preview — reply to add

1. pace /peɪs/
   (1) [noun] the speed at which someone or something moves
       _She set a fast pace as we walked through the park._
   (2) [noun] a single step when walking or running
       _He took two paces forward._  ↺ Already in deck
   (3) [noun] the rate at which something happens
       _The pace of change accelerated._
   (4) [verb] to walk back and forth because you are worried
       _He paced the floor nervously._

2. trait /treɪt/
   (1) [noun] a particular characteristic that can produce a particular type of behaviour
       _His sense of humour is one of his better traits._
   (2) [noun] a genetically determined characteristic
       _Blue eyes is a recessive trait._

Reply like: `pace 1,3; trait 1;`
Or `cancel` to drop.
```

**Subcommand `confirm <chat_id> <reply_text>`:**

1. Load `~/.zeroclaw/anki-pending/<chat_id>.json`. If missing or > 10 min old → stdout `⚠️ No pending preview (or expired). Send "New Anki Cards: ..." to start over.` and exit.
2. Parse reply: `pace 1,3; trait 1;` → `{"pace": [0, 2], "trait": [0]}` (zero-indexed internally).
3. Validate: unknown term in reply that wasn't in pending → error; out-of-range sense index → error.
4. For each (term, sense_indices) build card entries:
   ```json
   {"word": "pace", "sense_idx": 0, "label": "speed",
    "meaning": "...", "ipa": "peɪs", "example": "...",
    "example_cloze": "...", "audio_url": "..."}
   ```
5. Skip entries flagged `already_in_deck: true` unless user explicitly re-picked them (print a note).
6. Call `ankiconnect.py add <batch.json>` (see Phase 4 for multi-sense support).
7. Delete pending file.
8. Emit confirmation:
   ```
   ✅ Added 3 cards:
    • pace (speed)
    • pace (rate)
    • trait
   ```
   Or if some skipped:
   ```
   ✅ Added 2 cards:
    • pace (speed)
    • trait
   
   ↺ Skipped (already in deck):
    • pace (step)
   ```

**Subcommand `cancel <chat_id>`:** (optional — Rust side can also just delete the file)
- Delete pending, emit `❌ Cancelled.`

**State management:**
- New directory: `~/.zeroclaw/anki-pending/`.
- One file per chat: `<chat_id>.json`.
- TTL: 10 minutes. On every `preview`, purge files older than 10 min.
- On new `preview` for same chat_id: overwrite silently.

---

## Phase 4 — B3-new + B5: Multi-card add with disambiguation (≈ 2 hrs)

**Goal:** multiple cards per word, with a `(label)` hint on Card 1 (Recognition) only — and ONLY when the deck holds more than one card for that word.

**Model field addition:**
- Add field `Disambiguation` to model `ZeroClaw English 3-Card`. Default empty string.
- Use `modelFieldAdd` (idempotent — check first, skip if exists).
- Migrate existing 6 cards: set `Disambiguation = ""`. No visible change until a 2nd sense is added.

**Template changes:**
- **Card 1 (Recognition)** front: `{{Word}}{{#Disambiguation}} ({{Disambiguation}}){{/Disambiguation}}`
- **Card 2 (Production)** front: `{{Word}}` — unchanged
- **Card 3 (Listening)** front: `{{Audio}}` — unchanged (no Word shown)
- Back sides: unchanged for all 3 templates.

**Update `ankiconnect.py`:**

1. `add` command accepts a flat list of entries — each entry is one note (not one term). Multiple entries with the same `word` → multiple notes.
2. Entry schema:
   ```json
   {"word": "pace", "label": "speed",
    "meaning": "...", "ipa": "peɪs", "example": "...",
    "example_cloze": "...", "audio_url": "..."}
   ```
3. For each entry: `addNote` (with `allowDuplicate: false` removed — we need duplicates-by-word).
4. **Post-process (disambiguation refresh)** — after all adds, for each affected word:
   - `findNotes "Word:<word>"` → get note IDs
   - If count ≥ 2: for each note, `updateNoteFields` to set `Disambiguation = <that note's label>`
   - If count == 1: set `Disambiguation = ""` (clean up in case of deletion history)
5. `sync` at the end.

**Retroactive behaviour example:**
- Deck has `pace` (sense 1, label `speed`, Disambiguation `""`).
- User adds `pace 2` (label `step`).
- After add, `findNotes "Word:pace"` returns 2 notes.
- Post-process sets `Disambiguation = "speed"` on old note, `Disambiguation = "step"` on new note.
- Next review: Card 1 shows `pace (speed)` and `pace (step)` respectively.

**New `update` subcommand (optional, for future `Fix Anki`):**
- `update <word> <sense_idx> <field> <value>` — covers the Fix flow. Not required for this phase but scaffold if cheap.

---

## Phase 5 — Testing on Pi (≈ 30 min)

1. **Happy path:** `New Anki Cards: pace; trait` → preview shows 4 + 2 senses. Reply `pace 1,2; trait 1;` → 3 cards added. Verify in Anki GUI:
   - `pace` has 2 notes, Disambiguation `speed` / `step`
   - Card 1 shows `pace (speed)` and `pace (step)`
   - Card 2 & 3 show just `pace`
   - `trait` has 1 note, no disambiguation hint

2. **Retroactive:** Send `New Anki Cards: pace` → preview. Reply `pace 3;` → 1 new card. Verify all 3 pace notes now have labels (speed / step / rate) on Card 1.

3. **Already-in-deck flag:** Send `New Anki Cards: pace` again. Preview shows `↺ Already in deck` next to senses 1, 2, 3. Reply `pace 4;` → adds verb sense. Old cards updated to show disambiguation.

4. **Cancel:** Send `New Anki Cards: ...` → reply `cancel` → pending cleared, nothing added.

5. **Expired pending:** Send preview, wait 11 min, reply → error message, no add.

6. **Polysemous cap:** `New Anki Cards: bank` → exactly 5 senses in preview (Cambridge has ~10). Preview notes this if easy: `(showing top 5 of N senses)`.

7. **Single-sense word:** `New Anki Cards: cheerful` → 1 sense, user still must reply `cheerful 1;`. No disambiguation hint after add.

8. **Migration of existing 6 cards:** After Phase 4, confirm trait/pace/stubborn/curious/cheerful/rebellious still render correctly. `pace` will get its `(speed)` label the first time a 2nd pace card is added — BEFORE that, no hint.

9. **Reliability (A1):** Send `New Anki Cards: foo` while LLM is artificially unreachable (stop Anthropic/Z.ai). Cards flow still works — confirms LLM never touched.

10. **Foreign-language user test:** Send `Новые Anki карточки: pace` — should NOT match (regex is English-only). LLM handles, replies in English (per AGENTS.md language policy). This confirms the dispatcher isn't stealing non-English Anki-like requests.

---

## Phase 6 — Documentation sweep

- Update `workspace/skills/anki-cards/SKILL.md` to describe the new preview/confirm flow. Remove fire-and-forget wording. Add examples.
- Update `workspace/AGENTS.md` → `## Anki Cards` section. Remove the old "skill invocation" language; mention that the dispatcher now handles these messages deterministically and the LLM should NOT respond to them.
- Update `.gitignore` for `workspace/skills/anki-cards/.venv/` (already done?) and `~/.zeroclaw/anki-pending/` if under repo.

---

## Files modified / created

| Path | Action |
|--|--|
| `<HOME>/.agents/zeroclaw/src/**` | PATCH — Phase 1 hook (exact file from Phase 0) |
| `<HOME>/.zeroclaw/config.toml` | PATCH — add `anki_dispatcher_enabled` flag |
| `workspace/skills/anki-cards/lookup.py` | REWRITE — multi-sense |
| `workspace/skills/anki-cards/ankiconnect.py` | PATCH — multi-card add, Disambiguation field |
| `workspace/skills/anki-cards/dispatcher.py` | NEW |
| `workspace/skills/anki-cards/SKILL.md` | REWRITE — new flow |
| `workspace/AGENTS.md` | PATCH — Anki section |
| `~/.zeroclaw/anki-pending/` | NEW DIR — runtime state |

---

## Non-goals

- No new LLM prompts. All logic deterministic Python.
- No changes to AnkiWeb sync path.
- No changes to Docker/headless-anki setup.
- No new fields beyond `Disambiguation`.
- No support for languages other than English in Anki input (regex is ASCII-only by design).

---

## Risks & mitigations

| Risk | Mitigation |
|--|--|
| Phase 0 finds no clean hook point in zeroclaw Rust | STOP, surface to user, discuss refactor vs A2 fallback |
| Cambridge HTML changes break `.pos-block` selector | Free Dictionary API fallback already wired; print warning on selector miss |
| User spams previews without confirming → pending state bloat | 10-min TTL + single-file-per-chat overwrite |
| Retroactive disambiguation races with user reviewing | Sync is post-add; if user is mid-review, they see old label until next sync. Acceptable. |
| Existing 6 cards break after model field add | `modelFieldAdd` is idempotent; test on one card first |

---

## Definition of done

- User sends `New Anki Cards: pace` → sees 4-sense preview in English within 5 s.
- User replies `pace 1,2;` → 2 cards added, labels `(speed)` and `(step)` visible on Recognition template only.
- User sends `Fix Anki: pace — sense 3` via old path still works (backward compat for existing `Fix Anki` command, if kept).
- LLM path untouched for non-Anki messages.
- All 10 tests in Phase 5 pass.
- Existing 6 cards still function; no visible regression.
