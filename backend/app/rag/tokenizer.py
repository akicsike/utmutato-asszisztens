"""BM25 tokenizáló magyar használati útmutatókhoz (a demo tokenizer.py-ja alapján).

A dense (bge-m3) keresés a jelentést fogja meg, a BM25 a PONTOS egyezéseket: típusszámok (SMV41D10EU,
DR890, S85), hibakódok (E15, F3), menüpontok, gomb- és alkatrésznevek. Ezért:
  - a szavak ékezet nélkül ÉS magyar szótővel is bekerülnek ("vízkőtelenítést" -> "vizkotelenitest",
    "vízkőtelenítés"), így a ragozott és az ékezet nélkül beírt kérdés is egyezik;
  - a betű+szám alakok (típusszám, hibakód) egészben ÉS részeikre bontva is tokenek;
  - a töltelékszavak (a, az, és, hogyan, the …) kimaradnak.
A dokumentumokat és a lekérdezéseket UGYANEZ a függvény tokenizálja.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import snowballstemmer

TOKENIZER_VERSION = "2"

# Igekötők leválasztása + igenév -> főnév: így a "feltölteni" és a "töltéséhez" közös tokent kap ("toltes").
# A prompt-mérésben a DJI töltés-kérdés emiatt nem találta meg a "Töltés" fejezetet (a szótövező szerint
# feltölteni -> "feltölten", töltéséhez -> "töltés": nincs közös token).
_PREVERBS = ("vissza", "össze", "hozzá", "szét", "bele", "fel", "meg", "át", "rá", "ki", "be", "le", "el")
_PREVERB_REST_MIN = 5

# Típusszám / hibakód: betű és szám vegyesen (SMV41D10EU, DR890, E15, VS-900)
_MODEL_CODE = re.compile(r"\b(?=[a-z0-9\-]*\d)(?=[a-z0-9\-]*[a-z])[a-z0-9]+(?:-[a-z0-9]+)*\b")
_WORD = re.compile(r"[0-9a-záéíóöőúüűäß]+(?:[-/][0-9a-záéíóöőúüűäß]+)*")

_STOPWORDS = {
    # magyar
    "a", "az", "és", "es", "egy", "is", "meg", "vagy", "van", "kell", "nem", "hogy", "ha", "de", "valamint",
    "illetve", "ill", "pl", "stb", "által", "altal", "ez", "azt", "ezt", "mint", "már", "mar", "csak", "még",
    "be", "ki", "le", "fel", "el", "itt", "ott", "nincs", "vannak", "hogyan", "mit", "mi", "mire", "miért",
    "miert", "melyik", "milyen", "hol", "mikor", "kell", "lehet", "tudom", "tudok", "szeretném", "szeretnem",
    "kérem", "kerem", "nekem", "ezzel", "azzal", "akkor", "után", "utan", "alatt", "mellett", "minden",
    # angol
    "the", "and", "of", "to", "in", "for", "on", "with", "is", "are", "be", "by", "or", "an", "this", "that",
}
_STEM_MIN_LEN = 4
_stemmer = snowballstemmer.stemmer("hungarian")


def fold_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@lru_cache(maxsize=300_000)
def _word_forms(word: str) -> tuple[str, ...]:
    """Ékezet nélküli alak + szótő(k). Az eredeti alak is marad, mert a szótövező néha túl sokat vág."""
    folded = fold_accents(word)
    if len(word) < _STEM_MIN_LEN or word.isdigit():
        return (folded,)
    stem = _stemmer.stemWord(word)
    # főnévi igenév -> cselekvést jelentő főnév: "tölteni" (tő: tölten) ~ "töltés", "tisztítani" ~ "tisztítás"
    if len(stem) >= 6 and stem.endswith(("an", "en")):
        stem_noun = stem[:-2] + ("ás" if stem.endswith("an") else "és")
    else:
        stem_noun = None
    stems = (fold_accents(stem), _stemmer.stemWord(folded), fold_accents(stem_noun) if stem_noun else "")
    forms = [folded, *(s for s in stems if len(s) >= 3)]
    for pv in _PREVERBS:
        rest = word[len(pv):]
        if word.startswith(pv) and len(rest) >= _PREVERB_REST_MIN:
            forms.extend(_word_forms(rest))
            break
    return tuple(dict.fromkeys(forms))


def tokenize(text: str) -> list[str]:
    """Szöveg -> BM25 tokenek (ismétlődéssel, a tf számításhoz)."""
    if not text:
        return []
    t = unicodedata.normalize("NFC", text).lower()
    tokens: list[str] = []
    for m in _MODEL_CODE.finditer(t):
        code = fold_accents(m.group(0))
        tokens.append(code.replace("-", ""))
        if "-" in code:
            tokens.extend(p for p in code.split("-") if len(p) >= 2)
    for m in _WORD.finditer(t):
        word = m.group(0)
        if _MODEL_CODE.fullmatch(word):
            continue
        for p in dict.fromkeys(re.split(r"[-/]", word)):
            if len(p) < 2 or p in _STOPWORDS or fold_accents(p) in _STOPWORDS:
                continue
            tokens.extend(_word_forms(p))
    return tokens
