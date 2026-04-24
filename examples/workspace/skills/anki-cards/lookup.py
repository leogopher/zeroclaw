#!/usr/bin/env python3
"""Look up English words/phrases for Anki card generation (multi-sense).

Usage: lookup.py <term> [<term> ...]
Prints one JSON object per line (NDJSON) with keys:
  term, ipa_us, audio_url, source, partial, senses

Each sense is: {pos, meaning, example, label}
source ∈ {"cambridge", "freedict", "none"}
partial=True if no senses were found for the term.
"""
from __future__ import annotations
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

CACHE_DIR = Path.home() / ".zeroclaw" / "cache" / "anki"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SEC = 30 * 24 * 3600
CACHE_PREFIX = "v2_"
MAX_SENSES = 5

UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36"
CAMBRIDGE_BASE = "https://dictionary.cambridge.org/dictionary/english/"
CAMBRIDGE_MEDIA_BASE = "https://dictionary.cambridge.org"
FREEDICT_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en/"

LABEL_STOPWORDS = {
    "of", "at", "which", "that", "when", "where", "while", "who", "whom", "whose",
    "someone", "something", "somebody", "person", "people", "place", "thing", "things",
    "used", "way", "kind", "sort", "type", "piece", "part", "particular", "specific",
    "certain", "like",
    "is", "are", "was", "were", "be", "been", "being", "am", "has", "have", "had",
    "for", "with", "from", "on", "in", "into", "onto", "by", "as", "about", "to", "off", "out",
    "up", "down", "over", "under",
    "and", "or", "but", "not", "no", "only", "also", "such", "esp", "especially",
    "you", "your", "he", "she", "it", "they", "them", "their", "his", "her", "its",
    "the", "an", "this", "these", "those", "there", "here", "if", "so", "very",
    "any", "all", "some", "each", "every", "more", "most", "less",
}
LABEL_PREFIXES = ("to be ", "to ", "the ", "a ", "an ")


def _slug(term: str) -> str:
    s = term.strip().lower()
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _cache_path(term: str) -> Path:
    return CACHE_DIR / f"{CACHE_PREFIX}{_slug(term)}.json"


def _cache_get(term: str):
    p = _cache_path(term)
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > CACHE_TTL_SEC:
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _cache_put(term: str, data: dict) -> None:
    _cache_path(term).write_text(json.dumps(data, ensure_ascii=False))


def label_candidates(meaning: str, term: str = "") -> list[str]:
    """Return ranked label candidates for a definition string.

    First choice is the first non-stopword token of the cleaned meaning.
    Subsequent choices are later non-stopword tokens — used to break ties when
    multiple senses of the same term produce the same top candidate.
    Each candidate is lowercased and truncated to 12 chars.
    """
    if not meaning:
        return []
    m = meaning.strip()[:120].lower()
    for p in LABEL_PREFIXES:
        if m.startswith(p):
            m = m[len(p):]
            break
    term_lc = term.strip().lower() if term else ""
    out: list[str] = []
    for tok in re.split(r"[^a-z0-9\-]+", m):
        tok = tok.strip("-")
        if not tok or tok in LABEL_STOPWORDS or len(tok) < 2:
            continue
        if term_lc and tok == term_lc:
            continue
        trimmed = tok[:12]
        if trimmed not in out:
            out.append(trimmed)
        if len(out) >= 4:
            break
    return out


def pick_unique_label(candidates: list[str], used: set[str]) -> str:
    """Pick the first unused candidate. Falls back to candidate+N on exhaustion."""
    for c in candidates:
        if c not in used:
            return c
    if not candidates:
        return ""
    base = candidates[0]
    n = 2
    while f"{base}{n}" in used:
        n += 1
    return f"{base}{n}"


def _clean_meaning(text: str) -> str:
    t = text.strip().rstrip(":").strip()
    # Strip leading register labels like "(infml)", "[UK]", etc.
    t = re.sub(r"^\s*[\(\[]\s*(infml|fml|UK|US|dated|approving|disapproving|slang)\s*[\)\]]\s*",
               "", t, flags=re.IGNORECASE)
    return t.strip()


