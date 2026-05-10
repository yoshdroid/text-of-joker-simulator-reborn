from __future__ import annotations

import json
from pathlib import Path

from .actions import drive_unit
from .state import create_game_state, load_card_catalog


ROOT = Path(__file__).resolve().parents[3]


def build_demo_state():
    catalog = load_card_catalog(ROOT / "carddata" / "generated" / "cards.normalized.json")
    state = create_game_state(catalog)
    happaloid = state.create_card_instance("1-0-040", "P1")
    draw_target = state.create_card_instance("1-0-001", "P1")
    state.players["P1"].hand.add(happaloid.instance_id)
    state.players["P1"].deck.cards.append(draw_target.instance_id)
    state.players["P1"].current_cp = 1
    return state, happaloid.instance_id


def main() -> None:
    state, happaloid_id = build_demo_state()
    drive_unit(state, "P1", happaloid_id)
    print(json.dumps(state.event_store.to_list(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
