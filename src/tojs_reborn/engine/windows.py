from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .events import EventSource, FactEvent
from .resolver import EffectHandler
from .rules import opponent_id
from .state import AbilityDefinition, GameState, UnitState


WindowChoice = Callable[[str, list[dict[str, Any]]], dict[str, Any]]


def list_trigger_intercept_window(
    state: GameState,
    player_id: str,
    *,
    window: str,
    cause_event_no: int,
) -> dict[str, Any]:
    candidates = []
    for card_instance_id in state.players[player_id].trigger_zone.cards:
        card_no = state.card_instances[card_instance_id].card_no
        card = state.card_catalog[card_no]
        if card.category in {"trigger", "intercept"}:
            candidates.append(
                {
                    "card_instance_id": card_instance_id,
                    "card_no": card_no,
                    "category": card.category,
                    "color": card.color,
                }
            )
    return {
        "window": window,
        "player_id": player_id,
        "cause_event_no": cause_event_no,
        "candidates": candidates,
        "pass_action": {"type": "pass_window", "window": window},
    }


def process_trigger_window(
    state: GameState,
    cause_event_no: int,
    effect_handlers: dict[str, EffectHandler] | None = None,
) -> int:
    if effect_handlers is None:
        from .actions import get_effect_handlers

        effect_handlers = get_effect_handlers()
    cause_event = _event_by_no(state, cause_event_no)
    activated_count = 0
    current_player_id = state.turn_player_id
    consecutive_empty_checks = 0
    state.event_store.append(
        "trigger_window_opened",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=current_player_id,
        cause_event_no=cause_event_no,
        payload={"start_player_id": current_player_id},
    )
    while consecutive_empty_checks < 2:
        activated = _activate_first_matching_card(
            state,
            current_player_id,
            card_category="trigger",
            window_prefix="TRIGGER",
            window_name=cause_event.type,
            cause_event=cause_event,
            activation_event_type="trigger_activated",
            effect_handlers=effect_handlers,
        )
        current_player_id = opponent_id(current_player_id)
        if activated:
            activated_count += 1
            consecutive_empty_checks = 0
        else:
            consecutive_empty_checks += 1
    return activated_count


def process_intercept_window(
    state: GameState,
    window: str,
    cause_event_no: int,
    choose_intercept: WindowChoice | None = None,
    effect_handlers: dict[str, EffectHandler] | None = None,
) -> int:
    if effect_handlers is None:
        from .actions import get_effect_handlers

        effect_handlers = get_effect_handlers()
    cause_event = _event_by_no(state, cause_event_no)
    activated_count = 0
    current_player_id = state.turn_player_id
    consecutive_passes = 0
    state.event_store.append(
        "intercept_window_opened",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=current_player_id,
        cause_event_no=cause_event_no,
        payload={"window": window, "start_player_id": current_player_id},
    )
    while consecutive_passes < 2:
        actions = _list_intercept_actions(state, current_player_id, window, cause_event)
        selected = (
            choose_intercept(current_player_id, actions)
            if choose_intercept is not None
            else {"type": "pass_window", "window": window}
        )
        if selected not in actions:
            state.event_store.append(
                "invalid_response",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=current_player_id,
                cause_event_no=cause_event_no,
                payload={"selected": selected, "fallback": {"type": "pass_window", "window": window}},
            )
            selected = {"type": "pass_window", "window": window}
        if selected["type"] == "activate_intercept":
            activated = _activate_card(
                state,
                current_player_id,
                selected["card_instance_id"],
                cause_event,
                "intercept_activated",
                effect_handlers,
                window_name=window,
            )
            if activated:
                activated_count += 1
                consecutive_passes = 0
            else:
                consecutive_passes += 1
        else:
            state.event_store.append(
                "intercept_passed",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=current_player_id,
                cause_event_no=cause_event_no,
                payload={"window": window},
            )
            consecutive_passes += 1
        current_player_id = opponent_id(current_player_id)
    return activated_count


