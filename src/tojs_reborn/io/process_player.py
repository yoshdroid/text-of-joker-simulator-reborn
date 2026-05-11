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
        return self.player.choose_action(player_id, legal_actions)

    def choose_choice(
        self,
        player_id: str,
        *,
        request_id: str,
        choice: dict,
        legal_choices: list[dict],
    ) -> dict:
        return self.player.choose_choice(
            player_id,
            request_id=request_id,
            choice=choice,
            legal_choices=legal_choices,
        )

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
