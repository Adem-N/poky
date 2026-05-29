"""
Détection du contexte préflop à partir d'une Observation.

Convertit l'état de jeu en un `scenario_key` + `table_size` + `position`
utilisables pour interroger les ranges expertes.

La détection est conservative : si la situation est ambiguë (multi-way
post-3-bet, stack effective != 100bb, sizing exotique), on retourne None
et le caller bascule sur Tier 2.

Conventions de label de position :
  - HU (2 joueurs)   : "BTN", "BB"   (le BTN est aussi la SB)
  - 3-max            : "BTN", "SB", "BB"
  - 6-max            : "UTG", "HJ", "CO", "BTN", "SB", "BB"

Convention rlcard HU : le dealer poste la BB et agit en SECOND préflop ;
le non-dealer poste la SB et agit en PREMIER. C'est l'inverse de la
convention "BTN agit en premier en HU" classique au poker — d'où le
mapping des labels HU [BB, BTN] dans _POS_LABELS.

Scenarios produits :
  - "rfi:<pos>"                      first-in raise (aucune action volontaire avant moi)
  - "vs_open:<hero>|<opener>"        hero face à un seul raiser
  - "vs_3bet:<hero>|<three_bettor>"  hero (qui a ouvert) face à 3-bet
  - "vs_4bet:<hero>|<four_bettor>"   hero (qui a 3-bet) face à 4-bet
"""
from typing import List, Optional, Tuple

from poky.engine import Observation, Stage