def _activate_first_matching_card(
    state: GameState,
    player_id: str,
    *,
    card_category: str,
    window_prefix: str,
    window_name: str,
    cause_event: FactEvent,
    activation_event_type: str,
    effect_handlers: dict[str, EffectHandler],
) -> bool:
    for card_instance_id in list(state.players[player_id].trigger_zone.cards):
        card_no = state.card_instances[card_instance_id].card_no
        card = state.card_catalog[card_no]
        if card.category != card_category:
            continue
        if not any(_timing_matches(ability, window_prefix, window_name) for ability in card.abilities):
            continue
        return _activate_card(
            state,
            player_id,
            card_instance_id,
            cause_event,
            activation_event_type,
            effect_handlers,
            window_name=window_name,
        )
    return False


def _activate_card(
    state: GameState,
    player_id: str,
    card_instance_id: str,
    cause_event: FactEvent,
    activation_event_type: str,
    effect_handlers: dict[str, EffectHandler],
    *,
    window_name: str | None = None,
) -> bool:
    if card_instance_id not in state.players[player_id].trigger_zone.cards:
        return False
    instance = state.card_instances[card_instance_id]
    card = state.card_catalog[instance.card_no]
    prefix = "TRIGGER" if card.category == "trigger" else "INTERCEPT"
    window_name = window_name or cause_event.type
    matching_abilities = [
        ability
        for ability in card.abilities
        if ability.status == "supported" and _timing_matches(ability, prefix, str(window_name))
    ]
    if not matching_abilities:
        return False
    activation_event = state.event_store.append(
        activation_event_type,
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event.event_no,
        source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
        payload={"category": card.category},
    )
    source = UnitState(
        unit_id="",
        card_instance_id=card_instance_id,
        card_no=instance.card_no,
        owner_player_id=player_id,
        level=instance.level,
    )
    for ability in matching_abilities:
        _resolve_card_ability(state, source, ability, activation_event, effect_handlers)
    if card_instance_id in state.players[player_id].trigger_zone.cards:
        state.players[player_id].trigger_zone.remove(card_instance_id)
        state.players[player_id].discard_pile.add(card_instance_id)
        state.event_store.append(
            "card_moved",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=player_id,
            cause_event_no=activation_event.event_no,
            source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
            payload={
                "from_zone": "trigger_zone",
                "to_zone": "discard_pile",
                "owner_player_id": player_id,
                "reason": "window_activation",
            },
        )
    return True


def _resolve_card_ability(
    state: GameState,
    source: UnitState,
    ability: AbilityDefinition,
    activation_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
) -> None:
    ability_event = state.event_store.append(
        "ability_resolved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=source.owner_player_id,
        cause_event_no=activation_event.event_no,
        source=EventSource(
            card_no=source.card_no,
            card_instance_id=source.card_instance_id,
            ability_id=ability.ability_id,
        ),
        payload={"ability_name": ability.name, "timing": ability.timing},
    )
    for step in ability.effect_steps:
        handler = effect_handlers.get(str(step.get("effect")))
        if handler is not None:
            handler(state, source, ability, ability_event, step)


def _list_intercept_actions(state: GameState, player_id: str, window: str, cause_event: FactEvent) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for card_instance_id in state.players[player_id].trigger_zone.cards:
        card_no = state.card_instances[card_instance_id].card_no
        card = state.card_catalog[card_no]
        if card.category != "intercept":
            continue
        if not any(_timing_matches(ability, "INTERCEPT", window) for ability in card.abilities):
            continue
        actions.append(
            {
                "type": "activate_intercept",
                "window": window,
                "cause_event_no": cause_event.event_no,
                "card_instance_id": card_instance_id,
            }
        )
    actions.append({"type": "pass_window", "window": window})
    return actions


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


def _event_by_no(state: GameState, event_no: int) -> FactEvent:
    for event in state.event_store.events:
        if event.event_no == event_no:
            return event
    raise ValueError(f"unknown event_no: {event_no}")
