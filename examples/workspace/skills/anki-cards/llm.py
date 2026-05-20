#!/usr/bin/env python3
"""Z.ai LLM helper for the anki-cards skill.

Used for two things:
  1. classify_terms()   — split a mixed list into "word" vs "phrase" buckets
                          so the dispatcher knows which lookup path to take.
  2. generate_phrase()  — produce IPA / meaning / example for a phrase that
                          Cambridge has no entry for.

The API key is read from ~/.zeroclaw/config.toml (the same key the Rust
daemon's `zai` model route uses). ZAI_API_KEY in the env overrides.
"""
from __future__ import annotations
import json
import os
import re
import threading
import tomllib
from pathlib import Path

import requests

CONFIG_PATH = Path.home() / ".zeroclaw" / "config.toml"
# Z.ai GLM Coding Plan endpoint — same base the Rust daemon's `zai` provider
# alias resolves to (see ZAI_GLOBAL_BASE_URL in zeroclaw-providers/src/lib.rs).
# The bare `/api/paas/v4` path goes to the pay-as-you-go account, which has a
# separate, empty balance.
ZAI_ENDPOINT = "https://api.z.ai/api/coding/paas/v4/chat/completions"
ZAI_MODEL = os.environ.get("ZEROCLAW_ZAI_MODEL", "glm-5")
TIMEOUT_SEC = 30

# Z.ai's free tier 429s under concurrent load. Cap simultaneous chat() calls
# so a 16-phrase batch doesn't fan out into 16 parallel rejected requests.
_CHAT_CONCURRENCY = int(os.environ.get("ZEROCLAW_ZAI_CONCURRENCY", "2"))
_chat_semaphore = threading.Semaphore(_CHAT_CONCURRENCY)

_cached_key: str | None = None


def _api_key() -> str:
    global _cached_key
    env = os.environ.get("ZAI_API_KEY")
    if env:
        return env
    if _cached_key:
        return _cached_key
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"config not found: {CONFIG_PATH}")
    data = tomllib.loads(CONFIG_PATH.read_text())
    for route in data.get("model_routes") or []:
        if route.get("provider") == "zai" and route.get("api_key"):
            _cached_key = route["api_key"]
            return _cached_key
    top_key = (data.get("api_key") or "").strip()
    if top_key and not top_key.startswith("enc"):
        _cached_key = top_key
        return _cached_key
    raise RuntimeError("no zai api_key in config (looked at [[model_routes]] with provider=zai)")


def chat(system: str, user: str, temperature: float = 0.2) -> str:
    import time
    payload = {
        "model": ZAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    # Retry 429 / 5xx with exponential backoff. Anything else is fatal.
    # Hold the semaphore for the duration of the (possibly retrying) call so
    # backoff actually staggers — releasing between retries would let the
    # next waiter pile straight back in.
    last_err: Exception | None = None
    with _chat_semaphore:
        for attempt in range(5):
            try:
                r = requests.post(ZAI_ENDPOINT, json=payload, headers=headers, timeout=TIMEOUT_SEC)
            except requests.RequestException as e:
                last_err = e
                time.sleep(1.5 * (2 ** attempt))
                continue
            if r.status_code == 429 or 500 <= r.status_code < 600:
                last_err = RuntimeError(f"Z.ai HTTP {r.status_code}: {r.text[:200]}")
                # Honor Retry-After if present, else exponential backoff.
                wait = float(r.headers.get("Retry-After") or 0) or 1.5 * (2 ** attempt)
                time.sleep(min(wait, 20))
                continue
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
    raise last_err or RuntimeError("Z.ai chat: exhausted retries")


def _parse_json_loose(text: str):
    """Pull the first JSON object/array out of a possibly-fenced LLM reply."""
    if not text:
        raise ValueError("empty LLM response")
    m = re.search(r"```(?:json)?\s*([\{\[].*?[\}\]])\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = None
    for i, c in enumerate(text):
        if c in "{[":
            start = i
            break
    if start is None:
        raise ValueError(f"no JSON found in: {text[:200]}")
    snippet = text[start:].strip()
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        depth = 0
        opener = snippet[0]
        closer = "}" if opener == "{" else "]"
        for i, c in enumerate(snippet):
            if c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(snippet[: i + 1])
        raise


def classify_terms(terms: list[str]) -> dict[str, str]:
    """Return {term_lower -> "word"|"phrase"} for each input.

    Falls back to "phrase if contains a space else word" on any error.
    """
    if not terms:
        return {}
    fallback = {t.lower(): ("phrase" if " " in t else "word") for t in terms}
    system = (
        "You classify English-learner vocabulary inputs. "
        'For each input return "word" (single dictionary headword, including '
        'hyphenated words) or "phrase" (any multi-word expression: collocation, '
        "idiom, phrasal verb, set phrase, preposition-anchored chunk like "
        '"fond of" or "fed up with"). '
        "Reply with strict JSON: a single object whose keys are the input "
        'terms verbatim and whose values are "word" or "phrase". '
        "No prose, no markdown, no commentary."
    )
    user = "Classify these terms:\n" + json.dumps(terms, ensure_ascii=False)
    try:
        raw = chat(system, user, temperature=0)
        parsed = _parse_json_loose(raw)
        if not isinstance(parsed, dict):
            raise ValueError("expected object")
        out: dict[str, str] = {}
        # Match case-insensitively in case the LLM normalized keys.
        lc_map = {k.lower(): v for k, v in parsed.items() if isinstance(k, str)}
        for t in terms:
            v = lc_map.get(t.lower())
            if v not in ("word", "phrase"):
                v = fallback[t.lower()]
            out[t.lower()] = v
        return out
    except Exception:
        return fallback


def generate_phrase(phrase: str) -> dict:
    """Generate a single-sense definition for a phrase Cambridge doesn't index.

    Returns the same shape lookup.lookup() produces:
      {ipa_us, audio_url, source, senses: [{pos, meaning, example, label}]}
    """
    system = (
        "You define English phrases for a learner's flashcard. "
        "Given ONE phrase, return strict JSON with EXACTLY these keys: "
        '"ipa_us" (US-accent IPA transcription of the whole phrase, no '
        "surrounding slashes), "
        '"meaning" (one short learner-friendly definition, no surrounding quotes), '
        '"example" (one natural example sentence that uses the phrase verbatim '
        "or with a small inflection). "
        "No markdown, no prose, no extra keys."
    )
    raw = chat(system, f"Phrase: {phrase}", temperature=0.2)
    parsed = _parse_json_loose(raw)
    if not isinstance(parsed, dict):
        raise ValueError("expected object")
    ipa = (parsed.get("ipa_us") or "").strip().strip("/") or None
    meaning = (parsed.get("meaning") or "").strip()
    example = (parsed.get("example") or "").strip()
    if not meaning:
        raise ValueError("LLM returned empty meaning")
    return {
        "ipa_us": ipa,
        "audio_url": None,
        "source": "llm",
        "senses": [{
            "pos": "phrase",
            "meaning": meaning,
            "example": example,
            "label": "",
        }],
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: llm.py {classify <t1> <t2>... | phrase <phrase>}", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "classify":
        print(json.dumps(classify_terms(sys.argv[2:]), ensure_ascii=False, indent=2))
    elif cmd == "phrase":
        print(json.dumps(generate_phrase(" ".join(sys.argv[2:])), ensure_ascii=False, indent=2))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)
