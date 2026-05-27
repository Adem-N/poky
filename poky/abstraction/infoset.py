"""
Info-set encoding pour MCCFR sur NLHE.

Un "info set" en CFR = l'ensemble d'informations qu'un joueur a quand c'est à
son tour de décider. Pour NLHE, cela comprend :
  - sa position (offset par rapport au bouton)
  - la street courante (préflop / flop / turn / river)
  - sa main (abstractée via card bucket : 169 préflop, 5 par street postflop)
  - l'historique des actions abstraites de tous les joueurs

On encode tout ça en **bytes** pour servir de clé dans la strategy table
(`dict[bytes, np.ndarray]`). Format compact pour minimiser RAM + lookup rapide.

FORMAT (variable, ~6-30 bytes par info set) :
  byte 0    : position offset from BTN (0..N-1)
  byte 1    : stage (0=preflop, 1=flop, 2=turn, 3=river)
  bytes 2-3 : card bucket (uint16 little-endian)
              - preflop : class id 0..168 (de poky.abstraction.preflop)
              - postflop : bucket id 0..NUM_POSTFLOP_BUCKETS-1
  byte 4    : number of betting actions in history (0..127)
  bytes 5+  : sequence of (player_id, action_id) pairs, 1 byte each
              packed as (player << 4) | action_id
              (Soutient jusqu'à 15 joueurs et 16 actions abstraites max — large)

À la limite du standard MCCFR, ce format permet ~256 actions max d'historique
mais en pratique une main NLHE a < 30 actions max.

API :
  encode_history(actions: List[Tuple[int, int]]) -> bytes
  infoset_key(obs, history_actions, card_bucket) -> bytes
  decode_for_debug(key: bytes) -> dict
"""
from typing import List, Tuple

from poky.engine import Observation


def encode_history(history: List[Tuple[int, int]]) -> bytes:
    """history = liste de (player_id, action_idx). Retourne bytes packés.
    `player_id` ∈ [0, 15], `action_idx` ∈ [0, 15] (4 bits chacun)."""
    out = bytearray()
    out.append(min(len(history), 127))   # max 127 actions encodées
    for player_id, action_idx in history[:127]:
        packed = ((player_id & 0xF) << 4) | (action_idx & 0xF)
        out.append(packed)
    return bytes(out)


def decode_history(blob: bytes) -> List[Tuple[int, int]]:
    """Inverse de encode_history."""
    n = blob[0]
    out = []
    for i in range(1, n + 1):
        byte = blob[i]
        player_id = (byte >> 4) & 0xF
        action_idx = byte & 0xF
        out.append((player_id, action_idx))
    return out


def infoset_key(obs: Observation, history: List[Tuple[int, int]],
                card_bucket: int) -> bytes:
    """
    Clé canonique de l'info set du joueur courant.

    Args:
      obs : Observation courante (donne position, stage, num_players).
      history : liste des (player_id, action_idx) abstraites depuis le début de main.
      card_bucket : abstraction de la main (préflop class ou postflop bucket).

    Returns: bytes (5 + variable). Utilisable directement comme dict key.
    """
    offset = (obs.player_id - obs.dealer_id) % obs.num_players
    stage = int(obs.stage)
    if not (0 <= card_bucket < 65536):
        raise ValueError(f"card_bucket={card_bucket} out of uint16 range")
    out = bytearray()
    out.append(offset & 0xFF)
    out.append(stage & 0xFF)
    out.append(card_bucket & 0xFF)
    out.append((card_bucket >> 8) & 0xFF)
    out += encode_history(history)
    return bytes(out)


def decode_for_debug(key: bytes) -> dict:
    """Décode une key pour inspection (tests / debug)."""
    offset = key[0]
    stage = key[1]
    card_bucket = key[2] | (key[3] << 8)
    hist_blob = key[4:]
    history = decode_history(hist_blob)
    return {
        "offset_from_btn": offset,
        "stage": stage,
        "card_bucket": card_bucket,
        "history": history,
    }


def history_truncated(history: List[Tuple[int, int]],
                      max_actions: int = 24) -> List[Tuple[int, int]]:
    """
    Tronque l'historique aux N dernières actions. Réduit la taille du game tree
    (à la Pluribus) sans trop perdre d'info — la plupart des décisions dépendent
    surtout des actions récentes.
    """
    if len(history) <= max_actions:
        return history
    return history[-max_actions:]
