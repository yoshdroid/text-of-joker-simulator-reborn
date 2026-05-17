from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from tojs_reborn.engine.state import load_card_catalog

from .decklist import DecklistError, load_decklist
from .match_cli import _build_player
from .match_runner import MatchRunner, replay_match_record, snapshot_match_initial_state
from .match_setup import MatchSetupConfig, setup_match_state


def run_match_batch_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run sample matches across multiple seeds.")
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    parser.add_argument("--deck1", required=True)
    parser.add_argument("--deck2", required=True)
    parser.add_argument("--p1", default="sample:random")
    parser.add_argument("--p2", default="sample:aggressive")
    parser.add_argument("--seeds", required=True, help="Comma-separated seeds and ranges, e.g. 1,3-5.")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--max-actions-per-turn", type=int, default=20)
    parser.add_argument("--verify-replay", action="store_true")
    parser.add_argument("--output-dir", default="BattleLogs")
    parser.add_argument("--save-all-replays", action="store_true")
    parser.add_argument("--strict-deck-rule", action="store_true")
    args = parser.parse_args(argv)

    try:
        seeds = parse_seed_spec(args.seeds)
        card_catalog = load_card_catalog(args.cards)
        deck1 = load_decklist(args.deck1, card_catalog, strict_deck_rule=args.strict_deck_rule)
        deck2 = load_decklist(args.deck2, card_catalog, strict_deck_rule=args.strict_deck_rule)
    except (DecklistError, FileNotFoundError, ValueError) as exc:
        print(f"match batch failed: {exc}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    failures = 0
    for seed in seeds:
        item = _run_one_seed(
            seed,
            card_catalog=card_catalog,
            deck1=deck1,
            deck2=deck2,
            p1=args.p1,
            p2=args.p2,
            max_turns=args.max_turns,
            max_actions_per_turn=args.max_actions_per_turn,
            verify_replay=args.verify_replay,
        )
        replay_record = item.pop("_replay_record", None)
        if item["status"] != "ok":
            failures += 1
        should_save_replay = args.save_all_replays or item["status"] != "ok"
        if should_save_replay and isinstance(replay_record, dict):
            output_dir.mkdir(parents=True, exist_ok=True)
            replay_path = output_dir / f"replay_seed_{seed}.json"
            replay_path.write_text(json.dumps(replay_record, ensure_ascii=False, indent=2), encoding="utf-8")
            item["replay_path"] = str(replay_path)
        print(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    return 1 if failures else 0


def parse_seed_spec(spec: str) -> list[int]:
    seeds: list[int] = []
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"invalid descending seed range: {token}")
            seeds.extend(range(start, end + 1))
        else:
            seeds.append(int(token))
    if not seeds:
        raise ValueError("seeds must not be empty")
    return seeds


def _run_one_seed(
    seed: int,
    *,
    card_catalog,
    deck1,
    deck2,
    p1: str,
    p2: str,
    max_turns: int,
    max_actions_per_turn: int,
    verify_replay: bool,
) -> dict[str, Any]:
    players = {}
    replay_record: dict[str, Any] | None = None
    try:
        state = setup_match_state(
            card_catalog,
            {"P1": deck1, "P2": deck2},
            config=MatchSetupConfig(seed=seed),
        )
        players = {
            "P1": _build_player(p1, seed=seed, player_id="P1"),
            "P2": _build_player(p2, seed=seed, player_id="P2"),
        }
        initial_state = snapshot_match_initial_state(state)
        runner = MatchRunner(state, players=players)
        result = runner.run_match(max_turns=max_turns, max_actions_per_turn=max_actions_per_turn)
        replay_record = runner.build_replay_record(initial_state)
        replay_record["match_result"] = {
            "winner_player_id": result.winner_player_id,
            "reason": result.reason,
            "turn_count": result.turn_count,
        }
        if verify_replay:
            replay_match_record(card_catalog, replay_record)
        return {
            "seed": seed,
            "status": "ok",
            "winner_player_id": result.winner_player_id,
            "reason": result.reason,
            "turn_count": result.turn_count,
            "event_count": len(state.event_store.events),
            "last_event": state.event_store.events[-1].to_dict() if state.event_store.events else None,
            "_replay_record": replay_record,
        }
    except Exception as exc:
        last_event = None
        if replay_record is not None and replay_record.get("events"):
            last_event = replay_record["events"][-1]
        return {
            "seed": seed,
            "status": "failed",
            "error": str(exc),
            "last_event": last_event,
            "_replay_record": replay_record,
        }
    finally:
        for player in players.values():
            close = getattr(player, "close", None)
            if callable(close):
                close()


def main() -> None:
    raise SystemExit(run_match_batch_cli())


if __name__ == "__main__":
    main()
