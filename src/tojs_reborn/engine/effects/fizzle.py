from __future__ import annotations

from tojs_reborn.engine.events import FactEvent
from tojs_reborn.engine.state import GameState


EFFECT_FIZZLED_REASONS = {
    "no_valid_target",
    "selector_missing",
    "target_already_exhausted",
    "target_not_exhausted",
    "target_not_on_battlefield",
}


def append_effect_fizzled(
    state: GameState,
    actor_player_id: str,
    ability_event: FactEvent,
    step: dict,
    reason: str,
) -> None:
    if reason not in EFFECT_FIZZLED_REASONS:
        raise ValueError(f"unknown effect_fizzled reason: {reason}")
    state.event_store.append(
        "effect_fizzled",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=actor_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={"effect": step.get("effect"), "reason": reason},
    )
