#!/usr/bin/env python3
"""Blank out the target word/phrase in an example sentence, inflection-aware.

Usage: cloze.py <term> <example>
Prints the blanked sentence to stdout.

For single words we match any token starting with the stem (3+ chars shared),
so run/runs/running/ran are caught for "run", study/studies/studied for "study".
For multi-word phrases we replace the whole phrase case-insensitively, allowing
each word to have a small suffix (s, ed, ing, etc.).
"""
from __future__ import annotations
import re
import sys

BLANK = "_____"

# Top irregular English verbs — past / past participle forms that don't follow rules.
IRREGULAR = {
    "be": ["am", "is", "are", "was", "were", "been", "being"],
    "have": ["has", "had", "having"],
    "do": ["does", "did", "done", "doing"],
    "go": ["goes", "went", "gone", "going"],
    "say": ["says", "said", "saying"],
    "get": ["gets", "got", "gotten", "getting"],
    "make": ["makes", "made", "making"],
    "know": ["knows", "knew", "known", "knowing"],
    "take": ["takes", "took", "taken", "taking"],
    "see": ["sees", "saw", "seen", "seeing"],
    "come": ["comes", "came", "coming"],
    "think": ["thinks", "thought", "thinking"],
    "give": ["gives", "gave", "given", "giving"],
    "find": ["finds", "found", "finding"],
    "tell": ["tells", "told", "telling"],
    "run": ["runs", "ran", "running"],
    "eat": ["eats", "ate", "eaten", "eating"],
    "write": ["writes", "wrote", "written", "writing"],
    "read": ["reads", "read", "reading"],
    "begin": ["begins", "began", "begun", "beginning"],
    "break": ["breaks", "broke", "broken", "breaking"],
    "bring": ["brings", "brought", "bringing"],
    "buy": ["buys", "bought", "buying"],
    "catch": ["catches", "caught", "catching"],
    "choose": ["chooses", "chose", "chosen", "choosing"],
    "drive": ["drives", "drove", "driven", "driving"],
    "fall": ["falls", "fell", "fallen", "falling"],
    "feel": ["feels", "felt", "feeling"],
    "fight": ["fights", "fought", "fighting"],
    "forget": ["forgets", "forgot", "forgotten", "forgetting"],
    "hit": ["hits", "hit", "hitting"],
    "hold": ["holds", "held", "holding"],
    "keep": ["keeps", "kept", "keeping"],
    "leave": ["leaves", "left", "leaving"],
    "lose": ["loses", "lost", "losing"],
    "meet": ["meets", "met", "meeting"],
    "pay": ["pays", "paid", "paying"],
    "put": ["puts", "put", "putting"],
    "send": ["sends", "sent", "sending"],
    "sit": ["sits", "sat", "sitting"],
    "sleep": ["sleeps", "slept", "sleeping"],
    "speak": ["speaks", "spoke", "spoken", "speaking"],
    "spend": ["spends", "spent", "spending"],
    "stand": ["stands", "stood", "standing"],
    "teach": ["teaches", "taught", "teaching"],
    "understand": ["understands", "understood", "understanding"],
    "win": ["wins", "won", "winning"],
}


def _regular_forms(word: str) -> list[str]:
    """Generate plausible regular inflections for a base word."""
    w = word.lower()
    if not w.isalpha():
        return [w]
    forms = {w}
    # plurals / 3rd person
    if w.endswith("y") and len(w) > 2 and w[-2] not in "aeiou":
        forms.add(w[:-1] + "ies")
        forms.add(w[:-1] + "ied")
    elif w.endswith(("s", "x", "z", "ch", "sh")):
        forms.add(w + "es")
    else:
        forms.add(w + "s")
    # -ing / -ed
    if w.endswith("e") and len(w) > 2:
        forms.add(w[:-1] + "ing")
        forms.add(w + "d")
    else:
        forms.add(w + "ing")
        forms.add(w + "ed")
    return sorted(forms, key=len, reverse=True)


def _all_forms(word: str) -> list[str]:
    w = word.lower()
    forms = set(_regular_forms(w))
    if w in IRREGULAR:
        forms.update(IRREGULAR[w])
        forms.add(w)
    # reverse lookup — if someone gave us an inflected form as the term
    for base, inflections in IRREGULAR.items():
        if w in inflections:
            forms.add(base)
            forms.update(inflections)
    return sorted(forms, key=len, reverse=True)


def _word_pattern(word: str) -> str:
    forms = _all_forms(word)
    alt = "|".join(re.escape(f) for f in forms)
    return rf"\b(?:{alt})\b"


def cloze(term: str, sentence: str) -> str:
    if not sentence:
        return ""
    term = term.strip()
    words = term.split()
    if len(words) == 1:
        pattern = _word_pattern(words[0])
        return re.sub(pattern, BLANK, sentence, flags=re.IGNORECASE)
    # multi-word: match each with small inflection tolerance, preserving order
    parts = [_word_pattern(w) if w.isalpha() else re.escape(w) for w in words]
    pattern = r"\s+".join(parts)
    replaced = re.sub(pattern, BLANK, sentence, flags=re.IGNORECASE)
    if replaced == sentence:
        # fallback: plain literal, case-insensitive
        replaced = re.sub(re.escape(term), BLANK, sentence, flags=re.IGNORECASE)
    return replaced


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: cloze.py <term> <example>", file=sys.stderr)
        return 2
    print(cloze(sys.argv[1], sys.argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
