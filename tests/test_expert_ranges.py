"""Sanity tests pour le Tier 1 (ranges expertes préflop).

Vérifie :
  - Le parser de patterns décode les notations standard correctement
  - Les ranges HU 100bb chargent et compilent sans erreur
  - Des spots canoniques retournent les bonnes décisions :
      * AA toujours 3-bet+4-bet+5-bet jam
      * 72o toujours fold (sauf RFI BTN où c'est limite mais hors range)
      * AKs en BB vs open : mix raise/call
  - La détection de contexte distingue rfi/vs_open/vs_3bet/vs_4bet
"""
import pytest

from poky.abstraction.preflop import canonical_class, class_name
from poky.engine import Action, Observation, PlayerStatus, Stage
from poky.expert.context import detect_context
from poky.expert.hand_patterns import parse_pattern
from poky.expert.preflop_ranges import reload_book
from poky.expert.range_lookup import pro_preflop_strategy


# ============ HAND PATTERN PARSER ============

def test_parse_single_pair():
    ids = parse_pattern("AA")
    assert len(ids) == 1
    assert canonical_class("HA", "DA") in ids


def test_parse_pair_plus():
    ids = parse_pattern("22+")
    assert len(ids) == 13   # 22, 33, ..., AA


def test_parse_pair_range():
    ids = parse_pattern("TT-77")
    assert len(ids) == 4    # 77, 88, 99, TT
    assert canonical_class("HT", "DT") in ids
    assert canonical_class("H7", "D7") in ids
    assert canonical_class("H6", "D6") not in ids


def test_parse_suited_plus():
    ids = parse_pattern("A2s+")
    assert len(ids) == 12   # A2s, A3s, ..., AKs
    assert canonical_class("HA", "H2") in ids
    assert canonical_class("HA", "HK") in ids


def test_parse_offsuit_plus():
    ids = parse_pattern("K9o+")
    assert len(ids) == 4    # K9o, KTo, KJo, KQo


def test_parse_connector_range():
    ids = parse_pattern("76s-54s")
    assert len(ids) == 3
    # tous des suited connecteurs
    assert canonical_class("H7", "H6") in ids
    assert canonical_class("H6", "H5") in ids
    assert canonical_class("H5", "H4") in ids


def test_parse_multi_token():
    ids = parse_pattern("AKs,AKo,AQs")
    assert len(ids) == 3


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        parse_pattern("ZZ")
    with pytest.raises(ValueError):
        parse_pattern("AA-22+")     # mix invalide
    with pytest.raises(ValueError):
        parse_pattern("AKx")        # suffixe invalide


# ============ JSON LOADING ============

def test_hu_ranges_load():
    """HU 100bb doit charger sans erreur."""
    book = reload_book()
    scenarios = book.available_scenarios("HU")
    assert "rfi:BTN" in scenarios
    assert "vs_open:BB|BTN" in scenarios
    assert "vs_3bet:BTN|BB" in scenarios
    assert "vs_4bet:BB|BTN" in scenarios


def test_hu_rfi_btn_aa_raises():
    """AA en BTN RFI doit toujours raise (1.0)."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "rfi:BTN")
    aa = canonical_class("HA", "DA")
    freq = sc.strategy_for_class(aa)
    assert freq.get("raise", 0) > 0.99


def test_hu_rfi_btn_72o_folds():
    """72o en BTN RFI HU v0.3 : default=FOLD (le limp se fait iso-raise par Heuristic, plus cher que folder)."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "rfi:BTN")
    seven_two_o = canonical_class("H7", "D2")
    freq = sc.strategy_for_class(seven_two_o)
    assert freq.get("fold", 0) > 0.99


def test_hu_vs_open_bb_aks_pure_raise():
    """AKs en BB vs BTN open v0.2 : 3-bet pur value (Heuristic fold beaucoup)."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_open:BB|BTN")
    aks = canonical_class("HA", "HK")
    freq = sc.strategy_for_class(aks)
    assert freq.get("raise", 0) > 0.99
    assert freq.get("fold", 0) < 0.01


def test_hu_vs_open_bb_ajs_mixed():
    """AJs en BB vs BTN open v0.2 : mix 3-bet (30%) / call (70%)."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_open:BB|BTN")
    ajs = canonical_class("HA", "HJ")
    freq = sc.strategy_for_class(ajs)
    assert freq.get("raise", 0) > 0.2
    assert freq.get("call", 0) > 0.5
    assert freq.get("fold", 0) < 0.01


