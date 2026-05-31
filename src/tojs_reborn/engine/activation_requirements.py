from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import FactEvent
from .state import AbilityDefinition, GameState
from .targets import resolve_player_id, unit_candidates_for_selector


COLORED_INTERCEPT_COLORS = {"赤", "黄", "青", "緑"}


@dataclass(frozen=True)
class ActivationCheck:
    can_activate: bool
    reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


def card_can_activate(state: GameState, player_id: str, card_instance_id: str) -> bool:
    return explain_card_activation(state, player_id, card_instance_id).can_activate


def explain_card_activation(state: GameState, player_id: str, card_instance_id: str) -> ActivationCheck:
    instance = state.card_instances[card_instance_id]
    if instance.card_no in state.joker_catalog:
        return explain_joker_activation(state, player_id, card_instance_id)
    card = state.card_catalog[instance.card_no]
    details: dict[str, Any] = {
        "card_instance_id": card_instance_id,
        "card_no": instance.card_no,
        "category": card.category,
        "color": card.color,
    }
    if card.category != "intercept":
        return ActivationCheck(True, details=details)
    required_cp = card.cp or 0
    current_cp = state.players[player_id].current_cp
    reasons: list[str] = []
    details.update({"current_cp": current_cp, "required_cp": required_cp})
    if current_cp < required_cp:
        reasons.append("insufficient_cp")
    if card.color not in COLORED_INTERCEPT_COLORS:
        return ActivationCheck(not reasons, tuple(reasons), details)

    has_same_color_unit = _has_own_same_color_unit(state, player_id, card.color)
    details.update({"required_unit_color": card.color, "has_same_color_unit": has_same_color_unit})
    if not has_same_color_unit:
        reasons.append("missing_same_color_unit")
    return ActivationCheck(not reasons, tuple(reasons), details)


def explain_joker_activation(state: GameState, player_id: str, card_instance_id: str) -> ActivationCheck:
    instance = state.card_instances[card_instance_id]
    joker = state.joker_catalog.get(instance.card_no)
    details: dict[str, Any] = {
        "card_instance_id": card_instance_id,
        "card_no": instance.card_no,
        "category": "joker",
        "joker_no": instance.card_no,
        "current_cp": state.players[player_id].current_cp,
    }
    reasons: list[str] = []
    if joker is None:
        reasons.append("not_joker")
        return ActivationCheck(False, tuple(reasons), details)
    details.update({"required_cp": joker.cp, "speed": joker.speed})
    if state.turn_player_id != player_id:
        reasons.append("not_turn_player")
    if card_instance_id not in state.players[player_id].hand.cards:
        reasons.append("card_not_in_hand")
    if state.players[player_id].current_cp < joker.cp:
        reasons.append("insufficient_cp")
    return ActivationCheck(not reasons, tuple(reasons), details)


def _has_own_same_color_unit(state: GameState, player_id: str, color: str) -> bool:
    return any(
        state.card_catalog[state.units[unit_id].card_no].color == color
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
    if not _ability_has_required_targets(state, ability, player_id):
        return False
    if ability.timing.upper().endswith("_UNIT_ENTERED") and cause_event.actor_player_id != player_id:
        return False
    return True


def _ability_has_required_targets(state: GameState, ability: AbilityDefinition, player_id: str) -> bool:
    selector = ability.raw.get("selector")
    if not isinstance(selector, dict):
        return True
    if selector.get("type") != "unit" or not bool(selector.get("required", True)):
        return True
    controller = resolve_player_id(player_id, selector.get("controller"))
    return bool(unit_candidates_for_selector(state, controller, selector))


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
    if condition_type == "battle_winner_is_owner":
        return cause_event.payload.get("winner_player_id") == player_id
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
