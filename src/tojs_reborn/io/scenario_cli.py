from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Sequence

from tojs_reborn.engine.combat import attack_player
from tojs_reborn.engine.actions import drive_unit, override_card
from tojs_reborn.engine.replay import build_replay_record, snapshot_initial_state, verify_replay_record
from tojs_reborn.engine.state import GameState, load_card_catalog
from tojs_reborn.engine.turn import end_turn, start_turn
from tojs_reborn.engine.windows import process_windows_for_events

from .replay_gui import run_replay_gui_cli


ScenarioBuilder = Callable[[dict[str, Any]], tuple[GameState, dict[str, Any]]]


FILLER_CARD_NOS = (
    "1-0-001",
    "1-0-004",
    "1-0-005",
    "1-0-006",
    "1-0-007",
    "1-0-010",
    "1-0-016",
    "1-0-017",
    "1-0-018",
    "1-0-019",
    "1-0-020",
    "1-0-021",
    "1-0-023",
    "1-0-024",
    "1-0-025",
    "1-0-027",
    "1-0-028",
    "1-0-029",
    "1-0-030",
    "1-0-031",
    "1-0-033",
    "1-0-040",
    "1-0-041",
    "1-0-042",
    "1-0-043",
    "1-0-044",
    "1-0-045",
    "1-0-047",
    "1-0-048",
)


SCENARIOS: dict[str, ScenarioBuilder] = {
    "bishamon_evolve_destroy_all": lambda catalog: _scenario_bishamon_evolve_destroy_all(catalog),
    "bloodhound_level3_damage": lambda catalog: _scenario_bloodhound_level3_damage(catalog),
    "dartagnan_cip_attack_draw": lambda catalog: _scenario_dartagnan_cip_attack_draw(catalog),
    "display_stand_trigger_draw": lambda catalog: _scenario_display_stand_trigger_draw(catalog),
    "goliath_level3_life_damage": lambda catalog: _scenario_goliath_level3_life_damage(catalog),
    "happaloid_cip_draw": lambda catalog: _scenario_happaloid_cip_draw(catalog),
    "hand_limit_draw": lambda catalog: _scenario_hand_limit_draw(catalog),
    "howling_intercept_draw_two": lambda catalog: _scenario_howling_intercept_draw_two(catalog),
    "jumpoo_bounce_hand_limit": lambda catalog: _scenario_jumpoo_bounce_hand_limit(catalog),
    "kaim_cip_trigger_search": lambda catalog: _scenario_kaim_cip_trigger_search(catalog),
    "new_armor_trigger": lambda catalog: _scenario_new_armor_trigger(catalog),
    "lina_discard_choice": lambda catalog: _scenario_lina_discard_choice(catalog),
    "raguel_exhausted_damage": lambda catalog: _scenario_raguel_exhausted_damage(catalog),
    "rairyu_evolve_damage": lambda catalog: _scenario_rairyu_evolve_damage(catalog),
    "tailwind_intercept_cp": lambda catalog: _scenario_tailwind_intercept_cp(catalog),
    "viper_discard_unit_recover": lambda catalog: _scenario_viper_discard_unit_recover(catalog),
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
    target = _create_initial_deck_card(state, "P1", "1-0-001")
    first_material = _create_initial_deck_card(state, "P1", "1-0-001")
    second_material = _create_initial_deck_card(state, "P1", "1-0-001")
    rival_card = _create_initial_deck_card(state, "P2", "1-0-004")
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


def _scenario_bishamon_evolve_destroy_all(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=26)
    state.turn_player_id = "P1"
    _skull_card, _skull = _add_battlefield_unit(state, "P1", "1-0-028")
    _raimal_card, raimal = _add_battlefield_unit(state, "P1", "1-0-021")
    _mummy_card, _mummy = _add_battlefield_unit(state, "P1", "1-0-027")
    _crow_card, _crow = _add_battlefield_unit(state, "P2", "1-0-029")
    _add_hand_card(state, "P2", "1-0-001")
    _add_hand_card(state, "P2", "1-0-004")
    _add_deck_card(state, "P2", "1-0-040")
    _add_deck_card(state, "P2", "1-0-097")
    entering_card = _create_initial_deck_card(state, "P1", "1-0-026")
    state.players["P1"].hand.add(entering_card.instance_id)
    state.players["P1"].current_cp = 7
    initial_state = snapshot_initial_state(state)

    bishamon = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=raimal.unit_id)
    attack_player(state, "P1", bishamon.unit_id)
    return state, initial_state


