from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Sequence

from tojs_reborn.engine.actions import drive_unit, override_card
from tojs_reborn.engine.replay import build_replay_record, snapshot_initial_state, verify_replay_record
from tojs_reborn.engine.state import GameState, load_card_catalog
from tojs_reborn.engine.turn import end_turn, start_turn
from tojs_reborn.engine.windows import process_windows_for_events

from .replay_gui import run_replay_gui_cli


ScenarioBuilder = Callable[[dict[str, Any]], tuple[GameState, dict[str, Any]]]


SCENARIOS: dict[str, ScenarioBuilder] = {
    "bloodhound_level3_damage": lambda catalog: _scenario_bloodhound_level3_damage(catalog),
    "happaloid_cip_draw": lambda catalog: _scenario_happaloid_cip_draw(catalog),
    "hand_limit_draw": lambda catalog: _scenario_hand_limit_draw(catalog),
    "kaim_cip_trigger_search": lambda catalog: _scenario_kaim_cip_trigger_search(catalog),
    "new_armor_trigger": lambda catalog: _scenario_new_armor_trigger(catalog),
    "lina_discard_choice": lambda catalog: _scenario_lina_discard_choice(catalog),
    "rairyu_evolve_damage": lambda catalog: _scenario_rairyu_evolve_damage(catalog),
}


