from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


PASS_ACTION_TYPES = {"pass", "no_block", "pass_window"}


def choose_sample_action(legal_actions: list[dict[str, Any]], mode: str, rng: random.Random | None = None) -> dict[str, Any]:
    if not legal_actions:
        raise ValueError("legal_actions must not be empty")
    if mode == "pass":
        return choose_pass_action(legal_actions)
    if mode == "random":
        return (rng or random.Random(0)).choice(legal_actions)
    if mode in {"intercept_all", "intercept-all"}:
        return choose_intercept_all_action(legal_actions)
    if mode == "aggressive":
        return choose_aggressive_action(legal_actions)
    return choose_first_action(legal_actions)


def choose_sample_choice(legal_choices: list[dict[str, Any]], mode: str, rng: random.Random | None = None) -> dict[str, Any]:
    if not legal_choices:
        raise ValueError("legal_choices must not be empty")
    if mode == "random":
        return (rng or random.Random(0)).choice(legal_choices)
    return legal_choices[0]


def choose_first_action(legal_actions: list[dict[str, Any]]) -> dict[str, Any]:
    for action in legal_actions:
        if action.get("type") not in PASS_ACTION_TYPES:
            return action
    return legal_actions[0]


def choose_pass_action(legal_actions: list[dict[str, Any]]) -> dict[str, Any]:
    for action in legal_actions:
        if action.get("type") in PASS_ACTION_TYPES:
            return action
    return legal_actions[0]


def choose_aggressive_action(legal_actions: list[dict[str, Any]]) -> dict[str, Any]:
    priorities = [
        _is_attack,
        _is_block,
        _is_activate_intercept,
        _is_evolve_drive,
        _is_normal_drive,
        _is_set_trigger,
        _is_override,
        _is_non_pass,
    ]
    for predicate in priorities:
        for action in legal_actions:
            if predicate(action):
                return action
    return legal_actions[0]


def choose_intercept_all_action(legal_actions: list[dict[str, Any]]) -> dict[str, Any]:
    for action in legal_actions:
        if _is_activate_intercept(action):
            return action
    return choose_aggressive_action(legal_actions)


@dataclass
class SampleStrategyPlayer:
    mode: str
    seed: int = 0
    player_id_hint: str = ""
    rng_by_player: dict[str, random.Random] = field(default_factory=dict)

    def choose_action(self, player_id: str, legal_actions: list[dict[str, Any]]) -> dict[str, Any]:
        return choose_sample_action(legal_actions, self.mode, self._rng(player_id))

    def choose_choice(
        self,
        player_id: str,
        *,
        request_id: str,
        choice: dict[str, Any],
        legal_choices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return choose_sample_choice(legal_choices, self.mode, self._rng(player_id))

    def choose_mulligan(self, player_id: str) -> bool:
        return False

    def _rng(self, player_id: str) -> random.Random:
        if player_id not in self.rng_by_player:
            self.rng_by_player[player_id] = random.Random(_derive_seed(self.seed, self.player_id_hint or player_id))
        return self.rng_by_player[player_id]


def _derive_seed(seed: int, player_id: str) -> int:
    value = int(seed) & 0xFFFFFFFF
    for char in player_id:
        value = ((value * 131) + ord(char)) & 0xFFFFFFFF
    return value


def _is_attack(action: dict[str, Any]) -> bool:
    return action.get("type") == "attack"


def _is_block(action: dict[str, Any]) -> bool:
    return action.get("type") == "block"


def _is_activate_intercept(action: dict[str, Any]) -> bool:
    return action.get("type") == "activate_intercept"


def _is_evolve_drive(action: dict[str, Any]) -> bool:
    return action.get("type") == "drive_unit" and "evolve_target_unit_id" in action


def _is_normal_drive(action: dict[str, Any]) -> bool:
    return action.get("type") == "drive_unit" and "evolve_target_unit_id" not in action


def _is_set_trigger(action: dict[str, Any]) -> bool:
    return action.get("type") == "set_trigger"


def _is_override(action: dict[str, Any]) -> bool:
    return action.get("type") == "override_card"


def _is_non_pass(action: dict[str, Any]) -> bool:
    return action.get("type") not in PASS_ACTION_TYPES