def _scenario_display_stand_trigger_draw(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=62)
    state.turn_player_id = "P1"
    trigger_card = _create_initial_deck_card(state, "P1", "1-0-062")
    entering = _create_initial_deck_card(state, "P1", "1-0-001")
    draw_target = _create_initial_deck_card(state, "P1", "1-0-004")
    state.players["P1"].trigger_zone.add(trigger_card.instance_id)
    state.players["P1"].hand.add(entering.instance_id)
    state.players["P1"].deck.cards.append(draw_target.instance_id)
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering.instance_id)
    process_windows_for_events(state, 1)
    return state, initial_state


def _scenario_dartagnan_cip_attack_draw(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=47)
    state.turn_no = 3
    state.turn_player_id = "P1"
    dartagnan = _create_initial_deck_card(state, "P1", "1-0-047")
    draw_target = _create_initial_deck_card(state, "P1", "1-0-001")
    state.players["P1"].hand.add(dartagnan.instance_id)
    state.players["P1"].deck.cards.append(draw_target.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    unit = drive_unit(state, "P1", dartagnan.instance_id)
    state.turn_no += 2
    attack_player(state, "P1", unit.unit_id)
    return state, initial_state


def _scenario_happaloid_cip_draw(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=40)
    state.turn_player_id = "P1"
    happaloid = _create_initial_deck_card(state, "P1", "1-0-040")
    draw_target = _create_initial_deck_card(state, "P1", "1-0-001")
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
    p1_cards = list(FILLER_CARD_NOS[:15])
    p2_cards = list(FILLER_CARD_NOS[5:19])
    for card_no in p1_cards[:3]:
        _add_hand_card(state, "P1", card_no)
    for card_no in p2_cards[:2]:
        _add_hand_card(state, "P2", card_no)
    for card_no in p1_cards[3:]:
        _add_deck_card(state, "P1", card_no)
    for card_no in p2_cards[2:]:
        _add_deck_card(state, "P2", card_no)
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


def _scenario_goliath_level3_life_damage(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=7)
    state.turn_player_id = "P1"
    target = _create_initial_deck_card(state, "P1", "1-0-007")
    first_material = _create_initial_deck_card(state, "P1", "1-0-007")
    second_material = _create_initial_deck_card(state, "P1", "1-0-007")
    _add_deck_card(state, "P1", "1-0-004")
    _add_deck_card(state, "P1", "1-0-005")
    state.players["P1"].hand.add(target.instance_id)
    state.players["P1"].hand.add(first_material.instance_id)
    state.players["P1"].hand.add(second_material.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    override_card(state, "P1", target.instance_id, first_material.instance_id)
    override_card(state, "P1", target.instance_id, second_material.instance_id)
    drive_unit(state, "P1", target.instance_id)
    return state, initial_state


def _scenario_kaim_cip_trigger_search(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=20)
    state.turn_player_id = "P1"
    kaim = _create_initial_deck_card(state, "P1", "1-0-020")
    unit_card = _create_initial_deck_card(state, "P1", "1-0-001")
    trigger_card = _create_initial_deck_card(state, "P1", "1-0-061")
    intercept_card = _create_initial_deck_card(state, "P1", "1-0-097")
    state.players["P1"].hand.add(kaim.instance_id)
    state.players["P1"].deck.cards.extend([unit_card.instance_id, trigger_card.instance_id, intercept_card.instance_id])
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", kaim.instance_id)
    return state, initial_state


def _scenario_jumpoo_bounce_hand_limit(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=19)
    state.turn_player_id = "P1"
    first_jumpoo = _create_initial_deck_card(state, "P1", "1-0-019")
    second_jumpoo = _create_initial_deck_card(state, "P1", "1-0-019")
    first_target_card = _create_initial_deck_card(state, "P2", "1-0-001", level=2)
    second_target_card = _create_initial_deck_card(state, "P2", "1-0-004", level=3)
    first_target = state.create_unit(first_target_card.instance_id)
    second_target = state.create_unit(second_target_card.instance_id)
    state.players["P1"].hand.add(first_jumpoo.instance_id)
    state.players["P1"].hand.add(second_jumpoo.instance_id)
    state.players["P2"].battlefield.add(first_target.unit_id)
    state.players["P2"].battlefield.add(second_target.unit_id)
    for card_no in FILLER_CARD_NOS[4:10]:
        _add_hand_card(state, "P2", card_no)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", first_jumpoo.instance_id)
    drive_unit(state, "P1", second_jumpoo.instance_id)
    return state, initial_state


def _scenario_howling_intercept_draw_two(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=99)
    state.turn_player_id = "P1"
    entering = _create_initial_deck_card(state, "P1", "1-0-001")
    howling = _create_initial_deck_card(state, "P1", "1-0-099")
    first_draw = _create_initial_deck_card(state, "P1", "1-0-004")
    second_draw = _create_initial_deck_card(state, "P1", "1-0-005")
    state.players["P1"].hand.add(entering.instance_id)
    state.players["P1"].trigger_zone.add(howling.instance_id)
    state.players["P1"].deck.cards.extend([first_draw.instance_id, second_draw.instance_id])
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering.instance_id)
    process_windows_for_events(state, 1, choose_intercept=_choose_first_intercept)
    return state, initial_state


def _scenario_raguel_exhausted_damage(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=23)
    state.turn_player_id = "P1"
    _ready_card, ready_unit = _add_battlefield_unit(state, "P2", "1-0-048")
    _first_exhausted_card, first_exhausted = _add_battlefield_unit(state, "P2", "1-0-048")
    _second_exhausted_card, second_exhausted = _add_battlefield_unit(state, "P2", "1-0-048")
    first_exhausted.exhausted = True
    second_exhausted.exhausted = True
    entering_card = _create_initial_deck_card(state, "P1", "1-0-023")
    state.players["P1"].hand.add(entering_card.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering_card.instance_id)
    return state, initial_state


def _scenario_tailwind_intercept_cp(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=97)
    state.turn_player_id = "P1"
    entering = _create_initial_deck_card(state, "P1", "1-0-001")
    tailwind = _create_initial_deck_card(state, "P1", "1-0-097")
    state.players["P1"].hand.add(entering.instance_id)
    state.players["P1"].trigger_zone.add(tailwind.instance_id)
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering.instance_id)
    process_windows_for_events(state, 1, choose_intercept=_choose_first_intercept)
    return state, initial_state


