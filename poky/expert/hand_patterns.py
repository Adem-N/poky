"""
Parser de patterns de mains de poker en shorthand standard.

Grammaire :
  Pairs:
    "AA"         -> {AA}
    "22+"        -> {22, 33, ..., AA}
    "JJ+"        -> {JJ, QQ, KK, AA}
    "TT-77"      -> {77, 88, 99, TT}

  Suited (sX = même couleur) :
    "AKs"        -> {AKs}
    "A2s+"       -> {A2s, A3s, ..., AKs}        (high card = A, kicker >= 2)
    "K9s+"       -> {K9s, KTs, KJs, KQs}        (high card = K, kicker >= 9)
    "76s-54s"    -> {54s, 65s, 76s}             (gappers connectés)

  Offsuit (oX = couleurs différentes) :
    "AKo"        -> {AKo}
    "AJo+"       -> {AJo, AQo, AKo}
    "K9o+"       -> {K9o, KTo, KJo, KQo}

  Combos littéraux :
    "AKs,AKo,AQs" -> ensemble explicite

Le résultat est toujours un set d'IDs canoniques (0..168) issus de
`poky.abstraction.preflop`.

Le parser ignore les espaces blancs et accepte des listes
séparées par virgule. Une erreur de syntaxe lève ValueError.

Pourquoi : le format JSON natural-language reste lisible par un humain
qui connaît le poker, et chaque pattern se développe en sa liste exacte
de combos via canonical_class().
"""
from typing import Iterable, Set

from poky.abstraction.preflop import canonical_class


_RANKS = "23456789TJQKA"
_RANK_TO_VAL = {r: i for i, r in enumerate(_RANKS, start=2)}  # 2..14
_VAL_TO_RANK = {v: r for r, v in _RANK_TO_VAL.items()}


def _hand_to_class_id(high: int, low: int, suited: bool) -> int:
    """Convertit (rank_high, rank_low, suited) en class_id via deux cartes
    représentatives. Utilise des couleurs arbitraires (H/D) pour matcher
    canonical_class().
    """
    rh = _VAL_TO_RANK[high]
    rl = _VAL_TO_RANK[low]
    if high == low:
        # paire — deux suits différents
        return canonical_class("H" + rh, "D" + rl)
    if suited:
        return canonical_class("H" + rh, "H" + rl)
    return canonical_class("H" + rh, "D" + rl)


def _parse_single(token: str) -> Set[int]:
    """Parse un seul pattern (sans virgule). Retourne un set de class_ids."""
    t = token.strip()
    if not t:
        return set()

    # Cas 1 : range "X-Y" (ex "TT-77", "76s-54s", "AJo+")
    if "-" in t:
        left, right = t.split("-", 1)
        return _parse_range_pair(left.strip(), right.strip())

    # Cas 2 : pattern avec "+" (ex "22+", "A2s+", "AJo+")
    if t.endswith("+"):
        return _parse_plus(t[:-1].strip())

    # Cas 3 : combo unique (ex "AA", "AKs", "AKo")
    return _parse_atom(t)


def _parse_atom(t: str) -> Set[int]:
    """Parse un combo unique sans modificateur : 'AA', 'AKs', 'AKo'."""
    if len(t) == 2:
        # paire (ex "AA", "TT")
        r = t[0].upper()
        if t[0] != t[1] or r not in _RANK_TO_VAL:
            raise ValueError(f"Pattern invalide : {t!r}")
        v = _RANK_TO_VAL[r]
        return {_hand_to_class_id(v, v, False)}

    if len(t) == 3:
        r1, r2, sf = t[0].upper(), t[1].upper(), t[2].lower()
        if r1 not in _RANK_TO_VAL or r2 not in _RANK_TO_VAL:
            raise ValueError(f"Pattern invalide : {t!r}")
        if sf not in ("s", "o"):
            raise ValueError(f"Suffixe doit être 's' ou 'o' : {t!r}")
        v1, v2 = _RANK_TO_VAL[r1], _RANK_TO_VAL[r2]
        if v1 == v2:
            raise ValueError(f"Une paire n'a pas de suffixe s/o : {t!r}")
        high, low = max(v1, v2), min(v1, v2)
        return {_hand_to_class_id(high, low, sf == "s")}

    raise ValueError(f"Pattern atomique non reconnu : {t!r}")


