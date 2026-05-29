from __future__ import annotations

from typing import Any

from tojs_reborn.engine.rules import get_unit_base_bp, get_unit_bp, get_unit_modified_bp
from tojs_reborn.engine.state import CardDefinition, GameState


def build_public_state(state: GameState, viewer_player_id: str) -> dict[str, Any]:
    return {
        "round_no": state.round_no,
        "turn_no": state.turn_no,
        "turn_player_id": state.turn_player_id,
        "players": {
            player_id: _public_player_state(state, player_id, viewer_player_id)
            for player_id in sorted(state.players)
        },
    }


def build_private_view(state: GameState, viewer_player_id: str) -> dict[str, Any]:
    player = state.players[viewer_player_id]
    return {
        "player_id": viewer_player_id,
        "hand": [_card_instance_view(state, card_instance_id) for card_instance_id in player.hand.cards],
        "trigger_zone": [_card_instance_view(state, card_instance_id) for card_instance_id in player.trigger_zone.cards],
        "deck_count": len(player.deck.cards),
    }


def state_revision(state: GameState) -> int:
    return len(state.event_store.events)


def card_instance_public_view(state: GameState, card_instance_id: str) -> dict[str, Any]:
    return _card_instance_view(state, card_instance_id)


def unit_public_view(state: GameState, unit_id: str) -> dict[str, Any]:
    unit = state.units[unit_id]
    card = state.card_catalog[unit.card_no]
    base_bp = get_unit_base_bp(state, unit)
    modified_bp = get_unit_modified_bp(state, unit)
    current_bp = get_unit_bp(state, unit)
    return {
        "unit_id": unit.unit_id,
        "card_instance_id": unit.card_instance_id,
        "card_no": unit.card_no,
        "name": card.name,
        "category": card.category,
        "color": card.color,
        "cp": card.cp,
        "level": unit.level,
        "exhausted": unit.exhausted,
        "can_attack": not unit.exhausted and unit.attack_restricted_turn_no != state.turn_no,
        "current_damage": unit.current_damage,
        "base_bp": base_bp,
        "modified_bp": modified_bp,
        "current_bp": current_bp,
        "base_bp_modifiers": list(unit.base_bp_modifiers),
        "bp_modifiers": list(unit.bp_modifiers),
        "keywords": list(unit.keywords),
    }


def card_summary(card: CardDefinition, card_no: str) -> dict[str, Any]:
    return {
        "card_no": card_no,
        "name": card.name,
        "category": card.category,
        "color": card.color,
        "cp": card.cp,
    }