def _scenario_rairyu_evolve_damage(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=24)
    state.turn_player_id = "P1"
    _base_card, base_unit = _add_battlefield_unit(state, "P1", "1-0-021")
    ready_card, ready_unit = _add_battlefield_unit(state, "P2", "1-0-040")
    exhausted_card, exhausted_unit = _add_battlefield_unit(state, "P2", "1-0-048")
    exhausted_unit.exhausted = True
    entering_card = _create_initial_deck_card(state, "P1", "1-0-024")
    state.players["P1"].hand.add(entering_card.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)
    return state, initial_state


def _scenario_new_armor_trigger(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=61)
    state.turn_player_id = "P1"
    trigger_card = _create_initial_deck_card(state, "P1", "1-0-061")
    entering = _create_initial_deck_card(state, "P1", "1-0-001")
    unit_card = _create_initial_deck_card(state, "P1", "1-0-004")
    intercept_card = _create_initial_deck_card(state, "P1", "1-0-097")
    second_intercept = _create_initial_deck_card(state, "P1", "1-0-099")
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
    lina = _create_initial_deck_card(state, "P1", "1-0-031")
    first_material = _create_initial_deck_card(state, "P1", "1-0-031")
    second_material = _create_initial_deck_card(state, "P1", "1-0-031")
    viper = _create_initial_deck_card(state, "P1", "1-0-033")
    for card_no in ("1-0-001", "1-0-004", "1-0-040", "1-0-061"):
        _add_deck_card(state, "P1", card_no)
    state.players["P1"].hand.add(lina.instance_id)
    state.players["P1"].hand.add(first_material.instance_id)
    state.players["P1"].hand.add(second_material.instance_id)
    state.players["P1"].deck.cards.insert(0, viper.instance_id)
    initial_state = snapshot_initial_state(state)

    start_turn(state, "P1", draw_count=1, cp=7)
    override_card(state, "P1", lina.instance_id, first_material.instance_id)
    override_card(state, "P1", lina.instance_id, second_material.instance_id)
    drive_unit(state, "P1", viper.instance_id)
    drive_unit(state, "P1", lina.instance_id)
    returned_linas = [
        card_instance_id
        for card_instance_id in state.players["P1"].hand.cards
        if state.card_instances[card_instance_id].card_no == "1-0-031"
    ]
    if len(returned_linas) < 2:
        raise AssertionError("lina scenario expected two returned Lina cards in hand")
    override_card(state, "P1", returned_linas[0], returned_linas[1])
    return state, initial_state


