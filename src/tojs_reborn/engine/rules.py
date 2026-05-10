from __future__ import annotations

from .state import GameState, UnitState


def opponent_id(player_id: str) -> str:
    return "P2" if player_id == "P1" else "P1"


def get_unit_bp(state: GameState, unit: UnitState) -> int:
    card = state.card_catalog[unit.card_no]
    if not card.bp_by_level:
        base_bp = 0
    else:
        index = max(0, min(unit.level, len(card.bp_by_level)) - 1)
        base_bp = card.bp_by_level[index]
    modifier_amount = sum(int(modifier.get("amount", 0)) for modifier in unit.bp_modifiers)
    return max(0, base_bp + modifier_amount)