def test_hu_vs_3bet_btn_aa_4bets():
    """AA face à 3-bet BB : 4-bet pur."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_3bet:BTN|BB")
    aa = canonical_class("HA", "DA")
    freq = sc.strategy_for_class(aa)
    assert freq.get("raise", 0) > 0.99


def test_hu_vs_3bet_btn_qq_folds():
    """QQ face à 3-bet BB v0.5 : FOLD (Heuristic 3-bet = JJ+AK ; QQ derrière KK/AA, race AK).

    v0.5 stratégie de fer : seulement AA/KK 4-bet, tout le reste fold pour
    éviter de payer postflop OOP avec marginal vs tier 1 narrow.
    """
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_3bet:BTN|BB")
    qq = canonical_class("HQ", "DQ")
    freq = sc.strategy_for_class(qq)
    assert freq.get("fold", 0) > 0.99


def test_hu_vs_3bet_btn_aks_folds():
    """AKs face à 3-bet BB v0.5 : FOLD (chops vs AK, race JJ+, EV proche zéro à la limite négative)."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_3bet:BTN|BB")
    aks = canonical_class("HA", "HK")
    freq = sc.strategy_for_class(aks)
    assert freq.get("fold", 0) > 0.99


def test_hu_vs_4bet_bb_aa_jams():
    """AA en BB face à 4-bet BTN : 5-bet jam pur. raise_action = all_in."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_4bet:BB|BTN")
    aa = canonical_class("HA", "DA")
    freq = sc.strategy_for_class(aa)
    assert freq.get("raise", 0) > 0.99
    # Le sizing concret est ALL_IN
    assert sc.raise_action == Action.ALL_IN


def test_hu_vs_4bet_bb_72o_folds():
    """72o face à 4-bet BB : fold."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_4bet:BB|BTN")
    seven_two_o = canonical_class("H7", "D2")
    freq = sc.strategy_for_class(seven_two_o)
    assert freq.get("fold", 0) > 0.99


# ============ CONTEXT DETECTION ============

def _make_obs(num_players=2, dealer_id=0, player_id=0, hole=None,
              all_committed=None, bb=2, my_committed=None,
              stage=Stage.PREFLOP, legal=None):
    if hole is None:
        hole = ["HA", "DA"]
    if all_committed is None:
        all_committed = [1, 2] if num_players == 2 else [0] * num_players
    if my_committed is None:
        my_committed = all_committed[player_id]
    if legal is None:
        legal = [Action.FOLD, Action.CHECK_CALL,
                 Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN]
    return Observation(
        player_id=player_id,
        hole_cards=hole,
        community_cards=[],
        pot=sum(all_committed),
        my_committed=my_committed,
        my_stack=200 - my_committed,
        all_committed=all_committed,
        all_stacks=[200 - c for c in all_committed],
        stage=stage,
        legal_actions=legal,
        num_players=num_players,
        dealer_id=dealer_id,
        small_blind=bb // 2,
        big_blind=bb,
        player_statuses=[PlayerStatus.ALIVE] * num_players,
    )


def test_detect_rfi_btn_hu():
    """HU : SB/BTN à parler en premier (non-dealer dans rlcard), max bet = BB.

    Convention rlcard : dealer=BB, non-dealer=SB/BTN. Donc player_id=1 avec
    dealer_id=0 = BTN. all_committed=[BB=2, SB=1] = [2, 1].
    """
    reload_book()
    obs = _make_obs(num_players=2, dealer_id=0, player_id=1,
                    all_committed=[2, 1], bb=2, my_committed=1)
    ctx = detect_context(obs)
    assert ctx is not None
    ts, key, hero = ctx
    assert ts == "HU"
    assert key == "rfi:BTN"
    assert hero == "BTN"


