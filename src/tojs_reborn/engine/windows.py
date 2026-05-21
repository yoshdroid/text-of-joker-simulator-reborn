from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .activation_requirements import ability_matches_window, card_can_activate
from .events import EventSource, FactEvent
from .resolver import EffectHandler
from .rules import opponent_id
from .state import AbilityDefinition, GameState, UnitState
from tojs_reborn.io.views import card_instance_public_view


WindowChoice = Callable[[str, list[dict[str, Any]]], dict[str, Any]]

_AUTOMATIC_INTERCEPT_WINDOWS = {
    "unit_entered": "unit_entered",
    "unit_attacked": "attack",
    "battle_started": "battle",
    "unit_destroyed": "unit_destroyed",
}

_WINDOW_EVENT_TYPES = {
    "trigger_window_opened",
    "trigger_activated",
    "intercept_window_opened",
    "intercept_activated",
    "intercept_passed",
}


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
        if card.category in {"trigger", "intercept"} and card_can_activate(state, player_id, card_instance_id):
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
        "pass_action": _pass_window_action(window),
    }


def process_trigger_window(
    state: GameState,
    cause_event_no: int,
    effect_handlers: dict[str, EffectHandler] | None = None,
    *,
    window_name: str | None = None,
) -> int:
    if effect_handlers is None:
        from .effects import get_effect_handlers

        effect_handlers = get_effect_handlers()
    cause_event = _event_by_no(state, cause_event_no)
    window_name = window_name or cause_event.type
    if not _has_matching_card(state, "trigger", "TRIGGER", window_name, cause_event):
        return 0
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
            window_name=window_name,
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
        from .effects import get_effect_handlers

        effect_handlers = get_effect_handlers()
    cause_event = _event_by_no(state, cause_event_no)
    if not _has_matching_card(state, "intercept", "INTERCEPT", window, cause_event):
        return 0
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
            else actions[-1]
        )
        if selected not in actions:
            fallback = actions[-1]
            state.event_store.append(
                "invalid_response",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=current_player_id,
                cause_event_no=cause_event_no,
                payload={"selected": selected, "fallback": fallback},
            )
            selected = fallback
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


def process_windows_for_events(
    state: GameState,
    first_event_no: int,
    choose_intercept: WindowChoice | None = None,
    effect_handlers: dict[str, EffectHandler] | None = None,
) -> int:
    processed_count = 0
    index = _event_index_at_or_after(state, first_event_no)
    while index < len(state.event_store.events):
        event = state.event_store.events[index]
        if event.type not in _WINDOW_EVENT_TYPES:
            trigger_window_name = _trigger_window_name_for_event(event)
            processed_count += process_trigger_window(state, event.event_no, effect_handlers, window_name=trigger_window_name)
            intercept_window = _AUTOMATIC_INTERCEPT_WINDOWS.get(event.type)
            if intercept_window is None and event.type == "life_changed" and event.payload.get("reason") == "player_attack":
                intercept_window = "player_attack_success"
            if intercept_window is not None:
                if not _window_already_opened(state, event.event_no, intercept_window):
                    processed_count += process_intercept_window(
                        state,
                        intercept_window,
                        event.event_no,
                        choose_intercept,
                        effect_handlers,
                    )
                if intercept_window == "unit_destroyed":
                    from .combat import finalize_pending_destroyed_unit

                    finalize_pending_destroyed_unit(state, event.event_no)
        index += 1
    return processed_count


def _trigger_window_name_for_event(event: FactEvent) -> str | None:
    if event.type == "life_changed" and event.payload.get("reason") == "player_attack":
        return "player_attack_success"
    return None


def has_matching_intercept_window(state: GameState, window: str, cause_event_no: int) -> bool:
    cause_event = _event_by_no(state, cause_event_no)
    return _has_matching_card(state, "intercept", "INTERCEPT", window, cause_event)


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
        if not card_can_activate(state, player_id, card_instance_id):
            continue
        if not any(ability_matches_window(state, ability, window_prefix, window_name, cause_event, player_id) for ability in card.abilities):
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
    if not card_can_activate(state, player_id, card_instance_id):
        return False
    prefix = "TRIGGER" if card.category == "trigger" else "INTERCEPT"
    window_name = window_name or cause_event.type
    matching_abilities = [
        ability
        for ability in card.abilities
        if ability_matches_window(state, ability, prefix, str(window_name), cause_event, player_id)
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
        payload={
            "category": card.category,
            "card": card_instance_public_view(state, card_instance_id),
        },
    )
    if card.category == "intercept":
        before_cp = state.players[player_id].current_cp
        state.players[player_id].current_cp -= card.cp or 0
        state.event_store.append(
            "cp_changed",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=player_id,
            cause_event_no=activation_event.event_no,
            source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
            payload={
                "before_cp": before_cp,
                "after_cp": state.players[player_id].current_cp,
                "amount": -(card.cp or 0),
                "reason": "intercept_activation",
            },
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
        if not card_can_activate(state, player_id, card_instance_id):
            continue
        if not any(ability_matches_window(state, ability, "INTERCEPT", window, cause_event, player_id) for ability in card.abilities):
            continue
        actions.append(
            {
                "type": "activate_intercept",
                "window": window,
                "cause_event_no": cause_event.event_no,
                "card_instance_id": card_instance_id,
                "card": card_instance_public_view(state, card_instance_id),
                "display": {"label": f"{card.name}を発動する"},
            }
        )
    actions.append(_pass_window_action(window))
    return actions


def _pass_window_action(window: str) -> dict[str, Any]:
    return {
        "type": "pass_window",
        "window": window,
        "display": {"label": "発動しない"},
    }


def _has_matching_card(
    state: GameState,
    card_category: str,
    window_prefix: str,
    window_name: str,
    cause_event: FactEvent,
) -> bool:
    for player in state.players.values():
        for card_instance_id in player.trigger_zone.cards:
            card_no = state.card_instances[card_instance_id].card_no
            card = state.card_catalog[card_no]
            if card.category != card_category:
                continue
            if not card_can_activate(state, player.player_id, card_instance_id):
                continue
            if any(ability_matches_window(state, ability, window_prefix, window_name, cause_event, player.player_id) for ability in card.abilities):
                return True
    return False


def _event_by_no(state: GameState, event_no: int) -> FactEvent:
    for event in state.event_store.events:
        if event.event_no == event_no:
            return event
    raise ValueError(f"unknown event_no: {event_no}")


def _window_already_opened(state: GameState, cause_event_no: int, window: str) -> bool:
    return any(
        event.type == "intercept_window_opened"
        and event.cause_event_no == cause_event_no
        and event.payload.get("window") == window
        for event in state.event_store.events
    )


def _event_index_at_or_after(state: GameState, event_no: int) -> int:
    for index, event in enumerate(state.event_store.events):
        if event.event_no >= event_no:
            return index
    return len(state.event_store.events)
