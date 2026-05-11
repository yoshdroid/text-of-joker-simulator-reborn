from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Protocol, TextIO

from .protocol import action_selected_message, decode_message, encode_message


DEFAULT_RESPONSE_TIMEOUT_SECONDS = 1.0


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

    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
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
            return legal_actions[0]
        try:
            message = decode_message(line)
        except (ValueError, TypeError):
            return legal_actions[0]
        if message.get("type") != "action_selected":
            return legal_actions[0]
        if message.get("request_id") != request_id:
            return legal_actions[0]
        action = message.get("action")
        if not isinstance(action, dict) or action not in legal_actions:
            return legal_actions[0]
        return action


def encode_action_response(action: dict, *, request_id: str, player_id: str) -> str:
    return encode_message(action_selected_message(action, request_id=request_id, player_id=player_id))