def test_detect_vs_open_bb():
    """HU : BB à parler (dealer dans rlcard) après BTN open à 5.

    dealer_id=0 → player 0 = BB. all_committed=[BB=2, BTN_after_open=5].
    """
    reload_book()
    obs = _make_obs(num_players=2, dealer_id=0, player_id=0,
                    all_committed=[2, 5], bb=2, my_committed=2)
    ctx = detect_context(obs)
    assert ctx is not None
    _, key, _ = ctx
    assert key == "vs_open:BB|BTN"


def test_detect_vs_3bet_btn():
    """HU : BTN (= non-dealer) à parler après son open à 4 et BB 3-bet à 8.

    Sizings rlcard 5-action : open RAISE_POT = 2bb, 3-bet = 4bb.
    """
    reload_book()
    obs = _make_obs(num_players=2, dealer_id=0, player_id=1,
                    all_committed=[8, 4], bb=2, my_committed=4)
    ctx = detect_context(obs)
    assert ctx is not None
    _, key, _ = ctx
    assert key == "vs_3bet:BTN|BB"


def test_detect_vs_4bet_bb():
    """HU : BB (= dealer) face à 4-bet BTN. Sizings rlcard : 3-bet 4bb, 4-bet 8bb."""
    reload_book()
    obs = _make_obs(num_players=2, dealer_id=0, player_id=0,
                    all_committed=[8, 16], bb=2, my_committed=8)
    ctx = detect_context(obs)
    assert ctx is not None
    _, key, _ = ctx
    assert key == "vs_4bet:BB|BTN"


def test_detect_vs_limp_hu():
    """HU : BB face à SB limp (CHECK_CALL au lieu de raise).

    State : SB a CHECK_CALL la BB → all_committed=[2, 2] (les deux à BB amount),
    BB acte ensuite (dealer = BB = player 0, qui agit après SB en HU).
    """
    reload_book()
    obs = _make_obs(num_players=2, dealer_id=0, player_id=0,
                    all_committed=[2, 2], bb=2, my_committed=2)
    ctx = detect_context(obs)
    assert ctx is not None
    ts, key, hero = ctx
    assert ts == "HU"
    assert key == "vs_limp:BB|BTN"
    assert hero == "BB"


def test_hu_vs_limp_aa_iso_raise():
    """vs_limp:BB|BTN avec AA : 100% iso-raise (default est raise pour tous hands)."""
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_limp:BB|BTN")
    assert sc is not None
    aa = canonical_class("HA", "DA")
    freq = sc.strategy_for_class(aa)
    assert freq.get("raise", 0) > 0.99


def test_hu_vs_limp_72o_iso_raise():
    """vs_limp:BB|BTN avec 72o : aussi 100% iso-raise (SB tier 3 fold à tout raise).

    Le check-back perd OOP postflop. La iso-raise wide gagne +1bb à chaque limp.
    """
    reload_book()
    book = reload_book()
    sc = book.get("HU", "vs_limp:BB|BTN")
    seven_two_o = canonical_class("H7", "D2")
    freq = sc.strategy_for_class(seven_two_o)
    assert freq.get("raise", 0) > 0.99


def test_detect_returns_none_postflop():
    """Postflop → None."""
    reload_book()
    obs = _make_obs(num_players=2, stage=Stage.FLOP)
    assert detect_context(obs) is None


def test_detect_returns_none_unknown_table_size():
    """Table 4-max non couverte → None."""
    reload_book()
    obs = _make_obs(num_players=4, dealer_id=0, player_id=0,
                    all_committed=[0, 1, 2, 0], bb=2, my_committed=0)
    assert detect_context(obs) is None


# ============ 3-MAX ranges ============

def test_3max_ranges_load():
    """3-max 100bb doit charger."""
    book = reload_book()
    scenarios = book.available_scenarios("3max")
    assert "rfi:BTN" in scenarios
    assert "rfi:SB" in scenarios
    assert "vs_open:BB|SB" in scenarios
    assert "vs_limp:SB|BTN" in scenarios
    assert "vs_limp:BB|BTN" in scenarios
    assert "vs_3bet:BTN|SB" in scenarios
    assert "vs_4bet:BB|SB" in scenarios


