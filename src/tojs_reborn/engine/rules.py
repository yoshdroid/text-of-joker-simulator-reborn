from __future__ import annotations

from dataclasses import asdict, dataclass

from .state import GameState, UnitState


@dataclass(frozen=True)
class Ruleset:
    max_hand_size: int = 7
    max_battlefield_units: int = 5
    max_trigger_zone_cards: int = 4
    deck_size: int = 40
    max_same_card_copies: int = 3
    initial_hand_size: int = 4
    initial_life: int = 7
    max_cp: int = 12
    first_player_cp_schedule: tuple[int, ...] = (2, 3, 4, 5, 6, 7)
    second_player_cp_schedule: tuple[int, ...] = (3, 3, 4, 5, 6, 7)


DEFAULT_RULESET = Ruleset()
MAX_HAND_SIZE = DEFAULT_RULESET.max_hand_size
MAX_BATTLEFIELD_UNITS = DEFAULT_RULESET.max_battlefield_units
MAX_TRIGGER_ZONE_CARDS = DEFAULT_RULESET.max_trigger_zone_cards
MAX_CP = DEFAULT_RULESET.max_cp
BP_THOUSAND_SCALE_THRESHOLD = 100


def ruleset_to_dict(ruleset: Ruleset = DEFAULT_RULESET) -> dict:
    return asdict(ruleset)


def turn_cp_for(player_id: str, player_turn_count: int, ruleset: Ruleset = DEFAULT_RULESET) -> int:
    schedule = ruleset.first_player_cp_schedule if player_id == "P1" else ruleset.second_player_cp_schedule
    index = min(player_turn_count, len(schedule)) - 1
    return min(ruleset.max_cp, schedule[index])


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
        printed_bp = card_bp_to_game_bp(card.bp_by_level[index])
    return max(0, printed_bp + sum(bp_amount_to_game_bp(int(modifier.get("amount", 0))) for modifier in unit.base_bp_modifiers))


def get_unit_modified_bp(state: GameState, unit: UnitState) -> int:
    return sum(bp_amount_to_game_bp(int(modifier.get("amount", 0))) for modifier in unit.bp_modifiers)


def card_bp_to_game_bp(value: int) -> int:
    return bp_amount_to_game_bp(value)


def bp_amount_to_game_bp(value: int) -> int:
    if value != 0 and abs(value) < BP_THOUSAND_SCALE_THRESHOLD:
        return value * 1000
    return value
