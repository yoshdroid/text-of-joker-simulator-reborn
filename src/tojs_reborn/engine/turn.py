from __future__ import annotations

from .actions import draw_cards, get_effect_handlers
from .events import EventSource
from .resolver import AbilityCostChoice, OptionalAbilityChoice, resolve_turn_ended
from .rules import opponent_id
from .state import GameState


def start_turn(state: GameState, player_id: str, *, draw_count: int = 1, cp: int = 2) -> None:
    state.turn_player_id = player_id
    turn_event = state.event_store.append(
        "turn_started",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        payload={"draw_count": draw_count, "cp": cp},
    )
    player = state.players[player_id]
    for unit_id in player.battlefield.units:
        unit = state.units[unit_id]
        if not unit.exhausted:
            continue
        unit.exhausted = False
        state.event_store.append(
            "unit_action_recovered",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=player_id,
            cause_event_no=turn_event.event_no,
            payload={"unit_id": unit_id, "reason": "turn_start"},
        )
    before_cp = player.current_cp
    player.current_cp = cp
    state.event_store.append(
        "cp_set",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=turn_event.event_no,
        payload={"before_cp": before_cp, "after_cp": cp},
    )
    draw_cards(
        state,
        player_id,
        draw_count,
        cause_event_no=turn_event.event_no,
        source=EventSource(),
    )


def end_turn(
    state: GameState,
    player_id: str,
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    if state.turn_player_id != player_id:
        raise ValueError(f"not turn player: {player_id}")
    turn_event = state.event_store.append(
        "turn_ended",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
    )
    resolve_turn_ended(state, player_id, turn_event, get_effect_handlers(), optional_ability_choice, ability_cost_choice)
    _expire_turn_modifiers(state, turn_event.event_no)
    if player_id == "P2":
        state.round_no += 1
    state.turn_no += 1
    state.turn_player_id = opponent_id(player_id)


def _expire_turn_modifiers(state: GameState, cause_event_no: int) -> None:
    for unit in list(state.units.values()):
        kept_modifiers = []
        expired_count = 0
        for modifier in unit.bp_modifiers:
            if modifier.get("duration") == "turn":
                expired_count += 1
            else:
                kept_modifiers.append(modifier)
        if expired_count == 0:
            continue
        unit.bp_modifiers = kept_modifiers
        state.event_store.append(
            "modifier_expired",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=unit.owner_player_id,
            cause_event_no=cause_event_no,
            payload={"unit_id": unit.unit_id, "expired_count": expired_count, "duration": "turn"},
        )