def run_scenario_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate focused replay scenarios for GUI inspection.")
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    parser.add_argument("--images", default="carddata/images")
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS) + ["all"])
    parser.add_argument("--output-dir", default="test_output/scenarios")
    parser.add_argument("--replay", help="Output replay path for a single scenario.")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--open-gui", action="store_true")
    parser.add_argument("--fullscreen", action="store_true", help="Pass --fullscreen to replay_gui when using --open-gui.")
    parser.add_argument("--start-event-no", type=int)
    args = parser.parse_args(argv)

    if args.open_gui and args.scenario == "all":
        print("scenario failed: --open-gui requires a single scenario", file=sys.stderr)
        return 1

    try:
        catalog = load_card_catalog(args.cards)
        scenario_names = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
        outputs = []
        for scenario_name in scenario_names:
            state, initial_state = SCENARIOS[scenario_name](catalog)
            replay_record = build_replay_record(state, initial_state=initial_state)
            replay_record["scenario"] = {"name": scenario_name}
            if args.verify and not verify_replay_record(state, replay_record):
                raise AssertionError(f"scenario replay mismatch: {scenario_name}")
            replay_path = _scenario_replay_path(args, scenario_name)
            replay_path.parent.mkdir(parents=True, exist_ok=True)
            replay_path.write_text(json.dumps(replay_record, ensure_ascii=False, indent=2), encoding="utf-8")
            outputs.append({"scenario": scenario_name, "replay": str(replay_path), "event_count": len(state.event_store.events)})
        print(json.dumps({"outputs": outputs}, ensure_ascii=False, separators=(",", ":")))
        if args.open_gui:
            gui_args = [
                "--cards",
                args.cards,
                "--images",
                args.images,
                "--replay",
                outputs[0]["replay"],
            ]
            if args.start_event_no is not None:
                gui_args.extend(["--start-event-no", str(args.start_event_no)])
            if args.fullscreen:
                gui_args.append("--fullscreen")
            return run_replay_gui_cli(gui_args)
    except (FileNotFoundError, ValueError, AssertionError, KeyError) as exc:
        print(f"scenario failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _scenario_replay_path(args: argparse.Namespace, scenario_name: str) -> Path:
    if args.replay:
        if args.scenario == "all":
            raise ValueError("--replay cannot be used with --scenario all")
        return Path(args.replay)
    return Path(args.output_dir) / f"{scenario_name}.json"


def _scenario_bloodhound_level3_damage(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=1)
    state.turn_player_id = "P1"
    target = state.create_card_instance("1-0-001", "P1")
    first_material = state.create_card_instance("1-0-001", "P1")
    second_material = state.create_card_instance("1-0-001", "P1")
    rival_card = state.create_card_instance("1-0-004", "P2")
    rival = state.create_unit(rival_card.instance_id)
    state.players["P1"].hand.add(target.instance_id)
    state.players["P1"].hand.add(first_material.instance_id)
    state.players["P1"].hand.add(second_material.instance_id)
    state.players["P2"].battlefield.add(rival.unit_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    override_card(state, "P1", target.instance_id, first_material.instance_id)
    override_card(state, "P1", target.instance_id, second_material.instance_id)
    drive_unit(state, "P1", target.instance_id)
    return state, initial_state


def _scenario_happaloid_cip_draw(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=40)
    state.turn_player_id = "P1"
    happaloid = state.create_card_instance("1-0-040", "P1")
    draw_target = state.create_card_instance("1-0-001", "P1")
    state.players["P1"].hand.add(happaloid.instance_id)
    state.players["P1"].deck.cards.append(draw_target.instance_id)
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", happaloid.instance_id)
    return state, initial_state


def _scenario_hand_limit_draw(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=71)
    state.turn_player_id = "P1"
    for _ in range(3):
        state.players["P1"].hand.add(state.create_card_instance("1-0-001", "P1").instance_id)
    for _ in range(2):
        state.players["P2"].hand.add(state.create_card_instance("1-0-001", "P2").instance_id)
    for _ in range(12):
        state.players["P1"].deck.cards.append(state.create_card_instance("1-0-040", "P1").instance_id)
        state.players["P2"].deck.cards.append(state.create_card_instance("1-0-040", "P2").instance_id)
    initial_state = snapshot_initial_state(state)

    start_turn(state, "P1", draw_count=0, cp=2)
    end_turn(state, "P1")
    start_turn(state, "P2", draw_count=2, cp=3)
    end_turn(state, "P2")
    start_turn(state, "P1", draw_count=2, cp=3)
    end_turn(state, "P1")
    start_turn(state, "P2", draw_count=2, cp=3)
    end_turn(state, "P2")
    start_turn(state, "P1", draw_count=2, cp=4)
    end_turn(state, "P1")
    start_turn(state, "P2", draw_count=2, cp=4)
    end_turn(state, "P2")
    start_turn(state, "P1", draw_count=2, cp=5)
    return state, initial_state


def _scenario_kaim_cip_trigger_search(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=20)
    state.turn_player_id = "P1"
    kaim = state.create_card_instance("1-0-020", "P1")
    unit_card = state.create_card_instance("1-0-001", "P1")
    trigger_card = state.create_card_instance("1-0-061", "P1")
    intercept_card = state.create_card_instance("1-0-097", "P1")
    state.players["P1"].hand.add(kaim.instance_id)
    state.players["P1"].deck.cards.extend([unit_card.instance_id, trigger_card.instance_id, intercept_card.instance_id])
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", kaim.instance_id)
    return state, initial_state


def _scenario_rairyu_evolve_damage(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=24)
    state.turn_player_id = "P1"
    _base_card, base_unit = _add_battlefield_unit(state, "P1", "1-0-021")
    ready_card, ready_unit = _add_battlefield_unit(state, "P2", "1-0-040")
    exhausted_card, exhausted_unit = _add_battlefield_unit(state, "P2", "1-0-048")
    exhausted_unit.exhausted = True
    entering_card = state.create_card_instance("1-0-024", "P1")
    state.players["P1"].hand.add(entering_card.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)
    return state, initial_state


def _scenario_new_armor_trigger(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=61)
    state.turn_player_id = "P1"
    trigger_card = state.create_card_instance("1-0-061", "P1")
    entering = state.create_card_instance("1-0-001", "P1")
    unit_card = state.create_card_instance("1-0-004", "P1")
    intercept_card = state.create_card_instance("1-0-097", "P1")
    second_intercept = state.create_card_instance("1-0-099", "P1")
    state.players["P1"].trigger_zone.add(trigger_card.instance_id)
    state.players["P1"].hand.add(entering.instance_id)
    state.players["P1"].deck.cards.extend([unit_card.instance_id, intercept_card.instance_id, second_intercept.instance_id])
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering.instance_id)
    process_windows_for_events(state, 1)
    return state, initial_state


def _scenario_lina_discard_choice(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=31)
    state.turn_player_id = "P1"
    lina = state.create_card_instance("1-0-031", "P1")
    first_material = state.create_card_instance("1-0-031", "P1")
    second_material = state.create_card_instance("1-0-031", "P1")
    first_discard = state.create_card_instance("1-0-061", "P1")
    second_discard = state.create_card_instance("1-0-001", "P1")
    state.players["P1"].current_cp = 10
    state.players["P1"].hand.add(lina.instance_id)
    state.players["P1"].hand.add(first_material.instance_id)
    state.players["P1"].hand.add(second_material.instance_id)
    state.players["P1"].discard_pile.add(second_discard.instance_id)
    state.players["P1"].discard_pile.add(first_discard.instance_id)
    initial_state = snapshot_initial_state(state)

    override_card(state, "P1", lina.instance_id, first_material.instance_id)
    override_card(state, "P1", lina.instance_id, second_material.instance_id)
    drive_unit(state, "P1", lina.instance_id)
    return state, initial_state


def _add_battlefield_unit(state: GameState, player_id: str, card_no: str, *, level: int = 1):
    card = state.create_card_instance(card_no, player_id, level=level)
    unit = state.create_unit(card.instance_id)
    state.players[player_id].battlefield.add(unit.unit_id)
    return card, unit


def main() -> None:
    raise SystemExit(run_scenario_cli())


if __name__ == "__main__":
    main()
