from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tojs_reborn.engine.state import load_card_catalog

from .decklist import DecklistError, load_decklist
from .match_runner import ActionPlayer, FirstLegalPlayer, MatchRunner, replay_match_record, snapshot_match_initial_state
from .match_setup import MatchSetupConfig, setup_match_state
from .process_player import start_process_player


@dataclass
class PassPlayer:
    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        for action in legal_actions:
            if action.get("type") in {"pass", "no_block", "pass_window"}:
                return action
        return legal_actions[0]


def run_match_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Text of Joker simulator match.")
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    parser.add_argument("--deck1", required=True)
    parser.add_argument("--deck2", required=True)
    parser.add_argument("--p1", default="sample:first")
    parser.add_argument("--p2", default="sample:pass")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--max-actions-per-turn", type=int, default=20)
    parser.add_argument("--replay")
    parser.add_argument("--verify-replay", action="store_true")
    parser.add_argument("--strict-deck-rule", action="store_true")
    args = parser.parse_args(argv)

    try:
        card_catalog = load_card_catalog(args.cards)
        deck1 = load_decklist(args.deck1, card_catalog, strict_deck_rule=args.strict_deck_rule)
        deck2 = load_decklist(args.deck2, card_catalog, strict_deck_rule=args.strict_deck_rule)
        state = setup_match_state(
            card_catalog,
            {"P1": deck1, "P2": deck2},
            config=MatchSetupConfig(seed=args.seed),
        )
        players = {"P1": _build_player(args.p1), "P2": _build_player(args.p2)}
        try:
            initial_state = snapshot_match_initial_state(state)
            runner = MatchRunner(state, players=players)
            result = runner.run_match(max_turns=args.max_turns, max_actions_per_turn=args.max_actions_per_turn)
            replay_record = runner.build_replay_record(initial_state)
        finally:
            for player in players.values():
                close = getattr(player, "close", None)
                if callable(close):
                    close()
        replay_record["match_result"] = {
            "winner_player_id": result.winner_player_id,
            "reason": result.reason,
            "turn_count": result.turn_count,
        }
        if args.replay:
            replay_path = Path(args.replay)
            replay_path.parent.mkdir(parents=True, exist_ok=True)
            replay_path.write_text(json.dumps(replay_record, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.verify_replay:
            replay_match_record(card_catalog, replay_record)
    except (DecklistError, FileNotFoundError, ValueError, AssertionError) as exc:
        print(f"match failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "winner_player_id": result.winner_player_id,
                "reason": result.reason,
                "turn_count": result.turn_count,
                "event_count": len(state.event_store.events),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def _build_player(spec: str) -> ActionPlayer:
    if spec == "sample:first":
        return FirstLegalPlayer()
    if spec == "sample:pass":
        return PassPlayer()
    if spec.startswith("cmd:"):
        return start_process_player(spec.removeprefix("cmd:"))
    raise ValueError(f"unknown player spec: {spec}")


def main() -> None:
    raise SystemExit(run_match_cli())


if __name__ == "__main__":
    main()