def test_3max_rfi_btn_aa_raises():
    """AA en BTN open 3-max → raise pur."""
    book = reload_book()
    sc = book.get("3max", "rfi:BTN")
    aa = canonical_class("HA", "DA")
    assert sc.strategy_for_class(aa).get("raise", 0) > 0.99


def test_3max_vs_limp_default_iso_raise():
    """vs_limp:BB|BTN 3-max : default 100% iso-raise wide."""
    book = reload_book()
    sc = book.get("3max", "vs_limp:BB|BTN")
    # 72o not in explicit ranges → fallback to default = raise
    seven_two_o = canonical_class("H7", "D2")
    freq = sc.strategy_for_class(seven_two_o)
    assert freq.get("raise", 0) > 0.99


def test_3max_detect_rfi_btn():
    """3-max : BTN à parler en premier (dealer=1 → player 1 acts first).
    all_committed = [BB=2, BTN=0, SB=1]."""
    reload_book()
    obs = _make_obs(num_players=3, dealer_id=1, player_id=1,
                    all_committed=[2, 0, 1], bb=2, my_committed=0)
    ctx = detect_context(obs)
    assert ctx is not None
    ts, key, hero = ctx
    assert ts == "3max"
    assert key == "rfi:BTN"


def test_3max_detect_vs_limp_sb_after_btn_limp():
    """3-max : SB à parler après BTN limp. all_committed=[BB=2, BTN_limp=2, SB=1].
    dealer=1 → BTN=player 1 (committed 2 = limp), SB=player 2, BB=player 0.
    """
    reload_book()
    obs = _make_obs(num_players=3, dealer_id=1, player_id=2,
                    all_committed=[2, 2, 1], bb=2, my_committed=1)
    ctx = detect_context(obs)
    assert ctx is not None
    ts, key, hero = ctx
    assert ts == "3max"
    assert key == "vs_limp:SB|BTN"


def test_3max_detect_vs_limp_bb_after_btn_limp():
    """3-max : BB à parler après BTN limp + SB fold (rare) ou SB call.
    Cas BTN limp + SB call : all_committed=[BB=2, BTN=2, SB=2], BB=player 0."""
    reload_book()
    obs = _make_obs(num_players=3, dealer_id=1, player_id=0,
                    all_committed=[2, 2, 2], bb=2, my_committed=2)
    ctx = detect_context(obs)
    assert ctx is not None
    _, key, _ = ctx
    # Le premier limper en ordre d'action est BTN (offset 0)
    assert key == "vs_limp:BB|BTN"


# ============ 6-MAX ranges ============

def test_6max_ranges_load():
    """6-max 100bb doit charger."""
    book = reload_book()
    scenarios = book.available_scenarios("6max")
    assert "rfi:UTG" in scenarios
    assert "rfi:HJ" in scenarios
    assert "rfi:CO" in scenarios
    assert "rfi:BTN" in scenarios
    assert "rfi:SB" in scenarios
    assert "vs_open:BB|BTN" in scenarios
    assert "vs_3bet:UTG|HJ" in scenarios
    assert "vs_limp:BTN|CO" in scenarios


def test_6max_rfi_utg_aa_raises():
    """AA en UTG 6-max → raise."""
    book = reload_book()
    sc = book.get("6max", "rfi:UTG")
    aa = canonical_class("HA", "DA")
    assert sc.strategy_for_class(aa).get("raise", 0) > 0.99


def test_6max_rfi_utg_22_folds():
    """22 en UTG 6-max → fold (range tight value-heavy, TT+ only pour les pairs).
    Vérifie qu'on ne fold pas tout : 77+ doit raise.
    """
    book = reload_book()
    sc = book.get("6max", "rfi:UTG")
    twos = canonical_class("H2", "D2")
    # 22-66 not in UTG open range, default = fold
    assert sc.strategy_for_class(twos).get("fold", 0) > 0.99
    sevens = canonical_class("H7", "D7")
    assert sc.strategy_for_class(sevens).get("raise", 0) > 0.99


