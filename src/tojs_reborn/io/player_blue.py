from __future__ import annotations

import argparse
import sys
from typing import Any

from .protocol import (
    action_selected_message,
    choice_selected_message,
    decode_message,
    encode_message,
    mulligan_selected_message,
)


SET_PRIORITY = {
    "1-0-092": 120,
    "1-0-089": 110,
    "1-0-091": 105,
    "1-0-094": 95,
    "1-0-090": 90,
    "1-0-061": 86,
    "1-0-062": 84,
    "1-0-059": 80,
    "1-0-069": 72,
}

DRIVE_PRIORITY = {
    "1-0-039": 130,
    "1-0-035": 122,
    "1-0-037": 116,
    "1-0-033": 104,
    "1-0-032": 96,
    "1-0-028": 88,
    "1-0-029": 82,
    "1-0-027": 78,
}

INTERCEPT_PRIORITY = {
    "1-0-092": 130,
    "1-0-089": 118,
    "1-0-091": 112,
    "1-0-094": 105,
    "1-0-090": 96,
    "1-0-069": 70,
}

LOW_COST_UNITS = {"1-0-027", "1-0-028", "1-0-029", "1-0-032"}
PIG_UNITS = {"1-0-027", "1-0-028", "1-0-029", "1-0-037"}
PASS_ACTION_TYPES = {"pass", "no_block", "pass_window"}


