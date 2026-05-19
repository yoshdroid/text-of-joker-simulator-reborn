from __future__ import annotations

from .events import FactEvent
from .state import AbilityDefinition, GameState


COLORED_INTERCEPT_COLORS = {"赤", "黄", "青", "緑"}


def card_can_activate(state: GameState, player_id: str, card_instance_id: str) -> bool:
    instance = state.card_instances[card_instance_id]
    card = state.card_catalog[instance.card_no]
    if card.category != "intercept":
        return True
    if state.players[player_id].current_cp < (card.cp or 0):
        return False
    if card.color not in COLORED_INTERCEPT_COLORS:
        return True
    return any(
        state.card_catalog[state.units[unit_id].card_no].color == card.color
        for unit_id in state.players[player_id].battlefield.units
        if unit_id in state.units
    )


def ability_matches_window(
    state: GameState,
    ability: AbilityDefinition,
    prefix: str,
    window_name: str,
    cause_event: FactEvent,
    player_id: str,
) -> bool:
    if not _timing_matches(ability, prefix, window_name):
        return False
    if not _window_condition_matches(state, ability, cause_event, player_id):
        return False
    if ability.timing.upper().endswith("_UNIT_ENTERED") and cause_event.actor_player_id != player_id:
        return False
    return True


def _window_condition_matches(state: GameState, ability: AbilityDefinition, cause_event: FactEvent, player_id: str) -> bool:
    condition = ability.raw.get("condition")
    if not isinstance(condition, dict):
        return True
    condition_type = condition.get("type")
    if condition_type == "event_actor_is_owner":
        return cause_event.actor_player_id == player_id
    if condition_type == "event_actor_is_rival":
        return cause_event.actor_player_id is not None and cause_event.actor_player_id != player_id
    if condition_type == "battle_attacker_is_owner":
        return cause_event.type == "battle_started" and cause_event.actor_player_id == player_id
    if condition_type == "battle_unit_controller_is_owner":
        if cause_event.type != "battle_started":
            return False
        if cause_event.actor_player_id == player_id:
            return True
        blocker_unit_id = cause_event.payload.get("blocker_unit_id")
        return (
            isinstance(blocker_unit_id, str)
            and blocker_unit_id in state.units
            and state.units[blocker_unit_id].owner_player_id == player_id
        )
    return True


def _timing_matches(ability: AbilityDefinition, prefix: str, window_name: str) -> bool:
    if ability.status != "supported":
        return False
    timing = ability.timing.upper()
    normalized_window = window_name.upper()
    return timing in {
        f"{prefix}_ANY",
        f"{prefix}_{normalized_window}",
        normalized_window,
    }
