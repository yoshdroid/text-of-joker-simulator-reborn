from __future__ import annotations

from .state import GameState, UnitState


def opponent_id(player_id: str) -> str:
    return "P2" if player_id == "P1" else "P1"


def get_unit_bp(state: GameState, unit: UnitState) -> int:
    card = state.card_catalog[unit.card_no]
    if not card.bp_by_level:
        return 0
    index = max(0, min(unit.level, len(card.bp_by_level)) - 1)
    return card.bp_by_level[index]

