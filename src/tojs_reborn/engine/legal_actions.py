from __future__ import annotations

from typing import Any

from .rules import MAX_BATTLEFIELD_UNITS, MAX_TRIGGER_ZONE_CARDS, opponent_id
from .state import GameState
from .unit_drive_cost import unit_drive_cost
from tojs_reborn.io.views import card_instance_public_view, unit_public_view


def list_legal_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    if state.turn_player_id != player_id:
        return [_pass_action()]
    actions: list[dict[str, Any]] = []
    actions.extend(_drive_actions(state, player_id))
    actions.extend(_set_trigger_actions(state, player_id))
    actions.extend(_override_actions(state, player_id))
    actions.extend(_attack_actions(state, player_id))
    actions.append(_pass_action())
    return actions


def list_block_actions(state: GameState, defender_player_id: str, attacker_unit_id: str) -> list[dict[str, Any]]:
    attacker = state.units[attacker_unit_id]
    actions: list[dict[str, Any]] = [
        {
            "type": "no_block",
            "attacker_unit_id": attacker_unit_id,
            "unit": unit_public_view(state, attacker_unit_id),
            "display": {
                "label": f"{state.card_catalog[attacker.card_no].name}をブロックしない",
            },
        }
    ]
    player = state.players[defender_player_id]
    for unit_id in player.battlefield.units:
        unit = state.units.get(unit_id)
        if unit is not None and not unit.exhausted:
            actions.append(
                {
                    "type": "block",
                    "attacker_unit_id": attacker_unit_id,
                    "blocker_unit_id": unit_id,
                    "unit": unit_public_view(state, unit_id),
                    "attacker": unit_public_view(state, attacker_unit_id),
                    "display": {
                        "label": f"{state.card_catalog[unit.card_no].name}でブロックする",
                    },
                }
            )
    return actions


def _drive_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    player = state.players[player_id]
    actions = []
    for card_instance_id in player.hand.cards:
        card_no = state.card_instances[card_instance_id].card_no
        card = state.card_catalog[card_no]
        cost_info = unit_drive_cost(state, player_id, card_instance_id)
        if (
            card.category == "unit"
            and player.current_cp >= cost_info.effective_cost
            and len(player.battlefield.units) < MAX_BATTLEFIELD_UNITS
        ):
            actions.append(
                {
                    "type": "drive_unit",
                    "card_instance_id": card_instance_id,
                    "base_cp_cost": cost_info.base_cost,
                    "cp_cost": cost_info.effective_cost,
                    "cost_reduction": cost_info.reduction,
                    "cost_reduction_card_instance_id": cost_info.reducer_card_instance_id,
                    "card": card_instance_public_view(state, card_instance_id),
                    "display": {
                        "label": f"{card.name}をフィールドに出す",
                        "card_no": card_no,
                        "card_name": card.name,
                        "category": card.category,
                        "cp": cost_info.effective_cost,
                        "base_cp": cost_info.base_cost,
                        "cost_reduction": cost_info.reduction,
                    },
                }
            )
        elif card.category == "evolve" and player.current_cp >= (card.cp or 0):
            for unit_id in player.battlefield.units:
                unit = state.units.get(unit_id)
                if unit is None:
                    continue
                target_card = state.card_catalog[unit.card_no]
                if target_card.color != card.color:
                    continue
                actions.append(
                    {
                        "type": "drive_unit",
                        "card_instance_id": card_instance_id,
                        "evolve_target_unit_id": unit_id,
                        "card": card_instance_public_view(state, card_instance_id),
                        "target_unit": unit_public_view(state, unit_id),
                        "display": {
                            "label": f"{state.card_catalog[unit.card_no].name}に{card.name}を重ねて進化召喚する",
                            "card_no": card_no,
                            "card_name": card.name,
                            "category": card.category,
                            "cp": card.cp,
                            "target_unit_id": unit_id,
                        },
                    }
                )
    return actions


def _set_trigger_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    player = state.players[player_id]
    if len(player.trigger_zone.cards) >= MAX_TRIGGER_ZONE_CARDS:
        return []
    actions = []
    for card_instance_id in player.hand.cards:
        card_no = state.card_instances[card_instance_id].card_no
        card = state.card_catalog[card_no]
        if card.category in {"trigger", "intercept", "unit"}:
            actions.append(
                {
                    "type": "set_trigger",
                    "card_instance_id": card_instance_id,
                    "card": card_instance_public_view(state, card_instance_id),
                    "display": {
                        "label": f"{card.name}をトリガーゾーンにセットする",
                        "card_no": card_no,
                        "card_name": card.name,
                        "category": card.category,
                        "cp": card.cp,
                    },
                }
            )
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
                        "target_card": card_instance_public_view(state, target_card_instance_id),
                        "material_card": card_instance_public_view(state, material_card_instance_id),
                        "display": {
                            "label": f"{state.card_catalog[target.card_no].name}をオーバーライドする",
                            "card_no": target.card_no,
                            "card_name": state.card_catalog[target.card_no].name,
                            "category": state.card_catalog[target.card_no].category,
                            "cp": state.card_catalog[target.card_no].cp,
                        },
                    }
                )
    return actions


def _attack_actions(state: GameState, player_id: str) -> list[dict[str, Any]]:
    if state.turn_no == 1 and player_id == "P1":
        return []
    player = state.players[player_id]
    rival = state.players[opponent_id(player_id)]
    actions = []
    for unit_id in player.battlefield.units:
        unit = state.units.get(unit_id)
        if unit is None or unit.exhausted:
            continue
        if unit.attack_restricted_turn_no == state.turn_no:
            continue
        card = state.card_catalog[unit.card_no]
        actions.append(
            {
                "type": "attack",
                "attacker_unit_id": unit_id,
                "defender_player_id": rival.player_id,
                "unit": unit_public_view(state, unit_id),
                "display": {"label": f"{card.name}でアタックする"},
            }
        )
    return actions


def _pass_action() -> dict[str, Any]:
    return {
        "type": "pass",
        "display": {"label": "ターンを終了する"},
    }
