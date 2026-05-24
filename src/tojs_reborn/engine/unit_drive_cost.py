from __future__ import annotations

from dataclasses import dataclass

from .state import GameState


@dataclass(frozen=True)
class UnitDriveCost:
    base_cost: int
    effective_cost: int
    reduction: int
    reducer_card_instance_id: str | None


def unit_drive_cost(state: GameState, player_id: str, card_instance_id: str) -> UnitDriveCost:
    """Return the CP cost after trigger-zone unit/evolve reduction."""

    instance = state.card_instances[card_instance_id]
    card = state.card_catalog[instance.card_no]
    base_cost = card.cp or 0
    reduction = 0
    reducer_card_instance_id: str | None = None
    if card.category in {"unit", "evolve"}:
        reducer_card_instance_id = first_unit_drive_cost_reducer(state, player_id, card.color)
        if reducer_card_instance_id is not None:
            reduction = 1
    return UnitDriveCost(
        base_cost=base_cost,
        effective_cost=max(0, base_cost - reduction),
        reduction=reduction,
        reducer_card_instance_id=reducer_card_instance_id,
    )


def first_unit_drive_cost_reducer(state: GameState, player_id: str, color: str) -> str | None:
    player = state.players[player_id]
    for card_instance_id in player.trigger_zone.cards:
        instance = state.card_instances[card_instance_id]
        card = state.card_catalog[instance.card_no]
        if card.category in {"unit", "evolve"} and card.color == color:
            return card_instance_id
    return None
