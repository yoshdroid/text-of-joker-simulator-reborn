from __future__ import annotations

import argparse
import sys

from .protocol import action_selected_message, choice_selected_message, decode_message, encode_message, mulligan_selected_message
from .sample_strategies import SampleStrategyPlayer, choose_sample_action


def choose_action(legal_actions: list[dict], mode: str) -> dict:
    return choose_sample_action(legal_actions, mode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample JSON Lines player.")
    parser.add_argument("--mode", choices=["first", "pass", "random", "aggressive", "mulligan_max", "mulligan-max"], default="first")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    player = SampleStrategyPlayer(mode=args.mode, seed=args.seed)

    for line in sys.stdin:
        try:
            message = decode_message(line)
        except ValueError:
            continue
        if message.get("type") == "request_mulligan":
            response = mulligan_selected_message(
                request_id=message["request_id"],
                player_id=message["player_id"],
                do_mulligan=player.choose_mulligan(message["player_id"]),
            )
        elif message.get("type") != "request_action":
            if message.get("type") != "choice_request":
                continue
            legal_choices = message.get("legal_choices", [])
            if not isinstance(legal_choices, list) or not legal_choices:
                continue
            response = choice_selected_message(
                player.choose_choice(
                    message["player_id"],
                    request_id=message["request_id"],
                    choice=message.get("choice") or {},
                    legal_choices=legal_choices,
                ),
                request_id=message["request_id"],
                player_id=message["player_id"],
            )
        else:
            legal_actions = message.get("legal_actions", [])
            if not isinstance(legal_actions, list) or not legal_actions:
                continue
            action = player.choose_action(message["player_id"], legal_actions)
            response = action_selected_message(
                action,
                request_id=message["request_id"],
                player_id=message["player_id"],
            )
        sys.stdout.write(encode_message(response))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
