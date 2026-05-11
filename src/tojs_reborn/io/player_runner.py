from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Protocol, TextIO

from tojs_reborn.engine.state import GameState

from .protocol import (
    action_selected_message,
    choice_request_message,
    choice_selected_message,
    decode_message,
    encode_message,
    request_mulligan_message,
    request_action_message,
    mulligan_selected_message,
    state_update_message,
)


DEFAULT_RESPONSE_TIMEOUT_SECONDS = 0.5


class JsonLineTransport(Protocol):
    def write_line(self, line: str) -> None:
        ...

    def read_line(self, timeout_seconds: float) -> str | None:
        ...


@dataclass
class TextIOJsonLineTransport:
    reader: TextIO
    writer: TextIO

    def write_line(self, line: str) -> None:
        self.writer.write(line)
        self.writer.flush()

    def read_line(self, timeout_seconds: float) -> str | None:
        result_queue: queue.Queue[str | None] = queue.Queue(maxsize=1)

        def read() -> None:
            result_queue.put(self.reader.readline() or None)

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        try:
            return result_queue.get(timeout=timeout_seconds)
        except queue.Empty:
            return None


@dataclass
class JsonLinePlayer:
    transport: JsonLineTransport
    timeout_seconds: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS
    last_fallback_reason: str | None = None

    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        return self.choose_action_with_state(player_id, legal_actions, state=None)

    def choose_action_with_state(self, player_id: str, legal_actions: list[dict], *, state: GameState | None) -> dict:
        self.last_fallback_reason = None
        request_id = f"{player_id}:action"
        if state is not None:
            self.transport.write_line(
                encode_message(
                    state_update_message(
                        state,
                        player_id,
                        request_id=f"{player_id}:state:{len(state.event_store.events)}",
                    )
                )
            )
            request = request_action_message(state, player_id, request_id=request_id)
            request["legal_actions"] = legal_actions
        else:
            request = {
                "type": "request_action",
                "request_id": request_id,
                "player_id": player_id,
                "legal_actions": legal_actions,
            }
        self.transport.write_line(
            encode_message(request)
        )
        line = self.transport.read_line(self.timeout_seconds)
        if line is None:
            self.last_fallback_reason = "timeout"
            return legal_actions[0]
        try:
            message = decode_message(line)
        except (ValueError, TypeError):
            self.last_fallback_reason = "invalid_json"
            return legal_actions[0]
        if message.get("type") != "action_selected":
            self.last_fallback_reason = "unexpected_message_type"
            return legal_actions[0]
        if message.get("request_id") != request_id:
            self.last_fallback_reason = "request_id_mismatch"
            return legal_actions[0]
        action = message.get("action")
        if not isinstance(action, dict) or action not in legal_actions:
            self.last_fallback_reason = "illegal_action"
            return legal_actions[0]
        return action

    def choose_choice(
        self,
        player_id: str,
        *,
        request_id: str,
        choice: dict,
        legal_choices: list[dict],
    ) -> dict:
        return self.choose_choice_with_state(
            player_id,
            request_id=request_id,
            choice=choice,
            legal_choices=legal_choices,
            state=None,
        )

    def choose_choice_with_state(
        self,
        player_id: str,
        *,
        request_id: str,
        choice: dict,
        legal_choices: list[dict],
        state: GameState | None,
    ) -> dict:
        self.last_fallback_reason = None
        if state is not None:
            self.transport.write_line(
                encode_message(
                    state_update_message(
                        state,
                        player_id,
                        request_id=f"{player_id}:state:{len(state.event_store.events)}",
                    )
                )
            )
        self.transport.write_line(
            encode_message(
                choice_request_message(
                    request_id=request_id,
                    player_id=player_id,
                    choice=choice,
                    legal_choices=legal_choices,
                    state=state,
                )
            )
        )
        line = self.transport.read_line(self.timeout_seconds)
        if line is None:
            self.last_fallback_reason = "timeout"
            return legal_choices[0]
        try:
            message = decode_message(line)
        except (ValueError, TypeError):
            self.last_fallback_reason = "invalid_json"
            return legal_choices[0]
        if message.get("type") != "choice_selected":
            self.last_fallback_reason = "unexpected_message_type"
            return legal_choices[0]
        if message.get("request_id") != request_id:
            self.last_fallback_reason = "request_id_mismatch"
            return legal_choices[0]
        selected_choice = message.get("choice")
        if not isinstance(selected_choice, dict) or selected_choice not in legal_choices:
            self.last_fallback_reason = "illegal_choice"
            return legal_choices[0]
        return selected_choice

    def choose_mulligan(self, player_id: str) -> bool:
        return self.choose_mulligan_with_state(player_id, state=None)

    def choose_mulligan_with_state(self, player_id: str, *, state: GameState | None) -> bool:
        self.last_fallback_reason = None
        request_id = f"{player_id}:mulligan"
        if state is None:
            request = {
                "type": "request_mulligan",
                "request_id": request_id,
                "player_id": player_id,
            }
        else:
            request = request_mulligan_message(state, player_id, request_id=request_id)
        self.transport.write_line(encode_message(request))
        line = self.transport.read_line(self.timeout_seconds)
        if line is None:
            self.last_fallback_reason = "timeout"
            return False
        try:
            message = decode_message(line)
        except (ValueError, TypeError):
            self.last_fallback_reason = "invalid_json"
            return False
        if message.get("type") != "mulligan_selected":
            self.last_fallback_reason = "unexpected_message_type"
            return False
        if message.get("request_id") != request_id:
            self.last_fallback_reason = "request_id_mismatch"
            return False
        return bool(message.get("do_mulligan", False))


def encode_action_response(action: dict, *, request_id: str, player_id: str) -> str:
    return encode_message(action_selected_message(action, request_id=request_id, player_id=player_id))


def encode_choice_response(choice: dict, *, request_id: str, player_id: str) -> str:
    return encode_message(choice_selected_message(choice, request_id=request_id, player_id=player_id))


def encode_mulligan_response(do_mulligan: bool, *, request_id: str, player_id: str) -> str:
    return encode_message(mulligan_selected_message(request_id=request_id, player_id=player_id, do_mulligan=do_mulligan))