def _fetch_cambridge(term: str) -> dict | None:
    url = CAMBRIDGE_BASE + quote(_slug(term))
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10, allow_redirects=True)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.text:
        return None
    soup = BeautifulSoup(r.text, "lxml")

    # IPA: prefer US, fallback to UK.
    ipa_el = (soup.select_one(".us.dpron-i .ipa")
              or soup.select_one(".us .ipa")
              or soup.select_one(".uk.dpron-i .ipa")
              or soup.select_one(".uk .ipa"))
    ipa = ipa_el.get_text(strip=True) if ipa_el else None

    # Audio: prefer US MP3.
    audio_el = (soup.select_one('.us.dpron-i source[type="audio/mpeg"]')
                or soup.select_one('.us source[type="audio/mpeg"]')
                or soup.select_one('source[type="audio/mpeg"]'))
    audio_url = None
    if audio_el and audio_el.get("src"):
        audio_url = CAMBRIDGE_MEDIA_BASE + audio_el["src"]

    senses: list[dict] = []
    seen_meanings: set[str] = set()

    def _push(pos_text: str, meaning: str, example: str | None):
        if not meaning or len(senses) >= MAX_SENSES:
            return
        key = re.sub(r"\s+", " ", meaning.lower())[:80]
        if key in seen_meanings:
            return
        seen_meanings.add(key)
        senses.append({
            "pos": pos_text,
            "meaning": meaning,
            "example": example,
            # Label is assigned after all senses are collected so we can pick
            # distinct labels per sense.
            "_candidates": label_candidates(meaning, term),
        })

    # Walk each POS block; within each, walk its def-blocks in document order.
    pos_blocks = soup.select(".pos-block, .entry-body__el")
    if not pos_blocks:
        pos_blocks = [soup]

    for pos_block in pos_blocks:
        if len(senses) >= MAX_SENSES:
            break
        pos_el = pos_block.select_one(".pos.dpos, .pos")
        pos_text = pos_el.get_text(strip=True) if pos_el else ""

        # `.def-block` is the canonical per-definition container on Cambridge.
        # Fall back to raw `.def` nodes if the page structure is unusual.
        def_blocks = pos_block.select(".def-block")
        if def_blocks:
            for db in def_blocks:
                if len(senses) >= MAX_SENSES:
                    break
                def_el = db.select_one(".def.ddef_d.db, .def")
                if def_el is None:
                    continue
                meaning = _clean_meaning(def_el.get_text(" ", strip=True))
                ex_el = db.select_one(".dexamp, .examp .eg, .examp, .eg")
                example = ex_el.get_text(" ", strip=True) if ex_el else None
                _push(pos_text, meaning, example)
        else:
            for def_el in pos_block.select(".def.ddef_d.db, .def"):
                if len(senses) >= MAX_SENSES:
                    break
                meaning = _clean_meaning(def_el.get_text(" ", strip=True))
                example = None
                parent = def_el.parent
                if parent is not None:
                    ex_el = parent.select_one(".dexamp, .examp .eg, .examp")
                    if ex_el:
                        example = ex_el.get_text(" ", strip=True)
                _push(pos_text, meaning, example)

    if not senses:
        return None

    # Assign unique labels (Card 1 disambiguation hint).
    used: set[str] = set()
    for idx, s in enumerate(senses):
        lbl = pick_unique_label(s.pop("_candidates"), used)
        if not lbl:
            lbl = f"sense{idx + 1}"
        used.add(lbl)
        s["label"] = lbl

    return {
        "ipa_us": ipa,
        "audio_url": audio_url,
        "source": "cambridge",
        "senses": senses,
    }


def _fetch_freedict(term: str) -> dict | None:
    url = FREEDICT_BASE + quote(term.strip())
    try:
        r = requests.get(url, timeout=10)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    if not isinstance(data, list) or not data:
        return None
    entry = data[0]

    ipa = None
    audio_url = None
    for ph in entry.get("phonetics", []):
        if ph.get("audio") and not audio_url:
            audio_url = ph["audio"]
            if ph.get("text") and not ipa:
                ipa = ph["text"].strip("/")
        if ph.get("text") and not ipa:
            ipa = ph["text"].strip("/")

    senses: list[dict] = []
    cap = min(MAX_SENSES, 3)
    for block in entry.get("meanings", []):
        pos = (block.get("partOfSpeech") or "").strip()
        for d in block.get("definitions", []):
            if len(senses) >= cap:
                break
            meaning = _clean_meaning(d.get("definition") or "")
            if not meaning:
                continue
            example = d.get("example")
            senses.append({
                "pos": pos,
                "meaning": meaning,
                "example": example,
                "_candidates": label_candidates(meaning, term),
            })
        if len(senses) >= cap:
            break

    if not senses:
        return None

    used: set[str] = set()
    for idx, s in enumerate(senses):
        lbl = pick_unique_label(s.pop("_candidates"), used)
        if not lbl:
            lbl = f"sense{idx + 1}"
        used.add(lbl)
        s["label"] = lbl

    return {
        "ipa_us": ipa,
        "audio_url": audio_url,
        "source": "freedict",
        "senses": senses,
    }


def lookup(term: str, use_cache: bool = True) -> dict:
    if use_cache:
        cached = _cache_get(term)
        if cached is not None:
            return cached

    result: dict = {
        "term": term,
        "ipa_us": None,
        "audio_url": None,
        "source": "none",
        "senses": [],
        "partial": True,
    }

    cam = _fetch_cambridge(term)
    if cam:
        result.update(cam)
        result["term"] = term

    # Fill gaps (IPA, audio, or senses) from Free Dictionary.
    if not result["senses"] or not result["ipa_us"] or not result["audio_url"]:
        fd = _fetch_freedict(term)
        if fd:
            if not result["senses"]:
                result["senses"] = fd["senses"]
                if result["source"] == "none":
                    result["source"] = fd["source"]
            if not result["ipa_us"] and fd.get("ipa_us"):
                result["ipa_us"] = fd["ipa_us"]
            if not result["audio_url"] and fd.get("audio_url"):
                result["audio_url"] = fd["audio_url"]

    result["partial"] = not bool(result["senses"])

    if result["senses"]:
        _cache_put(term, result)
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: lookup.py <term> [<term> ...]", file=sys.stderr)
        return 2
    for term in sys.argv[1:]:
        res = lookup(term)
        print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