def decorate_choice_request(
    state: GameState,
    player_id: str,
    choice: dict[str, Any],
    legal_choices: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    decorated_choice = dict(choice)
    decorated_choice.setdefault("count", 1)
    decorated_choice.setdefault("required", True)
    decorated_choice.setdefault("display", _choice_display(choice))
    return decorated_choice, [decorate_legal_choice(state, player_id, item) for item in legal_choices]


def decorate_legal_choice(state: GameState, player_id: str, legal_choice: dict[str, Any]) -> dict[str, Any]:
    decorated = dict(legal_choice)
    unit_id = legal_choice.get("unit_id")
    if isinstance(unit_id, str) and unit_id in state.units:
        target = unit_choice_target_view(state, player_id, unit_id)
        decorated["target"] = target
        decorated["display"] = {"label": _unit_choice_label(target)}
    card_instance_id = legal_choice.get("card_instance_id")
    if isinstance(card_instance_id, str) and card_instance_id in state.card_instances:
        target = card_choice_target_view(state, player_id, card_instance_id)
        decorated["target"] = target
        decorated["display"] = {"label": _card_choice_label(target)}
    return decorated


def strip_choice_decoration(choice: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in choice.items() if key not in {"target", "display"}}


def unit_choice_target_view(state: GameState, player_id: str, unit_id: str) -> dict[str, Any]:
    unit = state.units[unit_id]
    card = state.card_catalog[unit.card_no]
    return {
        "type": "unit",
        "controller": unit.owner_player_id,
        "is_owner": unit.owner_player_id == player_id,
        "unit_id": unit.unit_id,
        "card_instance_id": unit.card_instance_id,
        "card_no": unit.card_no,
        "card_name": card.name,
        "level": unit.level,
        "base_bp": get_unit_base_bp(state, unit),
        "modified_bp": get_unit_modified_bp(state, unit),
        "damage": unit.current_damage,
        "current_bp": get_unit_bp(state, unit),
        "exhausted": unit.exhausted,
    }


def card_choice_target_view(state: GameState, player_id: str, card_instance_id: str) -> dict[str, Any]:
    instance = state.card_instances[card_instance_id]
    if instance.card_no in state.joker_catalog:
        joker = state.joker_catalog[instance.card_no]
        return {
            "type": "card",
            "controller": instance.owner_player_id,
            "is_owner": instance.owner_player_id == player_id,
            "card_instance_id": card_instance_id,
            "card_no": instance.card_no,
            "card_name": joker.name,
            "category": "joker",
            "color": "joker",
            "cp": joker.cp,
            "level": instance.level,
        }
    card = state.card_catalog[instance.card_no]
    return {
        "type": "card",
        "controller": instance.owner_player_id,
        "is_owner": instance.owner_player_id == player_id,
        "card_instance_id": card_instance_id,
        "card_no": instance.card_no,
        "card_name": card.name,
        "category": card.category,
        "color": card.color,
        "cp": card.cp,
        "level": instance.level,
    }


def _public_player_state(state: GameState, player_id: str, viewer_player_id: str) -> dict[str, Any]:
    player = state.players[player_id]
    return {
        "life": player.life,
        "current_cp": player.current_cp,
        "joker_no": player.joker_no,
        "joker_gauge": player.joker_gauge,
        "joker_granted": player.joker_granted,
        "hand_count": len(player.hand.cards),
        "deck_count": len(player.deck.cards),
        "discard_pile": [_card_instance_view(state, card_instance_id) for card_instance_id in player.discard_pile.cards],
        "battlefield": [unit_public_view(state, unit_id) for unit_id in player.battlefield.units if unit_id in state.units],
        "trigger_zone": _trigger_zone_view(state, player_id, viewer_player_id),
    }


def _trigger_zone_view(state: GameState, player_id: str, viewer_player_id: str) -> dict[str, Any]:
    cards = state.players[player_id].trigger_zone.cards
    if player_id == viewer_player_id:
        return {
            "count": len(cards),
            "items": [_card_instance_view(state, card_instance_id) for card_instance_id in cards],
        }
    items = []
    for card_instance_id in cards:
        card_no = state.card_instances[card_instance_id].card_no
        card = state.card_catalog[card_no]
        items.append({"color": card.color, "revealed_card_no": None, "revealed_name": None})
    return {"count": len(cards), "items": items}


def _choice_display(choice: dict[str, Any]) -> dict[str, str]:
    if choice.get("type") == "unit":
        count = int(choice.get("count", 1))
        return {"label": f"対象ユニットを{count}体選択"}
    if choice.get("type") == "cost_payment":
        count = int(choice.get("count", 1))
        return {"label": f"コストとして手札を{count}枚選択"}
    return {"label": "選択"}


def _unit_choice_label(target: dict[str, Any]) -> str:
    owner = target["controller"]
    name = target["card_name"]
    level = target["level"]
    current_bp = target["current_bp"]
    damage = target["damage"]
    return f"{owner} {name} LV{level} BP{current_bp} DMG{damage}"


def _card_choice_label(target: dict[str, Any]) -> str:
    owner = target["controller"]
    name = target["card_name"]
    card_no = target["card_no"]
    return f"{owner} {name} {card_no}"


def _card_instance_view(state: GameState, card_instance_id: str) -> dict[str, Any]:
    instance = state.card_instances[card_instance_id]
    if instance.card_no in state.joker_catalog:
        joker = state.joker_catalog[instance.card_no]
        return {
            "card_no": instance.card_no,
            "name": joker.name,
            "category": "joker",
            "color": "joker",
            "cp": joker.cp,
            "card_instance_id": card_instance_id,
            "level": instance.level,
        }
    card = state.card_catalog[instance.card_no]
    view = card_summary(card, instance.card_no)
    view["card_instance_id"] = card_instance_id
    view["level"] = instance.level
    return view
