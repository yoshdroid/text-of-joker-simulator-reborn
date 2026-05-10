from __future__ import annotations

from typing import Any

from .rules import opponent_id
from .state import GameState


def list_legal_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    if state.turn_player_id != player_id:
        return [{"type": "pass"}]
    actions: list[dict[str, Any]] = []
    actions.extend(_drive_actions(state, player_id))
    actions.extend(_set_trigger_actions(state, player_id))
    actions.extend(_overclock_actions(state, player_id))
    actions.extend(_attack_actions(state, player_id))
    actions.append({"type": "pass"})
    return actions


def _drive_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    player = state.players[player_id]
    actions = []
    for card_instance_id in player.hand.cards:
        card_no = state.card_instances[card_instance_id].card_no
        card = state.card_catalog[card_no]
        if card.category == "unit" and player.current_cp >= (card.cp or 0):
            actions.append({"type": "drive_unit", "card_instance_id": card_instance_id})
    return actions


def _set_trigger_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    player = state.players[player_id]
    actions = []
    for card_instance_id in player.hand.cards:
        card_no = state.card_instances[card_instance_id].card_no
        card = state.card_catalog[card_no]
        if card.category in {"trigger", "intercept"}:
            actions.append({"type": "set_trigger", "card_instance_id": card_instance_id})
    return actions


def _overclock_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    player = state.players[player_id]
    actions = []
    for card_instance_id in player.hand.cards:
        card_no = state.card_instances[card_instance_id].card_no
        for unit_id in player.battlefield.units:
            unit = state.units.get(unit_id)
            if unit is not None and unit.card_no == card_no and unit.level < 3:
                actions.append(
                    {
                        "type": "overclock_unit",
                        "card_instance_id": card_instance_id,
                        "target_unit_id": unit_id,
                    }
                )
    return actions


def _attack_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    player = state.players[player_id]
    rival = state.players[opponent_id(player_id)]
    actions = []
    for unit_id in player.battlefield.units:
        unit = state.units.get(unit_id)
        if unit is None or unit.exhausted:
            continue
        actions.append({"type": "attack_player", "attacker_unit_id": unit_id})
        for blocker_unit_id in rival.battlefield.units:
            if blocker_unit_id in state.units:
                actions.append(
                    {
                        "type": "attack_unit",
                        "attacker_unit_id": unit_id,
                        "blocker_unit_id": blocker_unit_id,
                    }
                )
    return actions
