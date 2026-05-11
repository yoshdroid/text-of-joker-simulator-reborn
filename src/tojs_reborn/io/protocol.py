from __future__ import annotations

import json
from typing import Any

from tojs_reborn.engine.state import GameState

from .views import build_private_view, build_public_state, decorate_choice_request, state_revision
from tojs_reborn.engine.legal_actions import list_legal_actions


KNOWN_MESSAGE_TYPES = {
    "hello",
    "state_update",
    "request_action",
    "action_selected",
    "choice_request",
    "choice_selected",
    "request_mulligan",
    "mulligan_selected",
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
    public_state = build_public_state(state, player_id)
    private_view = build_private_view(state, player_id)
    return {
        "type": "state_update",
        "request_id": request_id,
        "player_id": player_id,
        "state_revision": state_revision(state),
        "public_state": public_state,
        "private_view": private_view,
        "state": public_state,
    }


def state_update_message(state: GameState, player_id: str, *, request_id: str) -> dict[str, Any]:
    return public_state_message(state, player_id, request_id=request_id)


def request_action_message(state: GameState, player_id: str, *, request_id: str) -> dict[str, Any]:
    public_state = build_public_state(state, player_id)
    private_view = build_private_view(state, player_id)
    return {
        "type": "request_action",
        "request_id": request_id,
        "player_id": player_id,
        "state_revision": state_revision(state),
        "public_state": public_state,
        "private_view": private_view,
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
    state: GameState | None = None,
) -> dict[str, Any]:
    request_choice = dict(choice)
    request_legal_choices = list(legal_choices)
    if state is not None:
        request_choice, request_legal_choices = decorate_choice_request(state, player_id, choice, legal_choices)
    message = {
        "type": "choice_request",
        "request_id": request_id,
        "player_id": player_id,
        "choice": request_choice,
        "display": request_choice.get("display", {"label": "選択"}),
        "legal_choices": request_legal_choices,
    }
    if state is not None:
        message["state_revision"] = state_revision(state)
        message["public_state"] = build_public_state(state, player_id)
        message["private_view"] = build_private_view(state, player_id)
    return message


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


def request_mulligan_message(state: GameState, player_id: str, *, request_id: str) -> dict[str, Any]:
    return {
        "type": "request_mulligan",
        "request_id": request_id,
        "player_id": player_id,
        "state_revision": state_revision(state),
        "public_state": build_public_state(state, player_id),
        "private_view": build_private_view(state, player_id),
    }


def mulligan_selected_message(*, request_id: str, player_id: str, do_mulligan: bool) -> dict[str, Any]:
    return {
        "type": "mulligan_selected",
        "request_id": request_id,
        "player_id": player_id,
        "do_mulligan": do_mulligan,
    }
