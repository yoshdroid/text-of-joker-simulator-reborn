from __future__ import annotations

import argparse
import sys

from .protocol import action_selected_message, decode_message, encode_message


def choose_action(legal_actions: list[dict], mode: str) -> dict:
    if mode == "pass":
        for action in legal_actions:
            if action.get("type") in {"pass", "no_block", "pass_window"}:
                return action
        return legal_actions[0]
    for action in legal_actions:
        if action.get("type") not in {"pass", "no_block", "pass_window"}:
            return action
    return legal_actions[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample JSON Lines player.")
    parser.add_argument("--mode", choices=["first", "pass"], default="first")
    args = parser.parse_args()

    for line in sys.stdin:
        try:
            message = decode_message(line)
        except ValueError:
            continue
        if message.get("type") != "request_action":
            continue
        legal_actions = message.get("legal_actions", [])
        if not isinstance(legal_actions, list) or not legal_actions:
            continue
        action = choose_action(legal_actions, args.mode)
        response = action_selected_message(
            action,
            request_id=message["request_id"],
            player_id=message["player_id"],
        )
        sys.stdout.write(encode_message(response))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