# Tables de mapping offset_from_btn -> label par taille de table.
# Voir docstring du module pour la convention HU rlcard (inversée).
_POS_LABELS = {
    2: ["BB", "BTN"],
    3: ["BTN", "SB", "BB"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
}


def table_size_label(num_players: int) -> Optional[str]:
    """Retourne le label de table_size attendu dans les JSON ('HU', '3max', '6max')."""
    return {2: "HU", 3: "3max", 6: "6max"}.get(num_players)


def position_label(num_players: int, offset_from_btn: int) -> Optional[str]:
    """Label de position pour le scenario_key."""
    labels = _POS_LABELS.get(num_players)
    if not labels:
        return None
    if not (0 <= offset_from_btn < len(labels)):
        return None
    return labels[offset_from_btn]


def _initial_blind_chips(obs: Observation) -> int:
    """Chips que hero a obligatoirement engagés avant toute action volontaire.

    HU : dealer = BB (big_blind), non-dealer = SB (small_blind).
    3-max+ : BTN (offset 0) = 0, SB (offset 1) = small_blind,
             BB (offset 2) = big_blind, autres positions = 0.
    """
    return _initial_blind_for_offset(
        obs.num_players, obs.offset_from_btn, obs.small_blind, obs.big_blind
    )


def _initial_blind_for_offset(num_players: int, offset: int,
                              sb: int, bb: int) -> int:
    """Variante générique : utile pour calculer les voluntary commits
    des autres joueurs (pas seulement hero)."""
    if num_players == 2:
        return bb if offset == 0 else sb
    if offset == 0:
        return 0
    if offset == 1:
        return sb
    if offset == 2:
        return bb
    return 0


def _find_first_limper(obs: Observation) -> Optional[int]:
    """En 3-max+, identifie le premier limper non-hero.

    Un limper = joueur qui a commit voluntairement (committed > initial_blind)
    mais sans raiser (committed <= BB). En convention rlcard, ça veut dire
    qu'il a CHECK_CALL la BB. Le BB lui-même n'est jamais un "limper" : on
    ignore les blinds non-voluntary.

    Retourne l'index du limper avec le offset le plus bas (premier à parler)
    parmi les non-hero. None si aucun limper.

    Limites : ne distingue pas BTN-limp+SB-limp (les deux apparaîtront
    voluntaires) — on prend juste le premier dans l'ordre des offsets.
    """
    n = obs.num_players
    bb = obs.big_blind
    sb = obs.small_blind
    candidates: List[Tuple[int, int]] = []   # (offset, player_idx)
    for i, c in enumerate(obs.all_committed):
        if i == obs.player_id:
            continue
        off_i = (i - obs.dealer_id) % n
        initial = _initial_blind_for_offset(n, off_i, sb, bb)
        if c > initial + 0.01 and c <= bb + 0.01:
            candidates.append((off_i, i))
    if not candidates:
        return None
    # Ordre d'action préflop en 3-max+ : UTG (off 3), HJ (off 4), CO (off 5),
    # BTN (off 0), SB (off 1), BB (off 2). On cycle pour mettre les actors
    # tardifs (offsets 3,4,5) avant les early (0,1,2) dans le tri.
    def action_order_key(off: int) -> int:
        # offsets 3,4,5 viennent d'abord (UTG/HJ/CO), puis 0,1 (BTN, SB).
        # BB (offset 2) ne peut pas être limper (il n'a rien volontaire à
        # ce stade — le BB qui "check sa propre BB" est le post-flop).
        return off if off < 3 else off - 6
    candidates.sort(key=lambda c: action_order_key(c[0]))
    return candidates[0][1]


def detect_context(obs: Observation) -> Optional[Tuple[str, str, str]]:
    """Retourne (table_size, scenario_key, hero_pos) ou None si non supporté.

    Logique : on classifie l'état préflop par combinaison de :
      - hero a-t-il déjà engagé des chips au-delà de sa blind initiale ?
        (= a-t-il volontairement raise) ;
      - quelle est la mise courante maximale ?

    Cela évite la fragilité des brackets "bet en bb" qui ne distinguent
    pas un open de 2bb d'un 3-bet de 2.5bb (sizings de la 5-action
    abstraction de rlcard).
    """
    if obs.stage != Stage.PREFLOP:
        return None

    ts = table_size_label(obs.num_players)
    if ts is None:
        return None
    bb = obs.big_blind
    if bb <= 0:
        return None

    hero_pos = position_label(obs.num_players, obs.offset_from_btn)
    if hero_pos is None:
        return None

    bet_bb = max(obs.all_committed) / bb
    if bet_bb > 35.0:
        # 5-bet jam / all-in territory — pas de range Tier 1, laisse au heuristic.
        return None

    initial_blind = _initial_blind_chips(obs)
    hero_voluntary = obs.my_committed > initial_blind + 0.01
    max_bet = max(obs.all_committed)
    # "Quelqu'un a raise" = mise max > BB (au-dessus des seules blindes).
    someone_raised = max_bet > bb + 0.01

    # Cas 1 : aucune raise volontaire au-dessus de la BB. Deux sous-cas :
    # (a) hero est first-to-act (RFI) → rfi:<pos>
    # (b) hero acts after someone has called the BB (limp) → vs_limp:<hero>|<opener>
    # En HU spécifiquement : si hero est BB et personne n'a raise, ça
    # signifie nécessairement que SB a limpé (sinon BB n'a pas à agir).
    if not someone_raised and not hero_voluntary:
        if obs.num_players == 2 and hero_pos == "BB":
            return ts, "vs_limp:BB|BTN", hero_pos
        # 3-max+ : détecte un limper non-hero. Si présent → vs_limp ;
        # sinon → rfi (premier à parler, pas de limp avant nous).
        limper_idx = _find_first_limper(obs)
        if limper_idx is not None:
            limper_off = (limper_idx - obs.dealer_id) % obs.num_players
            limper_pos = position_label(obs.num_players, limper_off)
            if limper_pos is not None:
                return ts, f"vs_limp:{hero_pos}|{limper_pos}", hero_pos
        return ts, f"rfi:{hero_pos}", hero_pos

    # Au-delà, il faut un aggressor distinct de hero pour avoir un scenario "vs_X"
    if not someone_raised:
        return None
    aggressor_idx = _find_aggressor(obs)
    if aggressor_idx is None or aggressor_idx == obs.player_id:
        return None
    aggressor_offset = (aggressor_idx - obs.dealer_id) % obs.num_players
    aggressor_pos = position_label(obs.num_players, aggressor_offset)
    if aggressor_pos is None:
        return None

    # Cas 2 : hero n'a pas encore raise volontairement → c'est UN raise contre lui
    if not hero_voluntary:
        return ts, f"vs_open:{hero_pos}|{aggressor_pos}", hero_pos

    # Cas 3 : hero a déjà raise. On déduit la profondeur (3-bet vs 4-bet).
    #
    # En HU c'est déterministe via la position : seul le SB/BTN peut
    # opener (il agit en premier), donc :
    #   - HU BTN voluntary → BTN a opened → opp = BB 3-bet → vs_3bet
    #   - HU BB voluntary  → BB a 3-bet (BTN avait opened) → opp = BTN 4-bet → vs_4bet
    # En 3-max+ on retombe sur le bracket par bb committed.
    if obs.num_players == 2:
        if hero_pos == "BTN":
            return ts, f"vs_3bet:{hero_pos}|{aggressor_pos}", hero_pos
        # hero_pos == "BB"
        return ts, f"vs_4bet:{hero_pos}|{aggressor_pos}", hero_pos

    hero_bet_bb = obs.my_committed / bb
    if hero_bet_bb <= 4.5:
        return ts, f"vs_3bet:{hero_pos}|{aggressor_pos}", hero_pos
    if hero_bet_bb <= 12.0:
        return ts, f"vs_4bet:{hero_pos}|{aggressor_pos}", hero_pos
    return None


def _find_aggressor(obs: Observation) -> Optional[int]:
    """Index du joueur qui a la mise courante la plus élevée (unique)."""
    max_bet = max(obs.all_committed)
    holders = [i for i, c in enumerate(obs.all_committed) if c == max_bet]
    if len(holders) != 1:
        return None
    return holders[0]
