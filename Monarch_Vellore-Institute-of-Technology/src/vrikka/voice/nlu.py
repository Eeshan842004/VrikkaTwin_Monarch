"""Text check-in understanding (§23.5; Part 7): medicine brand recognition with fuzzy matching, so "combiflam",
"combiflem" or "Combi flam" all read back as ibuprofen + paracetamol. Symptoms and red flags are parsed by
whatif/red_flags.parse_text. No live speech recognition runs in the hosted app; a typed or ASHA-entered text is used.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz, process

from vrikka.config import load_yaml

MIN_SCORE = 85        # fuzzy-match acceptance (0-100); below this the word is not treated as a brand


def recognise_brands(text: str, min_score: int = MIN_SCORE) -> list[dict]:
    """Brands mentioned in free text -> [{"brand", "generics", "classes", "score", "heard"}], generic names first."""
    brands = load_yaml("drugs_india")["brands"]
    names = list(brands)
    words = re.findall(r"[a-zA-Z][a-zA-Z_\-]*", text.lower())
    # two-word grams first ("combi flam" -> "combiflam", "telma h" -> "telma_h"), then single words
    grams = [((i, i + 1), a + "_" + b, a + b) for i, (a, b) in enumerate(zip(words, words[1:], strict=False))]
    grams += [((i,), w, w) for i, w in enumerate(words)]
    found: dict[str, dict] = {}
    used: set[int] = set()
    for idx, joined, plain in grams:
        if used & set(idx) or len(plain) < 4:
            continue
        best = None
        for cand in {joined.replace("-", "_"), plain}:
            hit = process.extractOne(cand, names, scorer=fuzz.ratio)
            if hit and hit[1] >= min_score and (best is None or hit[1] > best[1]):
                best = hit
        if best is None:
            continue
        used |= set(idx)
        b = brands[best[0]]
        cls = b["class"] if isinstance(b["class"], list) else [b["class"]]
        if best[0] not in found or best[1] > found[best[0]]["score"]:
            found[best[0]] = {"brand": best[0], "generics": list(b["generics"]), "classes": cls,
                              "score": round(float(best[1]), 1), "heard": " ".join(words[i] for i in idx)}
    return sorted(found.values(), key=lambda d: -d["score"])
