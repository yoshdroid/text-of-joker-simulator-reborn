from __future__ import annotations

import json
from typing import Any

from tojs_reborn.engine.legal_actions import list_legal_actions
from tojs_reborn.engine.replay import state_digest
from tojs_reborn.engine.state import GameState


KNOWN_MESSAGE_TYPES = {
    "hello",
    "state_update",
    "request_action",
    "action_selected",
    "choice_request",
    "choice_selected",
    "error",
    "game_over",
}


def encode_message(message: dict[str, Any]) -> str:
    validate_message(message)
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"


def decode_message(line: str) -> dict[str, Any]:
    message = json.loads(line)
    validate_message(message)
    return message


def validate_message(message: dict[str, Any]) -> None:
    if not isinstance(message, dict):
        raise ValueError("protocol message must be an object")
    if message.get("type") not in KNOWN_MESSAGE_TYPES:
        raise ValueError(f"unknown protocol message type: {message.get('type')}")
    if "request_id" in message and not isinstance(message["request_id"], str):
        raise ValueError("request_id must be a string")


def public_state_message(state: GameState, player_id: str, *, request_id: str) -> dict[str, Any]:
    digest = state_digest(state)
    return {
        "type": "state_update",
        "request_id": request_id,
        "player_id": player_id,
        "state": _visible_state(digest, player_id),
    }


def request_action_message(state: GameState, player_id: str, *, request_id: str) -> dict[str, Any]:
    return {
        "type": "request_action",
        "request_id": request_id,
        "player_id": player_id,
        "legal_actions": list_legal_actions(state, player_id),
    }


def action_selected_message(action: dict[str, Any], *, request_id: str, player_id: str) -> dict[str, Any]:
    return {
        "type": "action_selected",
        "request_id": request_id,
        "player_id": player_id,
        "action": action,
    }


def choice_request_message(
    *,
    request_id: str,
    player_id: str,
    choice: dict[str, Any],
    legal_choices: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "choice_request",
        "request_id": request_id,
        "player_id": player_id,
        "choice": choice,
        "legal_choices": legal_choices,
    }


def choice_selected_message(choice: dict[str, Any], *, request_id: str, player_id: str) -> dict[str, Any]:
    return {
        "type": "choice_selected",
        "request_id": request_id,
        "player_id": player_id,
        "choice": choice,
    }


def game_over_message(winner_player_id: str | None, *, request_id: str) -> dict[str, Any]:
    return {
        "type": "game_over",
        "request_id": request_id,
        "winner_player_id": winner_player_id,
    }


def _visible_state(digest: dict[str, Any], viewer_player_id: str) -> dict[str, Any]:
    visible = json.loads(json.dumps(digest, ensure_ascii=False))
    for player_id, player in visible["players"].items():
        if player_id != viewer_player_id:
            player["hand"] = {"count": len(player["hand"])}
            player["deck"] = {"count": len(player["deck"])}
            player["trigger_zone"] = _visible_trigger_zone(digest, player["trigger_zone"])
    return visible


def _visible_trigger_zone(digest: dict[str, Any], card_instance_ids: list[str]) -> dict[str, Any]:
    items = []
    for card_instance_id in card_instance_ids:
        card_no = digest["card_instances"][card_instance_id]["card_no"]
        card = digest["card_catalog"][card_no]
        item = {
            "color": card["color"],
            "revealed_card_no": None,
        }
        items.append(item)
    return {
        "count": len(card_instance_ids),
        "colors": [item["color"] for item in items],
        "items": items,
    }
