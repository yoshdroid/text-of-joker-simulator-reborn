from __future__ import annotations

from .state import GameState, UnitState


def opponent_id(player_id: str) -> str:
    return "P2" if player_id == "P1" else "P1"


def get_unit_bp(state: GameState, unit: UnitState) -> int:
    return max(0, get_unit_base_bp(state, unit) + get_unit_modified_bp(state, unit))


def get_unit_base_bp(state: GameState, unit: UnitState) -> int:
    card = state.card_catalog[unit.card_no]
    if not card.bp_by_level:
        printed_bp = 0
    else:
        index = max(0, min(unit.level, len(card.bp_by_level)) - 1)
        printed_bp = card.bp_by_level[index]
    return max(0, printed_bp + sum(int(modifier.get("amount", 0)) for modifier in unit.base_bp_modifiers))


def get_unit_modified_bp(state: GameState, unit: UnitState) -> int:
    return sum(int(modifier.get("amount", 0)) for modifier in unit.bp_modifiers)