class BlueControlPlayer:
    def __init__(self, *, max_mulligans: int = 2) -> None:
        self.max_mulligans = max_mulligans
        self.mulligans_by_player: dict[str, int] = {}

    def choose_mulligan(self, message: dict[str, Any]) -> bool:
        player_id = str(message.get("player_id"))
        used = self.mulligans_by_player.get(player_id, 0)
        if used >= self.max_mulligans:
            return False
        hand = _private_hand(message)
        has_low_unit = any(_card_no(card) in LOW_COST_UNITS for card in hand)
        has_too_many_high_cp = sum(1 for card in hand if int(card.get("cp") or 0) >= 3 and card.get("category") != "trigger") >= 3
        do_mulligan = not has_low_unit or has_too_many_high_cp
        if do_mulligan:
            self.mulligans_by_player[player_id] = used + 1
        return do_mulligan

    def choose_action(self, message: dict[str, Any]) -> dict[str, Any]:
        legal_actions = [action for action in message.get("legal_actions") or [] if isinstance(action, dict)]
        if not legal_actions:
            return {"type": "pass"}
        context = message.get("request_context") or {}
        if context.get("kind") == "intercept_window":
            return self._choose_window_action(legal_actions)
        block = self._choose_block(legal_actions)
        if block is not None:
            return block
        joker = self._choose_joker(legal_actions, message)
        if joker is not None:
            return joker
        set_trigger = self._choose_set_trigger(legal_actions)
        if set_trigger is not None:
            return set_trigger
        drive = self._choose_drive(legal_actions, message)
        if drive is not None:
            return drive
        override = self._choose_override(legal_actions)
        if override is not None:
            return override
        attack = self._choose_attack(legal_actions)
        if attack is not None:
            return attack
        return _pass_action(legal_actions)

    def choose_choice(self, message: dict[str, Any]) -> dict[str, Any]:
        legal_choices = [choice for choice in message.get("legal_choices") or [] if isinstance(choice, dict)]
        if not legal_choices:
            return {}
        choice = message.get("choice") or {}
        if choice.get("type") == "cost_payment":
            return min(legal_choices, key=_cost_choice_score)
        return max(legal_choices, key=_choice_score)

    def _choose_window_action(self, legal_actions: list[dict[str, Any]]) -> dict[str, Any]:
        intercepts = [action for action in legal_actions if action.get("type") == "activate_intercept"]
        if not intercepts:
            return _pass_action(legal_actions)
        return max(intercepts, key=lambda action: INTERCEPT_PRIORITY.get(_action_card_no(action), 50))

    def _choose_block(self, legal_actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        blocks = [action for action in legal_actions if action.get("type") == "block"]
        if not blocks:
            return None
        favorable = [action for action in blocks if _unit_bp(action.get("unit")) >= _unit_bp(action.get("attacker"))]
        if favorable:
            return min(favorable, key=lambda action: _unit_bp(action.get("unit")))
        pig_blocks = [action for action in blocks if _unit_card_no(action.get("unit")) in PIG_UNITS]
        if pig_blocks:
            return min(pig_blocks, key=lambda action: _unit_bp(action.get("unit")))
        return None

    def _choose_joker(self, legal_actions: list[dict[str, Any]], message: dict[str, Any]) -> dict[str, Any] | None:
        jokers = [action for action in legal_actions if action.get("type") == "play_joker"]
        if not jokers:
            return None
        if len(_rival_battlefield(message)) >= 2:
            return jokers[0]
        return None

    def _choose_set_trigger(self, legal_actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        set_actions = [action for action in legal_actions if action.get("type") == "set_trigger"]
        if not set_actions:
            return None
        best = max(set_actions, key=lambda action: SET_PRIORITY.get(_action_card_no(action), 0))
        return best if SET_PRIORITY.get(_action_card_no(best), 0) > 0 else None

    def _choose_drive(self, legal_actions: list[dict[str, Any]], message: dict[str, Any]) -> dict[str, Any] | None:
        drive_actions = [action for action in legal_actions if action.get("type") == "drive_unit"]
        if not drive_actions:
            return None
        own_units = _own_battlefield(message)
        evolve_actions = [action for action in drive_actions if "evolve_target_unit_id" in action]
        if evolve_actions:
            return max(evolve_actions, key=lambda action: DRIVE_PRIORITY.get(_action_card_no(action), 0))
        if len(own_units) >= 4:
            return None
        return max(drive_actions, key=lambda action: DRIVE_PRIORITY.get(_action_card_no(action), 0))

    def _choose_override(self, legal_actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        overrides = [action for action in legal_actions if action.get("type") == "override_card"]
        if not overrides:
            return None
        return max(overrides, key=lambda action: DRIVE_PRIORITY.get(str((action.get("target_card") or {}).get("card_no")), 0))

    def _choose_attack(self, legal_actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        attacks = [action for action in legal_actions if action.get("type") == "attack"]
        if not attacks:
            return None
        return max(attacks, key=lambda action: (_unit_card_no(action.get("unit")) == "1-0-032", _unit_bp(action.get("unit"))))


def _private_hand(message: dict[str, Any]) -> list[dict[str, Any]]:
    hand = (message.get("private_view") or {}).get("hand") or []
    return [card for card in hand if isinstance(card, dict)]


def _own_battlefield(message: dict[str, Any]) -> list[dict[str, Any]]:
    player_id = message.get("player_id")
    players = ((message.get("public_state") or {}).get("players") or {})
    own = players.get(player_id) if isinstance(player_id, str) else None
    battlefield = (own or {}).get("battlefield") or []
    return [unit for unit in battlefield if isinstance(unit, dict)]


def _rival_battlefield(message: dict[str, Any]) -> list[dict[str, Any]]:
    player_id = message.get("player_id")
    players = ((message.get("public_state") or {}).get("players") or {})
    for candidate_player_id, player in players.items():
        if candidate_player_id != player_id and isinstance(player, dict):
            battlefield = player.get("battlefield") or []
            return [unit for unit in battlefield if isinstance(unit, dict)]
    return []


def _action_card_no(action: dict[str, Any]) -> str:
    return _card_no(action.get("card") or action.get("target_card") or action.get("material_card") or {})


def _card_no(card: dict[str, Any]) -> str:
    return str(card.get("card_no") or "")


def _unit_card_no(unit: Any) -> str:
    if not isinstance(unit, dict):
        return ""
    card = unit.get("card") if isinstance(unit.get("card"), dict) else unit
    return _card_no(card)


def _unit_bp(unit: Any) -> int:
    if not isinstance(unit, dict):
        return 0
    return int(unit.get("current_bp") or unit.get("modified_bp") or unit.get("base_bp") or 0)


def _choice_score(choice: dict[str, Any]) -> tuple[int, int]:
    target = choice.get("target") or {}
    if isinstance(target, dict):
        if target.get("is_owner") is False:
            return (100, _unit_bp(target))
        if target.get("is_owner") is True:
            return (50, _unit_bp(target))
    return (0, 0)


def _cost_choice_score(choice: dict[str, Any]) -> tuple[int, str]:
    card_no = _card_no(choice.get("card") or choice)
    return (DRIVE_PRIORITY.get(card_no, 0) + SET_PRIORITY.get(card_no, 0), card_no)


def _pass_action(legal_actions: list[dict[str, Any]]) -> dict[str, Any]:
    for action in legal_actions:
        if action.get("type") in PASS_ACTION_TYPES:
            return action
    return legal_actions[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Blue control deck JSON Lines player.")
    parser.add_argument("--max-mulligans", type=int, default=2)
    args = parser.parse_args()
    player = BlueControlPlayer(max_mulligans=args.max_mulligans)

    for line in sys.stdin:
        try:
            message = decode_message(line)
        except (ValueError, TypeError):
            continue
        message_type = message.get("type")
        if message_type == "state_update":
            continue
        if message_type == "request_mulligan":
            response = mulligan_selected_message(
                request_id=message["request_id"],
                player_id=message["player_id"],
                do_mulligan=player.choose_mulligan(message),
            )
        elif message_type == "request_action":
            response = action_selected_message(
                player.choose_action(message),
                request_id=message["request_id"],
                player_id=message["player_id"],
            )
        elif message_type == "choice_request":
            response = choice_selected_message(
                player.choose_choice(message),
                request_id=message["request_id"],
                player_id=message["player_id"],
            )
        else:
            continue
        sys.stdout.write(encode_message(response))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
