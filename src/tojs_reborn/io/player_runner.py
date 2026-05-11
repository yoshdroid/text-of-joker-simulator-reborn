from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Protocol, TextIO

from .protocol import action_selected_message, choice_request_message, choice_selected_message, decode_message, encode_message


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
        self.last_fallback_reason = None
        request_id = f"{player_id}:action"
        self.transport.write_line(
            encode_message(
                {
                    "type": "request_action",
                    "request_id": request_id,
                    "player_id": player_id,
                    "legal_actions": legal_actions,
                }
            )
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
        self.last_fallback_reason = None
        self.transport.write_line(
            encode_message(
                choice_request_message(
                    request_id=request_id,
                    player_id=player_id,
                    choice=choice,
                    legal_choices=legal_choices,
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


def encode_action_response(action: dict, *, request_id: str, player_id: str) -> str:
    return encode_message(action_selected_message(action, request_id=request_id, player_id=player_id))


def encode_choice_response(choice: dict, *, request_id: str, player_id: str) -> str:
    return encode_message(choice_selected_message(choice, request_id=request_id, player_id=player_id))
