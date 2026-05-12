from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .player_runner import DEFAULT_RESPONSE_TIMEOUT_SECONDS, JsonLinePlayer, TextIOJsonLineTransport


@dataclass
class ProcessJsonLinePlayer:
    process: subprocess.Popen
    player: JsonLinePlayer

    @property
    def last_fallback_reason(self) -> str | None:
        return self.player.last_fallback_reason

    @last_fallback_reason.setter
    def last_fallback_reason(self, value: str | None) -> None:
        self.player.last_fallback_reason = value

    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        if self._process_is_closed():
            self.player.last_fallback_reason = "process_closed"
            return legal_actions[0]
        response = self.player.choose_action(player_id, legal_actions)
        self._mark_process_closed_fallback()
        return response

    def send_state_update(self, player_id: str, *, state, request_id: str, event: dict | None = None) -> None:
        if self._process_is_closed():
            return
        self.player.send_state_update(player_id, state=state, request_id=request_id, event=event)
        self._mark_process_closed_fallback()

    def choose_action_with_state(
        self,
        player_id: str,
        legal_actions: list[dict],
        *,
        state,
        request_context: dict | None = None,
    ) -> dict:
        if self._process_is_closed():
            self.player.last_fallback_reason = "process_closed"
            return legal_actions[0]
        response = self.player.choose_action_with_state(
            player_id,
            legal_actions,
            state=state,
            request_context=request_context,
        )
        self._mark_process_closed_fallback()
        return response

    def choose_choice(
        self,
        player_id: str,
        *,
        request_id: str,
        choice: dict,
        legal_choices: list[dict],
    ) -> dict:
        if self._process_is_closed():
            self.player.last_fallback_reason = "process_closed"
            return legal_choices[0]
        response = self.player.choose_choice(
            player_id,
            request_id=request_id,
            choice=choice,
            legal_choices=legal_choices,
        )
        self._mark_process_closed_fallback()
        return response

    def choose_choice_with_state(
        self,
        player_id: str,
        *,
        request_id: str,
        choice: dict,
        legal_choices: list[dict],
        state,
    ) -> dict:
        if self._process_is_closed():
            self.player.last_fallback_reason = "process_closed"
            return legal_choices[0]
        response = self.player.choose_choice_with_state(
            player_id,
            request_id=request_id,
            choice=choice,
            legal_choices=legal_choices,
            state=state,
        )
        self._mark_process_closed_fallback()
        return response

    def choose_mulligan(self, player_id: str) -> bool:
        if self._process_is_closed():
            self.player.last_fallback_reason = "process_closed"
            return False
        response = self.player.choose_mulligan(player_id)
        self._mark_process_closed_fallback()
        return response

    def choose_mulligan_with_state(self, player_id: str, *, state) -> bool:
        if self._process_is_closed():
            self.player.last_fallback_reason = "process_closed"
            return False
        response = self.player.choose_mulligan_with_state(player_id, state=state)
        self._mark_process_closed_fallback()
        return response

    def _mark_process_closed_fallback(self) -> None:
        if self.player.last_fallback_reason == "timeout" and self.process.poll() is not None:
            self.player.last_fallback_reason = "process_closed"

    def _process_is_closed(self) -> bool:
        return self.process.poll() is not None

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


def start_process_player(
    command: str,
    *,
    timeout_seconds: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
) -> ProcessJsonLinePlayer:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=True,
    )
    if process.stdin is None or process.stdout is None:
        process.kill()
        raise RuntimeError("failed to open player stdin/stdout")
    player = JsonLinePlayer(
        TextIOJsonLineTransport(process.stdout, process.stdin),
        timeout_seconds=timeout_seconds,
    )
    return ProcessJsonLinePlayer(process=process, player=player)
