from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from tojs_reborn.engine.state import load_card_catalog

from .match_runner import replay_match_record


def run_replay_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a Text of Joker simulator replay.")
    parser.add_argument("--replay", required=True)
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    args = parser.parse_args(argv)

    try:
        card_catalog = load_card_catalog(args.cards)
        replay_record = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        replayed = replay_match_record(card_catalog, replay_record)
    except (FileNotFoundError, ValueError, AssertionError, KeyError, json.JSONDecodeError) as exc:
        print(f"replay verification failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "verified": True,
                "event_count": len(replayed.event_store.events),
                "final_turn_no": replayed.turn_no,
                "final_turn_player_id": replayed.turn_player_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def main() -> None:
    raise SystemExit(run_replay_cli())


if __name__ == "__main__":
    main()