def _parse_plus(base: str) -> Set[int]:
    """Parse un pattern avec '+'. Sémantique standard du poker :

    - 'XX+' (paire) : depuis XX jusqu'à AA
    - 'XYs+' / 'XYo+' (high card fixée) : kicker varie de Y à (X-1)
      ex 'A2s+' -> A2s, A3s, ..., AKs
      ex 'K9o+' -> K9o, KTo, KJo, KQo
    """
    if len(base) == 2:
        # paire
        if base[0] != base[1]:
            raise ValueError(f"Pattern '+' sur non-paire mal formé : {base!r}")
        r = base[0].upper()
        if r not in _RANK_TO_VAL:
            raise ValueError(f"Rang invalide : {base!r}")
        v = _RANK_TO_VAL[r]
        return {_hand_to_class_id(x, x, False) for x in range(v, 15)}

    if len(base) == 3:
        r1, r2, sf = base[0].upper(), base[1].upper(), base[2].lower()
        if r1 not in _RANK_TO_VAL or r2 not in _RANK_TO_VAL:
            raise ValueError(f"Rang invalide : {base!r}")
        if sf not in ("s", "o"):
            raise ValueError(f"Suffixe doit être 's' ou 'o' : {base!r}")
        v1, v2 = _RANK_TO_VAL[r1], _RANK_TO_VAL[r2]
        # On exige v1 > v2 (high card fixée, kicker varie vers le haut)
        if v1 <= v2:
            raise ValueError(
                f"Pattern '+' nécessite high card en premier : {base!r}"
            )
        # kicker varie de v2 à v1-1
        return {
            _hand_to_class_id(v1, k, sf == "s")
            for k in range(v2, v1)
        }

    raise ValueError(f"Pattern '+' non reconnu : {base!r}")


def _parse_range_pair(left: str, right: str) -> Set[int]:
    """Parse 'LEFT-RIGHT' : LEFT est la borne haute, RIGHT la borne basse.

    - 'TT-77'   : paires de 77 à TT
    - '76s-54s' : connecteurs suited, gap fixe (1)
    - 'A5s-A2s' : kicker varie, high card fixée
    - 'KQo-KTo' : idem
    """
    # Si les deux sont des paires
    if len(left) == 2 and left[0] == left[1] and len(right) == 2 and right[0] == right[1]:
        rh = left[0].upper()
        rl = right[0].upper()
        if rh not in _RANK_TO_VAL or rl not in _RANK_TO_VAL:
            raise ValueError(f"Rang invalide : {left}-{right}")
        vh, vl = _RANK_TO_VAL[rh], _RANK_TO_VAL[rl]
        if vh < vl:
            vh, vl = vl, vh
        return {_hand_to_class_id(x, x, False) for x in range(vl, vh + 1)}

    # Sinon les deux doivent être de la même "famille" (s ou o) et de
    # même high card OU de même gap (connecteurs).
    if len(left) != 3 or len(right) != 3:
        raise ValueError(f"Range malformée : {left}-{right}")
    if left[2].lower() != right[2].lower():
        raise ValueError(f"Suffixes incohérents : {left}-{right}")
    sf = left[2].lower()
    if sf not in ("s", "o"):
        raise ValueError(f"Suffixe doit être 's' ou 'o' : {left}-{right}")

    lh = _RANK_TO_VAL[left[0].upper()]
    ll = _RANK_TO_VAL[left[1].upper()]
    rh = _RANK_TO_VAL[right[0].upper()]
    rl = _RANK_TO_VAL[right[1].upper()]
    if lh <= ll or rh <= rl:
        raise ValueError(
            f"High card doit être en premier : {left}-{right}"
        )

    # Cas A : même high card, kicker varie (ex 'A5s-A2s')
    if lh == rh:
        lo_kicker, hi_kicker = sorted((ll, rl))
        return {
            _hand_to_class_id(lh, k, sf == "s")
            for k in range(lo_kicker, hi_kicker + 1)
        }

    # Cas B : connecteurs / gappers, gap fixe (ex '76s-54s')
    gap_l = lh - ll
    gap_r = rh - rl
    if gap_l != gap_r:
        raise ValueError(
            f"Gap inconsistant entre {left} et {right} : "
            f"{gap_l} vs {gap_r}"
        )
    lo_high, hi_high = sorted((lh, rh))
    return {
        _hand_to_class_id(h, h - gap_l, sf == "s")
        for h in range(lo_high, hi_high + 1)
    }


def parse_pattern(pattern: str) -> Set[int]:
    """Parse un pattern (potentiellement multi-token séparé par virgules).

    Exemples :
      parse_pattern("22+")            -> tous les paires
      parse_pattern("A2s+,AKo,QJs")   -> union
    """
    if not isinstance(pattern, str):
        raise TypeError(f"pattern doit être une string, pas {type(pattern)}")
    out: Set[int] = set()
    for token in pattern.split(","):
        token = token.strip()
        if not token:
            continue
        out |= _parse_single(token)
    return out


def parse_patterns(patterns: Iterable[str]) -> Set[int]:
    """Union de plusieurs patterns."""
    out: Set[int] = set()
    for p in patterns:
        out |= parse_pattern(p)
    return out
