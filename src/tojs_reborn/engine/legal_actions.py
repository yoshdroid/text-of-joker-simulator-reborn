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
    actions.extend(_override_actions(state, player_id))
    actions.extend(_attack_actions(state, player_id))
    actions.append({"type": "pass"})
    return actions


def list_block_actions(state: GameState, defender_player_id: str, attacker_unit_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [{"type": "no_block", "attacker_unit_id": attacker_unit_id}]
    player = state.players[defender_player_id]
    for unit_id in player.battlefield.units:
        unit = state.units.get(unit_id)
        if unit is not None and not unit.exhausted:
            actions.append(
                {
                    "type": "block",
                    "attacker_unit_id": attacker_unit_id,
                    "blocker_unit_id": unit_id,
                }
            )
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


def _override_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    player = state.players[player_id]
    actions = []
    for target_card_instance_id in player.hand.cards:
        target = state.card_instances[target_card_instance_id]
        if target.level >= 3:
            continue
        for material_card_instance_id in player.hand.cards:
            if material_card_instance_id == target_card_instance_id:
                continue
            material = state.card_instances[material_card_instance_id]
            if material.card_no == target.card_no:
                actions.append(
                    {
                        "type": "override_card",
                        "target_card_instance_id": target_card_instance_id,
                        "material_card_instance_id": material_card_instance_id,
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
        actions.append({"type": "attack", "attacker_unit_id": unit_id, "defender_player_id": rival.player_id})
    return actions