def test_6max_detect_rfi_utg():
    """6-max : UTG = offset 3 = player 0 quand dealer_id=3.
    Initial state : all_committed = [UTG=0, HJ=0, CO=0, BTN=0, SB=1, BB=2]."""
    reload_book()
    obs = _make_obs(num_players=6, dealer_id=3, player_id=0,
                    all_committed=[0, 0, 0, 0, 1, 2], bb=2, my_committed=0)
    ctx = detect_context(obs)
    assert ctx is not None
    ts, key, hero = ctx
    assert ts == "6max"
    assert key == "rfi:UTG"


def test_6max_detect_vs_limp_btn_after_co_limp():
    """6-max : BTN agit après CO limp (UTG/HJ fold).
    dealer=3 → BTN=player 3. all_committed=[UTG=0, HJ=0, CO=2, BTN=0, SB=1, BB=2].
    """
    reload_book()
    obs = _make_obs(num_players=6, dealer_id=3, player_id=3,
                    all_committed=[0, 0, 2, 0, 1, 2], bb=2, my_committed=0)
    ctx = detect_context(obs)
    assert ctx is not None
    _, key, _ = ctx
    assert key == "vs_limp:BTN|CO"


def test_6max_detect_vs_open_co_from_utg():
    """6-max : CO face UTG open (HJ fold).
    UTG=player 0, raise → committed=5. CO=player 2 à parler.
    all_committed=[UTG=5, HJ=0, CO=0, BTN=0, SB=1, BB=2]."""
    reload_book()
    obs = _make_obs(num_players=6, dealer_id=3, player_id=2,
                    all_committed=[5, 0, 0, 0, 1, 2], bb=2, my_committed=0)
    ctx = detect_context(obs)
    assert ctx is not None
    _, key, _ = ctx
    assert key == "vs_open:CO|UTG"


# ============ END-TO-END pro_preflop_strategy ============

def test_pro_strategy_hu_rfi_aa():
    """HU RFI avec AA → 1.0 RAISE_HALF_POT (le BTN = non-dealer en rlcard)."""
    reload_book()
    obs = _make_obs(num_players=2, dealer_id=0, player_id=1,
                    hole=["HA", "DA"],
                    all_committed=[2, 1], bb=2, my_committed=1)
    strat = pro_preflop_strategy(obs)
    assert strat is not None
    actions = {a: f for a, f in strat}
    assert Action.RAISE_HALF_POT in actions
    assert actions[Action.RAISE_HALF_POT] > 0.99


def test_pro_strategy_hu_rfi_72o():
    """HU RFI avec 72o v0.3 : default=FOLD (limp leak vs Heuristic iso-raise)."""
    reload_book()
    obs = _make_obs(num_players=2, dealer_id=0, player_id=1,
                    hole=["H7", "D2"],
                    all_committed=[2, 1], bb=2, my_committed=1)
    strat = pro_preflop_strategy(obs)
    assert strat is not None
    actions = {a: f for a, f in strat}
    assert actions.get(Action.FOLD, 0) > 0.99


def test_pro_strategy_hu_vs_4bet_aa_jam():
    """HU BB AA face à 4-bet → ALL_IN. Sizings rlcard : 3-bet 4bb, 4-bet 8bb."""
    reload_book()
    obs = _make_obs(num_players=2, dealer_id=0, player_id=0,
                    hole=["HA", "DA"],
                    all_committed=[8, 16], bb=2, my_committed=8)
    strat = pro_preflop_strategy(obs)
    assert strat is not None
    actions = {a: f for a, f in strat}
    assert actions.get(Action.ALL_IN, 0) > 0.99


def test_pro_strategy_returns_none_when_unsupported():
    """Table size non couverte → None (le caller fallback)."""
    reload_book()
    obs = _make_obs(num_players=4, dealer_id=0, player_id=0,
                    all_committed=[0, 1, 2, 0], bb=2, my_committed=0)
    assert pro_preflop_strategy(obs) is None
