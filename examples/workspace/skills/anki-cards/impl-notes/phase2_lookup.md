# Phase 2 — Multi-sense lookup.py

**Status:** complete, tested on seven words.

## Output schema (NDJSON per term)

```json
{
  "term": "pace",
  "ipa_us": "peɪs",
  "audio_url": "https://...",
  "source": "cambridge",
  "partial": false,
  "senses": [
    {"pos": "noun", "meaning": "...", "example": "...", "label": "speed"},
    ...
  ]
}
```

- Up to `MAX_SENSES = 5` senses per term.
- `source` ∈ `{"cambridge", "freedict", "none"}`.
- `partial: true` only when `senses` is empty.

## Cache

- Dir: `~/.zeroclaw/cache/anki/` (unchanged).
- Filename: `v2_<slug>.json` (`CACHE_PREFIX = "v2_"`). Old single-sense entries (`<slug>.json`) are ignored and age out naturally.
- TTL: 30 days.

## Label extraction

`label_candidates(meaning, term)` returns up to 4 ranked tokens from the first
120 chars of a definition — stopwords, the term itself, and anything ≤1 char
are dropped. `pick_unique_label(candidates, used)` picks the first unused
candidate and falls back to `<top>N` suffix if all candidates collide. Fallback
to `sense1..N` if a meaning has no usable tokens.

Observed behavior on the 6 existing deck words + `pace` + `bank`:

| Term | Labels |
|--|--|
| pace | speed, moving, progressing, make, ability |
| trait | characterist, personality, organism |
| cheerful | happy, describe, positive, pleasant |
| stubborn | determined, difficult, opposed, hard |
| bank | organization, gambling, sloping, pile, row |
| curious | interested, strange, unusual |
| rebellious | group, difficult, having |

Quality is heuristic — good enough for UX disambiguation, not semantic.

## Cambridge selectors

- IPA: `.us.dpron-i .ipa` → `.us .ipa` → `.uk.dpron-i .ipa` → `.uk .ipa`.
- Audio: `.us.dpron-i source[type="audio/mpeg"]` → broader fallbacks.
- Senses: walk every `.pos-block` / `.entry-body__el`; inside, iterate `.def-block` (canonical Cambridge leaf) and pull `.def.ddef_d.db` + `.dexamp/.examp/.eg`.
- Dedup by normalized-meaning prefix so the `.def-block ⊃ .ddef_block` nesting doesn't yield duplicate senses (earlier iteration had this bug).

## Free Dictionary API fallback

Same schema, capped at 3 senses total (across all POS blocks). Source: `"freedict"`.

## Backward compat

`ankiconnect.py add_notes()` still expects per-entry shape `{term, meaning, ipa, example, example_cloze, audio_url}` — that is NOT what `lookup.py` produces directly. The dispatcher (Phase 3) is responsible for the term→entry transformation: one lookup result → N entries, one per user-selected sense.
