from __future__ import annotations

from typing import Any

from .state import GameState


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
