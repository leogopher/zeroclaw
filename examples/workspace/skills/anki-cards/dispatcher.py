#!/usr/bin/env python3
"""Deterministic Anki dispatcher for Telegram messages.

Invoked by the zeroclaw Telegram channel BEFORE the LLM sees the message.
Writes its reply to stdout; the caller forwards it to Telegram verbatim.

Subcommands:
  preview <chat_id> <message_text>   Parse terms, look up senses, emit preview,
                                      write pending file.
  confirm <chat_id> <reply_text>     Parse sense-picks reply, add picked cards,
                                      emit confirmation.
  cancel  <chat_id> [<text>]         Drop pending preview.

State directory: ~/.zeroclaw/anki-pending/<chat_id>.json (TTL = PENDING_TTL_SEC).
All output is English (per workspace/AGENTS.md).
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import lookup as lookup_mod  # noqa: E402
import ankiconnect as ank  # noqa: E402
from cloze import cloze  # noqa: E402

PENDING_DIR = Path.home() / ".zeroclaw" / "anki-pending"
PENDING_TTL_SEC = 10 * 60

TRIGGER_PREFIX_RE = re.compile(
    r"(?is)^\s*(new\s+anki\s+cards?|anki\s+cards?|add\s+to\s+anki)\s*:?\s*",
)
ITEM_PREFIX_RE = re.compile(r"^\s*\d+\s*[\.\)\-:]\s*")


# ─── Term parsing ───────────────────────────────────────────────────────────

def parse_terms(message_text: str) -> list[str]:
    """Strip the trigger prefix and split the remainder into a list of terms.

    Handles:
      - "New Anki Cards: pace; trait"
      - "Anki Cards\n1) albeit\n2) hit the sack"
      - "Add to Anki: serendipity"
    Order is preserved, duplicates collapsed.
    """
    body = TRIGGER_PREFIX_RE.sub("", message_text, count=1)
    pieces: list[str] = []
    for line in body.splitlines():
        for chunk in line.split(";"):
            chunk = ITEM_PREFIX_RE.sub("", chunk).strip()
            chunk = chunk.strip(",.:- ")
            if chunk:
                pieces.append(chunk)

    seen: set[str] = set()
    out: list[str] = []
    for p in pieces:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ─── Pending-state management ───────────────────────────────────────────────

def _pending_path(chat_id: str) -> Path:
    return PENDING_DIR / f"{chat_id}.json"


def _purge_expired_pending() -> None:
    if not PENDING_DIR.exists():
        return
    cutoff = time.time() - PENDING_TTL_SEC
    for p in PENDING_DIR.glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def _write_pending(chat_id: str, payload: dict) -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    _pending_path(chat_id).write_text(json.dumps(payload, ensure_ascii=False))


def _read_pending(chat_id: str) -> dict | None:
    p = _pending_path(chat_id)
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > PENDING_TTL_SEC:
        try:
            p.unlink()
        except OSError:
            pass
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _drop_pending(chat_id: str) -> bool:
    p = _pending_path(chat_id)
    if p.exists():
        try:
            p.unlink()
            return True
        except OSError:
            return False
    return False


# ─── Meaning normalization ──────────────────────────────────────────────────

def _normalize_meaning(m: str) -> str:
    m = (m or "").strip()
    # Collapse Cambridge's extra spaces before punctuation.
    m = re.sub(r"\s+([,.;:!?])", r"\1", m)
    m = re.sub(r"\s+", " ", m)
    return m


def _normalize_example(ex: str | None) -> str:
    ex = (ex or "").strip()
    ex = re.sub(r"\s+([,.;:!?])", r"\1", ex)
    ex = re.sub(r"\s+", " ", ex)
    return ex


# ─── Preview subcommand ─────────────────────────────────────────────────────

def _lookup_with_flags(term: str) -> dict:
    data = lookup_mod.lookup(term)
    try:
        existing_ids = ank.find(term)
    except Exception:
        existing_ids = []

    existing_meanings: set[str] = set()
    if existing_ids:
        try:
            notes = ank.invoke("notesInfo", notes=existing_ids)
        except Exception:
            notes = []
        for n in notes or []:
            fields = n.get("fields") or {}
            meaning = ((fields.get("Meaning") or {}).get("value") or "").strip().lower()
            if meaning:
                existing_meanings.add(meaning)

    existing_sense_indices: list[int] = []
    for idx, sense in enumerate(data.get("senses", [])):
        m = _normalize_meaning(sense.get("meaning") or "").lower()
        if m and m in existing_meanings:
            existing_sense_indices.append(idx)
    data["existing_sense_indices"] = existing_sense_indices
    return data


def _format_preview(chat_id: str, terms_data: list[dict]) -> str:
    lines: list[str] = []
    lines.append("🗂 Preview — reply to add")
    lines.append("")
    usable = 0
    for t_idx, d in enumerate(terms_data, start=1):
        term = d["term"]
        ipa = d.get("ipa_us") or ""
        senses = d.get("senses") or []
        header = f"{t_idx}. {term}"
        if ipa:
            header += f" /{ipa}/"
        if not d.get("audio_url"):
            header += " ⚠️ no audio"
        lines.append(header)

        if not senses:
            lines.append("   ⚠️ no senses found — skipped")
            lines.append("")
            continue

        usable += 1
        existing = set(d.get("existing_sense_indices") or [])
        for s_idx, s in enumerate(senses, start=1):
            pos = s.get("pos") or "?"
            meaning = _normalize_meaning(s.get("meaning") or "")
            example = _normalize_example(s.get("example") or "")
            suffix = "  ↺ Already in deck" if (s_idx - 1) in existing else ""
            lines.append(f"   ({s_idx}) [{pos}] {meaning}{suffix}")
            if example:
                lines.append(f"       _{example}_")
        lines.append("")

    if usable == 0:
        lines.append("Nothing to add — no senses found for any term.")
        return "\n".join(lines).rstrip()

    usable_terms = [d["term"] for d in terms_data if d.get("senses")]
    if len(usable_terms) >= 2:
        hint = f"`{usable_terms[0]} 1,3; {usable_terms[1]} 1;`"
    else:
        hint = f"`{usable_terms[0]} 1;`  (or `{usable_terms[0]} 1,2;` for multiple senses)"
    lines.append(f"Reply like: {hint}")
    lines.append("Or `cancel` to drop.")
    return "\n".join(lines).rstrip()


def cmd_preview(chat_id: str, message_text: str) -> int:
    _purge_expired_pending()
    terms = parse_terms(message_text)
    if not terms:
        print("⚠️ No terms parsed from your message. Example: `New Anki Cards: pace; trait`.")
        return 0

    terms_data: list[dict] = []
    for term in terms:
        try:
            data = _lookup_with_flags(term)
        except Exception as e:
            data = {
                "term": term,
                "ipa_us": None,
                "audio_url": None,
                "source": "none",
                "senses": [],
                "partial": True,
                "existing_sense_indices": [],
                "lookup_error": str(e),
            }
        terms_data.append(data)

    # Persist pending state even when everything was "already in deck" — user
    # may re-pick a duplicate to force-add.
    _write_pending(chat_id, {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "terms": terms_data,
    })

    print(_format_preview(chat_id, terms_data))
    return 0


# ─── Confirm subcommand ─────────────────────────────────────────────────────

REPLY_ITEM_RE = re.compile(
    r"(?i)^\s*(?P<term>[a-z][a-z \-]*?)\s+(?P<ids>\d+(?:\s*,\s*\d+)*)\s*;?\s*$",
)


def parse_reply(reply_text: str) -> dict[str, list[int]]:
    """Parse `pace 1,3; trait 1;` into `{"pace": [1, 3], "trait": [1]}`.

    Raises ValueError on malformed input. Keys are lowercased; values are the
    ONE-based sense numbers as the user typed them.
    """
    out: dict[str, list[int]] = {}
    pieces = [p.strip() for p in reply_text.split(";") if p.strip()]
    if not pieces:
        raise ValueError("no picks in reply")
    for piece in pieces:
        m = REPLY_ITEM_RE.match(piece)
        if not m:
            raise ValueError(f"can't parse: {piece!r}")
        term = m.group("term").strip().lower()
        ids = [int(x) for x in re.split(r"\s*,\s*", m.group("ids")) if x]
        if not ids:
            raise ValueError(f"no sense numbers for {term!r}")
        if term in out:
            out[term].extend(ids)
        else:
            out[term] = ids
    return out


def _build_entry(term: str, sense: dict, top: dict) -> dict:
    meaning = _normalize_meaning(sense.get("meaning") or "")
    example = _normalize_example(sense.get("example") or "")
    try:
        example_cloze = cloze(term, example) if example else ""
    except Exception:
        example_cloze = example
    return {
        "word": term,
        "label": sense.get("label") or "",
        "meaning": meaning,
        "ipa": top.get("ipa_us") or "",
        "example": example,
        "example_cloze": example_cloze,
        "audio_url": top.get("audio_url") or "",
    }


def cmd_confirm(chat_id: str, reply_text: str) -> int:
    pending = _read_pending(chat_id)
    if pending is None:
        print('⚠️ No pending preview (or expired). Send "New Anki Cards: ..." to start over.')
        return 0

    try:
        picks = parse_reply(reply_text)
    except ValueError as e:
        print(f"⚠️ Couldn't parse your reply: {e}. Use format like `pace 1,3; trait 1;`.")
        return 0

    terms_by_key = {d["term"].lower(): d for d in pending.get("terms", [])}

    entries: list[dict] = []
    labels: list[tuple[str, str]] = []       # (term, label) for status line
    skipped: list[tuple[str, str]] = []      # (term, reason)
    errors: list[str] = []

    for term_lc, ids in picks.items():
        term_data = terms_by_key.get(term_lc)
        if not term_data:
            errors.append(f"unknown term in reply: {term_lc!r}")
            continue
        senses = term_data.get("senses") or []
        existing = set(term_data.get("existing_sense_indices") or [])
        if not senses:
            errors.append(f"no senses available for {term_lc!r}")
            continue
        for one_based in ids:
            if one_based < 1 or one_based > len(senses):
                errors.append(
                    f"{term_lc} sense {one_based} out of range (1..{len(senses)})"
                )
                continue
            zero_idx = one_based - 1
            sense = senses[zero_idx]
            # Plan §3 step 5: skip already-in-deck unless user explicitly
            # re-picked them — which they just did. Log the re-add as a note.
            if zero_idx in existing:
                skipped.append(
                    (term_data["term"], f"sense {one_based} already in deck — forcing add")
                )
            entries.append(_build_entry(term_data["term"], sense, term_data))
            labels.append((term_data["term"], sense.get("label") or ""))

    if errors:
        joined = "; ".join(errors)
        print(f"⚠️ {joined}. Nothing added.")
        return 0
    if not entries:
        print("⚠️ Nothing to add.")
        return 0

    try:
        add_result = ank.add_entries(entries)
    except Exception as e:
        print(f"⚠️ Anki add failed: {e}")
        return 1

    _drop_pending(chat_id)

    added_count = add_result.get("added", len(entries))
    sync_status = add_result.get("sync", "unknown")

    lines: list[str] = []
    noun = "card" if added_count == 1 else "cards"
    lines.append(f"✅ Added {added_count} {noun}:")
    for term, label in labels:
        if label:
            lines.append(f" • {term} ({label})")
        else:
            lines.append(f" • {term}")

    if skipped:
        lines.append("")
        lines.append("↺ Note:")
        for term, reason in skipped:
            lines.append(f" • {term} — {reason}")

    if sync_status != "ok":
        lines.append("")
        lines.append(f"⚠️ sync {sync_status}")

    print("\n".join(lines))
    return 0


# ─── Cancel subcommand ──────────────────────────────────────────────────────

def cmd_cancel(chat_id: str, _text: str = "") -> int:
    if _drop_pending(chat_id):
        print("❌ Cancelled.")
    else:
        print("❌ Nothing pending to cancel.")
    return 0


# ─── Entry point ────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) < 3:
        print("usage: dispatcher.py {preview|confirm|cancel} <chat_id> [text]", file=sys.stderr)
        return 2
    sub = sys.argv[1]
    chat_id = sys.argv[2]
    text = sys.argv[3] if len(sys.argv) > 3 else ""
    try:
        if sub == "preview":
            return cmd_preview(chat_id, text)
        if sub == "confirm":
            return cmd_confirm(chat_id, text)
        if sub == "cancel":
            return cmd_cancel(chat_id, text)
        print(f"unknown subcommand: {sub}", file=sys.stderr)
        return 2
    except Exception as e:
        # Top-level crash: print English error so the user sees something.
        sys.stderr.write(f"dispatcher crash: {e}\n")
        print("⚠️ Anki dispatcher error — see logs.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
