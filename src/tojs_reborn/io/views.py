from __future__ import annotations

from typing import Any

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
        "current_damage": unit.current_damage,
        "bp_modifiers": list(unit.bp_modifiers),
    }


def card_summary(card: CardDefinition, card_no: str) -> dict[str, Any]:
    return {
        "card_no": card_no,
        "name": card.name,
        "category": card.category,
        "color": card.color,
        "cp": card.cp,
    }


def _public_player_state(state: GameState, player_id: str, viewer_player_id: str) -> dict[str, Any]:
    player = state.players[player_id]
    return {
        "life": player.life,
        "current_cp": player.current_cp,
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


def _card_instance_view(state: GameState, card_instance_id: str) -> dict[str, Any]:
    instance = state.card_instances[card_instance_id]
    card = state.card_catalog[instance.card_no]
    view = card_summary(card, instance.card_no)
    view["card_instance_id"] = card_instance_id
    view["level"] = instance.level
    return view
