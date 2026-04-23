#!/usr/bin/env python3
"""AnkiConnect client + deck/model bootstrap + card operations.

Subcommands:
  bootstrap               Ensure deck + model exist and are migrated to the
                          current schema. Idempotent.
  add <json-file>         Add notes from JSON array of entries (see add_entries).
  update <term> <field> <value>
                          Update a field of the note whose Word == term.
                          If multiple notes match the term, all are updated.
  find <term>             Print note IDs whose Word == term.
  ping                    Health check.

Reads ANKI_CONNECT_URL env (default http://127.0.0.1:8765).
Prints JSON to stdout.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import requests

ANKI_URL = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
DECK_NAME = "English::Vocabulary"
MODEL_NAME = "ZeroClaw English 3-Card"
FIELDS = ["Word", "Meaning", "IPA", "Example", "ExampleCloze", "Audio", "Disambiguation"]

CARD_CSS = """
.card { font-family: -apple-system, system-ui, sans-serif; font-size: 22px;
        text-align: center; color: #222; background: #fafafa; padding: 24px; }
.word { font-size: 32px; font-weight: 600; }
.disambig { color: #888; font-size: 20px; font-weight: 400; margin-left: 4px; }
.ipa  { color: #888; font-size: 18px; margin-top: 6px; }
.meaning { margin-top: 14px; }
.example { font-style: italic; color: #555; margin-top: 16px; font-size: 18px; }
.cloze { font-style: italic; color: #555; font-size: 20px; }
.blank { border-bottom: 2px solid #888; display: inline-block; min-width: 60px; }
"""

# Card 1 (Recognition) front shows the word + audio. When multiple notes share
# the same Word, a `Disambiguation` label is rendered in muted text to
# distinguish them (e.g. `pace (speed)` vs `pace (step)`).
CARD1_FRONT = (
    '<div class="word">{{Word}}'
    '{{#Disambiguation}}<span class="disambig">({{Disambiguation}})</span>{{/Disambiguation}}'
    '</div>{{Audio}}'
)
CARD1_BACK = (
    '{{FrontSide}}<hr id="answer">'
    '<div class="ipa">/{{IPA}}/</div>'
    '<div class="meaning">{{Meaning}}</div>'
    '<div class="example">{{Example}}</div>'
)
CARD2_FRONT = (
    '<div class="meaning">{{Meaning}}</div>'
    '<div class="cloze">{{ExampleCloze}}</div>'
)
CARD2_BACK = (
    '{{FrontSide}}<hr id="answer">'
    '<div class="word">{{Word}}</div>'
    '<div class="ipa">/{{IPA}}/</div>{{Audio}}'
)
CARD3_FRONT = '{{Audio}}'
CARD3_BACK = (
    '{{FrontSide}}<hr id="answer">'
    '<div class="word">{{Word}}</div>'
    '<div class="ipa">/{{IPA}}/</div>'
    '<div class="meaning">{{Meaning}}</div>'
)

TEMPLATES = [
    {"Name": "1 Recognition", "Front": CARD1_FRONT, "Back": CARD1_BACK},
    {"Name": "2 Production", "Front": CARD2_FRONT, "Back": CARD2_BACK},
    {"Name": "3 Listening", "Front": CARD3_FRONT, "Back": CARD3_BACK},
]


def invoke(action: str, **params):
    payload = {"action": action, "version": 6, "params": params}
    r = requests.post(ANKI_URL, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"AnkiConnect {action}: {data['error']}")
    return data.get("result")


def ensure_deck() -> None:
    decks = invoke("deckNames")
    if DECK_NAME not in decks:
        invoke("createDeck", deck=DECK_NAME)


def ensure_model() -> None:
    models = invoke("modelNames")
    if MODEL_NAME not in models:
        invoke(
            "createModel",
            modelName=MODEL_NAME,
            inOrderFields=FIELDS,
            css=CARD_CSS,
            cardTemplates=TEMPLATES,
        )
        return

    # Model exists — make sure the schema matches current expectations.
    # Idempotent: missing field is added, Card 1 template is refreshed to
    # include the `{{Disambiguation}}` conditional.
    current_fields = invoke("modelFieldNames", modelName=MODEL_NAME) or []
    if "Disambiguation" not in current_fields:
        invoke("modelFieldAdd", modelName=MODEL_NAME, fieldName="Disambiguation", index=len(current_fields))

    try:
        current_templates = invoke("modelTemplates", modelName=MODEL_NAME) or {}
    except Exception:
        current_templates = {}
    desired = {
        "1 Recognition": {"Front": CARD1_FRONT, "Back": CARD1_BACK},
        "2 Production": {"Front": CARD2_FRONT, "Back": CARD2_BACK},
        "3 Listening": {"Front": CARD3_FRONT, "Back": CARD3_BACK},
    }
    needs_update = False
    for name, want in desired.items():
        have = current_templates.get(name) or {}
        if have.get("Front") != want["Front"] or have.get("Back") != want["Back"]:
            needs_update = True
            break
    if needs_update:
        invoke("updateModelTemplates", model={"name": MODEL_NAME, "templates": desired})

    # Only touch styling when it actually differs — writes to the model bump
    # the collection schema timestamp on Anki's side, which forces AnkiWeb to
    # demand a full sync on the next pull.
    try:
        current_css = invoke("modelStyling", modelName=MODEL_NAME) or {}
        current_css_text = current_css.get("css") if isinstance(current_css, dict) else current_css
    except Exception:
        current_css_text = None
    if current_css_text != CARD_CSS:
        try:
            invoke("updateModelStyling", model={"name": MODEL_NAME, "css": CARD_CSS})
        except Exception:
            pass


def bootstrap() -> dict:
    ensure_deck()
    ensure_model()
    return {"deck": DECK_NAME, "model": MODEL_NAME, "ok": True}


def _store_audio(term: str, url: str) -> str:
    """Download audio via AnkiConnect's storeMediaFile (it fetches the URL server-side)."""
    safe = "".join(c if c.isalnum() else "_" for c in term.lower())
    filename = f"zc_{safe}.mp3"
    invoke("storeMediaFile", filename=filename, url=url)
    return filename


def add_notes(items: list[dict]) -> dict:
    """Legacy single-card-per-term shim.

    Each item: `{term, meaning, ipa, example, example_cloze, audio_url}`.
    Converts to the new per-entry shape and delegates to `add_entries`.
    """
    entries = []
    for it in items:
        entries.append({
            "word": it["term"],
            "label": "",
            "meaning": it.get("meaning") or "",
            "ipa": it.get("ipa") or "",
            "example": it.get("example") or "",
            "example_cloze": it.get("example_cloze") or "",
            "audio_url": it.get("audio_url") or "",
        })
    return add_entries(entries)


def add_entries(entries: list[dict]) -> dict:
    """Add one note per entry. Multiple entries with the same `word` produce
    multiple notes (AnkiConnect `allowDuplicate: true`). After all adds, for
    every affected word, refresh the `Disambiguation` field on every matching
    note so Card 1 shows `word (label)` when the deck holds >1 note for that
    word, and a bare `word` when it holds exactly one.

    Entry schema:
      {word, label, meaning, ipa, example, example_cloze, audio_url}
    """
    bootstrap()
    notes: list[dict] = []
    audio_status: dict[str, str] = {}

    for e in entries:
        word = e["word"]
        label = e.get("label") or ""
        audio_field = ""
        if e.get("audio_url"):
            # Share one audio file per word — different senses of "pace" all
            # use /pace.mp3. Key the cache by word, not word+label.
            key = word
            if audio_status.get(key) != "ok":
                try:
                    fname = _store_audio(word, e["audio_url"])
                    audio_field = f"[sound:{fname}]"
                    audio_status[key] = "ok"
                except Exception as exc:
                    audio_status[key] = f"failed: {exc}"
            else:
                safe = "".join(c if c.isalnum() else "_" for c in word.lower())
                audio_field = f"[sound:zc_{safe}.mp3]"
        else:
            audio_status.setdefault(word, "missing")

        notes.append({
            "deckName": DECK_NAME,
            "modelName": MODEL_NAME,
            "fields": {
                "Word": word,
                "Meaning": e.get("meaning") or "",
                "IPA": e.get("ipa") or "",
                "Example": e.get("example") or "",
                "ExampleCloze": e.get("example_cloze") or "",
                "Audio": audio_field,
                # Filled in by _refresh_disambiguation below once we know how
                # many notes share this word.
                "Disambiguation": "",
            },
            "tags": ["zeroclaw", "english"],
            "options": {"allowDuplicate": True},
        })

    ids = invoke("addNotes", notes=notes)

    # AnkiConnect returns null for notes it refused to add (e.g. empty word).
    # Track which slots got real ids, pair them with their label + word so we
    # can write the Disambiguation value below.
    added: list[tuple[int, str, str]] = []  # (note_id, word, label)
    for nid, e in zip(ids, entries):
        if nid:
            added.append((nid, e["word"], e.get("label") or ""))

    # Refresh disambiguation for every word that got at least one new note —
    # plus any word those new notes share a slot with.
    affected_words = {w for _, w, _ in added}
    for word in affected_words:
        _refresh_disambiguation(word, added)

    sync_status = "ok"
    try:
        invoke("sync")
    except Exception as e:
        sync_status = f"pending: {e}"

    return {
        "note_ids": ids,
        "added": sum(1 for nid in ids if nid),
        "audio": audio_status,
        "count": len(ids),
        "sync": sync_status,
    }


def _refresh_disambiguation(word: str, just_added: list[tuple[int, str, str]]) -> None:
    """Ensure every note for `word` has a correct Disambiguation field.

    If the deck has ≥2 notes for this word, each note gets its own label.
    If exactly 1, Disambiguation is cleared (in case a prior sibling was
    deleted and we need to undo the `(label)` hint).

    Labels for freshly-added notes come from the `just_added` list (more
    reliable than scraping them back from Anki). For pre-existing notes we
    derive a label from the Meaning field when possible, else leave the
    existing Disambiguation value untouched.
    """
    ids = find(word)
    if not ids:
        return

    just_map = {nid: label for nid, w, label in just_added if w == word}

    if len(ids) <= 1:
        only_id = ids[0]
        invoke("updateNoteFields", note={"id": only_id, "fields": {"Disambiguation": ""}})
        return

    try:
        info = invoke("notesInfo", notes=ids) or []
    except Exception:
        info = []

    for note in info:
        nid = note.get("noteId")
        if nid is None:
            continue
        fields = note.get("fields") or {}
        current = ((fields.get("Disambiguation") or {}).get("value") or "").strip()
        if nid in just_map:
            new_label = just_map[nid]
        elif current:
            # Preserve any label the user previously set.
            continue
        else:
            meaning = ((fields.get("Meaning") or {}).get("value") or "")
            new_label = _fallback_label(meaning, word)

        if new_label != current:
            invoke("updateNoteFields", note={"id": nid, "fields": {"Disambiguation": new_label}})


def _fallback_label(meaning: str, word: str) -> str:
    """Reuse lookup.py's label extractor so stopwords stay in one place.

    Falls back to a stripped first-token heuristic if the import fails (e.g.
    ankiconnect is used standalone without lookup.py on PYTHONPATH).
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _here = str(_Path(__file__).resolve().parent)
        if _here not in _sys.path:
            _sys.path.insert(0, _here)
        from lookup import label_candidates as _cands  # type: ignore
        cands = _cands(meaning, word)
        return cands[0] if cands else ""
    except Exception:
        pass
    import re as _re
    m = (meaning or "").strip().lower()
    for tok in _re.split(r"[^a-z0-9\-]+", m):
        tok = tok.strip("-")
        if len(tok) < 3 or tok == word.lower():
            continue
        return tok[:12]
    return ""


def find(term: str) -> list[int]:
    query = f'deck:"{DECK_NAME}" Word:"{term}"'
    return invoke("findNotes", query=query)


def update(term: str, field: str, value: str) -> dict:
    ids = find(term)
    if not ids:
        return {"ok": False, "error": f"no note found for {term!r}"}
    for nid in ids:
        invoke("updateNoteFields", note={"id": nid, "fields": {field: value}})
    sync_status = "ok"
    try:
        invoke("sync")
    except Exception as e:
        sync_status = f"pending: {e}"
    return {"ok": True, "updated": ids, "field": field, "sync": sync_status}


def ping() -> dict:
    v = invoke("version")
    return {"ok": True, "ankiconnect_version": v}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    try:
        if cmd == "ping":
            out = ping()
        elif cmd == "bootstrap":
            out = bootstrap()
        elif cmd == "add":
            items = json.loads(Path(sys.argv[2]).read_text())
            # Detect new per-entry shape (`word`) vs legacy per-term shape (`term`).
            if items and isinstance(items[0], dict) and "word" in items[0]:
                out = add_entries(items)
            else:
                out = add_notes(items)
        elif cmd == "update":
            _, _, term, field, value = sys.argv[:5]
            out = update(term, field, value)
        elif cmd == "find":
            out = {"note_ids": find(sys.argv[2])}
        else:
            print(f"unknown command: {cmd}", file=sys.stderr)
            return 2
    except Exception as e:
        out = {"ok": False, "error": str(e)}
        print(json.dumps(out, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
