# Phase 4 — Multi-card add + Disambiguation field

**Status:** complete, model migrated on live Anki, existing 10 notes backfilled with empty Disambiguation.

## Model migration

`ensure_model()` is now migration-aware (idempotent):
1. If model doesn't exist → create with full schema (7 fields, 3 templates).
2. If exists → `modelFieldAdd` the `Disambiguation` field if missing, `updateModelTemplates` if the Card 1 front differs from the current spec, `updateModelStyling` to refresh the CSS (adds `.disambig` rule).

On the live Pi: ran `ankiconnect.py bootstrap` — `modelFieldNames` now returns `[Word, Meaning, IPA, Example, ExampleCloze, Audio, Disambiguation]`. All 10 existing notes have `Disambiguation=""`; because the template uses Mustache `{{#Disambiguation}}...{{/Disambiguation}}`, the `(label)` hint is hidden when the field is empty — so existing cards render identically.

## Card 1 template

```html
<div class="word">{{Word}}{{#Disambiguation}}<span class="disambig">({{Disambiguation}})</span>{{/Disambiguation}}</div>{{Audio}}
```

`.disambig` CSS: muted grey, 20px, normal weight — reads as a quiet clarifier, not a fight for attention with the headword.

Cards 2 (Production) and 3 (Listening) are unchanged.

## add_entries(entries)

New per-entry API. Entry schema:
```json
{"word": "pace", "label": "speed",
 "meaning": "...", "ipa": "peɪs",
 "example": "...", "example_cloze": "...",
 "audio_url": "..."}
```

- Multiple entries with the same `word` produce multiple notes (`allowDuplicate: true`).
- Audio: one file per word (e.g. `zc_pace.mp3`) — downloaded once, referenced by every sense of that word. Avoids N copies of the same MP3 for N senses.
- Post-processes every affected word via `_refresh_disambiguation(word, just_added)`:
  - If deck has ≥2 notes for the word → every note gets a label in its Disambiguation field.
  - If deck has exactly 1 → Disambiguation is cleared (to recover from deletions).
  - Freshly-added notes use the label from the dispatcher's request.
  - Pre-existing notes with a non-empty Disambiguation are preserved.
  - Pre-existing notes with empty Disambiguation get a `_fallback_label(meaning, word)` — a copy of the stopword+truncate logic from `lookup.py` that avoids importing that module.

## add_notes(items) shim

Old shape `{term, meaning, ipa, example, example_cloze, audio_url}` still works — converted to entries with empty label, then delegated to `add_entries`. Disambiguation refresh still runs; if a single legacy call produces ≥2 notes for the same word, they get labels derived from Meaning.

## CLI

`ankiconnect.py add <json-file>` auto-detects shape: array entries with a `word` key → `add_entries`; with a `term` key → legacy `add_notes`.