def _scenario_viper_discard_unit_recover(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=33)
    state.turn_player_id = "P1"
    viper = _create_initial_deck_card(state, "P1", "1-0-033")
    discarded_unit = _create_initial_deck_card(state, "P1", "1-0-001")
    discarded_trigger = _create_initial_deck_card(state, "P1", "1-0-061")
    state.players["P1"].hand.add(viper.instance_id)
    state.players["P1"].discard_pile.add(discarded_trigger.instance_id)
    state.players["P1"].discard_pile.add(discarded_unit.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", viper.instance_id)
    return state, initial_state


def _add_battlefield_unit(state: GameState, player_id: str, card_no: str, *, level: int = 1):
    card = _create_initial_deck_card(state, player_id, card_no, level=level)
    unit = state.create_unit(card.instance_id)
    state.players[player_id].battlefield.add(unit.unit_id)
    return card, unit


def _create_initial_deck_card(state: GameState, player_id: str, card_no: str, *, level: int = 1):
    if state.players[player_id].initial_deck_card_nos.count(card_no) >= 3:
        raise ValueError(f"scenario initial deck copy limit exceeded: player={player_id} card_no={card_no}")
    state.players[player_id].initial_deck_card_nos.append(card_no)
    return state.create_card_instance(card_no, player_id, level=level)


def _add_hand_card(state: GameState, player_id: str, card_no: str, *, level: int = 1):
    card = _create_initial_deck_card(state, player_id, card_no, level=level)
    state.players[player_id].hand.add(card.instance_id)
    return card


def _add_deck_card(state: GameState, player_id: str, card_no: str, *, level: int = 1):
    card = _create_initial_deck_card(state, player_id, card_no, level=level)
    state.players[player_id].deck.cards.append(card.instance_id)
    return card


def _choose_first_intercept(_player_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    for action in actions:
        if action.get("type") == "activate_intercept":
            return action
    return actions[-1]


def main() -> None:
    raise SystemExit(run_scenario_cli())


if __name__ == "__main__":
    main()
