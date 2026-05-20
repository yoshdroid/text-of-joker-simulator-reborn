from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Sequence

from tojs_reborn.engine.combat import attack_player, attack_unit, declare_attack, declare_block, destroy_unit, resolve_unblocked_attack
from tojs_reborn.engine.actions import drive_unit, override_card
from tojs_reborn.engine.replay import build_replay_record, snapshot_initial_state, verify_replay_record
from tojs_reborn.engine.state import GameState, load_card_catalog
from tojs_reborn.engine.turn import end_turn, start_turn
from tojs_reborn.engine.windows import process_windows_for_events

from .replay_gui import run_replay_gui_cli


ScenarioBuilder = Callable[[dict[str, Any]], tuple[GameState, dict[str, Any]]]
_SEED_OVERRIDE: int | None = None


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
    "attack_consume_action": lambda catalog: _scenario_attack_consume_action(catalog),
    "attack_bp_modifier": lambda catalog: _scenario_attack_bp_modifier(catalog),
    "block_bypass_player_attack": lambda catalog: _scenario_block_bypass_player_attack(catalog),
    "bishamon_evolve_destroy_all": lambda catalog: _scenario_bishamon_evolve_destroy_all(catalog),
    "bloodhound_level3_damage": lambda catalog: _scenario_bloodhound_level3_damage(catalog),
    "barbatos_base_bp": lambda catalog: _scenario_barbatos_base_bp(catalog),
    "battle_intercepts": lambda catalog: _scenario_battle_intercepts(catalog),
    "category_search_no_refresh": lambda catalog: _scenario_category_search_no_refresh(catalog),
    "dartagnan_cip_attack_draw": lambda catalog: _scenario_dartagnan_cip_attack_draw(catalog),
    "deck_refresh_draw": lambda catalog: _scenario_deck_refresh_draw(catalog),
    "display_stand_trigger_draw": lambda catalog: _scenario_display_stand_trigger_draw(catalog),
    "exquisite_provocation_no_oc": lambda catalog: _scenario_exquisite_provocation_no_oc(catalog),
    "ectoplasm_destroy": lambda catalog: _scenario_ectoplasm_destroy(catalog),
    "goliath_level3_life_damage": lambda catalog: _scenario_goliath_level3_life_damage(catalog),
    "happaloid_cip_draw": lambda catalog: _scenario_happaloid_cip_draw(catalog),
    "hand_limit_draw": lambda catalog: _scenario_hand_limit_draw(catalog),
    "heroic_sword_battle": lambda catalog: _scenario_heroic_sword_battle(catalog),
    "howling_intercept_draw_two": lambda catalog: _scenario_howling_intercept_draw_two(catalog),
    "jumpoo_bounce_hand_limit": lambda catalog: _scenario_jumpoo_bounce_hand_limit(catalog),
    "kaim_cip_trigger_search": lambda catalog: _scenario_kaim_cip_trigger_search(catalog),
    "leafia_block_bp_modifier": lambda catalog: _scenario_leafia_block_bp_modifier(catalog),
    "new_armor_trigger": lambda catalog: _scenario_new_armor_trigger(catalog),
    "new_armor_surprise_box_chain": lambda catalog: _scenario_new_armor_surprise_box_chain(catalog),
    "oc_consume_action": lambda catalog: _scenario_oc_consume_action(catalog),
    "power_shortage_battle": lambda catalog: _scenario_power_shortage_battle(catalog),
    "lina_discard_choice": lambda catalog: _scenario_lina_discard_choice(catalog),
    "raguel_exhausted_damage": lambda catalog: _scenario_raguel_exhausted_damage(catalog),
    "rairyu_evolve_damage": lambda catalog: _scenario_rairyu_evolve_damage(catalog),
    "tailwind_intercept_cp": lambda catalog: _scenario_tailwind_intercept_cp(catalog),
    "trigger_lost_random": lambda catalog: _scenario_trigger_lost_random(catalog),
    "v8_next_10_cards": lambda catalog: _scenario_v8_next_10_cards(catalog),
    "viper_discard_unit_recover": lambda catalog: _scenario_viper_discard_unit_recover(catalog),
}


def run_scenario_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate focused replay scenarios for GUI inspection.")
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    parser.add_argument("--images", default="carddata/images")
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS) + ["all"])
    parser.add_argument("--seed", type=int, help="Override the fixed seed used by scenario builders.")
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
        global _SEED_OVERRIDE
        previous_seed_override = _SEED_OVERRIDE
        _SEED_OVERRIDE = args.seed
        try:
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
        finally:
            _SEED_OVERRIDE = previous_seed_override
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


def _scenario_seed(default_seed: int) -> int:
    return default_seed if _SEED_OVERRIDE is None else _SEED_OVERRIDE


def _scenario_bloodhound_level3_damage(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(1))
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

    state = create_game_state(catalog, seed=_scenario_seed(26))
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

    state = create_game_state(catalog, seed=_scenario_seed(62))
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

    state = create_game_state(catalog, seed=_scenario_seed(47))
    state.turn_no = 3
    state.turn_player_id = "P1"
    dartagnan = _create_initial_deck_card(state, "P1", "1-0-047")
    draw_target = _create_initial_deck_card(state, "P1", "1-0-001")
    state.players["P1"].hand.add(dartagnan.instance_id)
    state.players["P1"].deck.cards.append(draw_target.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    unit = drive_unit(state, "P1", dartagnan.instance_id)
    end_turn(state, "P1")
    start_turn(state, "P2", draw_count=0, cp=3)
    end_turn(state, "P2")
    start_turn(state, "P1", draw_count=0, cp=5)
    attack_player(state, "P1", unit.unit_id)
    return state, initial_state


def _scenario_happaloid_cip_draw(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(40))
    state.turn_player_id = "P1"
    happaloid = _create_initial_deck_card(state, "P1", "1-0-040")
    draw_target = _create_initial_deck_card(state, "P1", "1-0-001")
    state.players["P1"].hand.add(happaloid.instance_id)
    state.players["P1"].deck.cards.append(draw_target.instance_id)
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", happaloid.instance_id)
    return state, initial_state


def _scenario_deck_refresh_draw(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(68))
    state.turn_player_id = "P1"
    for card_no in ("1-0-001", "1-0-004", "1-0-040", "1-0-061"):
        card = _create_initial_deck_card(state, "P1", card_no)
        state.players["P1"].discard_pile.add(card.instance_id)
    initial_state = snapshot_initial_state(state)

    start_turn(state, "P1", draw_count=1, cp=2)
    return state, initial_state


def _scenario_category_search_no_refresh(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(69))
    state.turn_player_id = "P1"
    kaim = _create_initial_deck_card(state, "P1", "1-0-020")
    for card_no in ("1-0-061", "1-0-062", "1-0-097"):
        card = _create_initial_deck_card(state, "P1", card_no)
        state.players["P1"].discard_pile.add(card.instance_id)
    state.players["P1"].hand.add(kaim.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", kaim.instance_id)
    return state, initial_state


def _scenario_attack_bp_modifier(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(2))
    state.turn_no = 3
    state.turn_player_id = "P1"
    _attacker_card, attacker = _add_battlefield_unit(state, "P1", "1-0-002")
    initial_state = snapshot_initial_state(state)

    attack_player(state, "P1", attacker.unit_id)
    end_turn(state, "P1")
    return state, initial_state


def _scenario_block_bypass_player_attack(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(8))
    state.turn_no = 3
    state.turn_player_id = "P1"
    _attacker_card, attacker = _add_battlefield_unit(state, "P1", "1-0-008")
    _blocker_card, _blocker = _add_battlefield_unit(state, "P2", "1-0-045")
    initial_state = snapshot_initial_state(state)

    attack_event = declare_attack(state, "P1", attacker.unit_id)
    resolve_unblocked_attack(state, attack_event.event_no)
    return state, initial_state


def _scenario_v8_next_10_cards(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.rules import get_unit_base_bp, get_unit_bp
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(110))
    state.turn_no = 3
    state.turn_player_id = "P1"
    _clara_card, clara = _add_battlefield_unit(state, "P1", "1-0-008")
    _clara_blocker_card, _clara_blocker = _add_battlefield_unit(state, "P2", "1-0-045")
    initial_state = snapshot_initial_state(state)

    attack_event = declare_attack(state, "P1", clara.unit_id)
    resolve_unblocked_attack(state, attack_event.event_no)

    _oni_card, oni = _add_battlefield_unit(state, "P1", "1-0-050")
    before_oni_base = get_unit_base_bp(state, oni)
    attack_player(state, "P1", oni.unit_id)
    if get_unit_base_bp(state, oni) != before_oni_base + 1000:
        raise AssertionError("v8 next scenario expected Oni Bull base BP to increase")

    _gasha_card, gasha = _add_battlefield_unit(state, "P2", "1-0-034")
    before_life = state.players["P1"].life
    destroy_unit(state, gasha, len(state.event_store.events) + 1, reason="scenario")
    if state.players["P1"].life != before_life - 1:
        raise AssertionError("v8 next scenario expected Gashadokuro PIG life damage")

    _attacker_card, attacker = _add_battlefield_unit(state, "P1", "1-0-001")
    _ally_card, ally = _add_battlefield_unit(state, "P1", "1-0-040")
    _blocker_card, blocker = _add_battlefield_unit(state, "P2", "1-0-040")
    order = _create_initial_deck_card(state, "P1", "1-0-066")
    state.players["P1"].trigger_zone.add(order.instance_id)
    state.players["P1"].current_cp = 1
    before_ally_bp = get_unit_bp(state, ally)
    battle_attack_event = declare_attack(state, "P1", attacker.unit_id)
    declare_block(
        state,
        "P2",
        blocker.unit_id,
        attacker.unit_id,
        battle_attack_event.event_no,
        battle_started_callback=lambda scenario_state, event_no: process_windows_for_events(
            scenario_state, event_no, choose_intercept=_choose_first_intercept
        ),
    )
    if get_unit_bp(state, ally) != before_ally_bp + 1000:
        raise AssertionError("v8 next scenario expected Opening Order to modify all owner units")

    return state, initial_state


def _scenario_attack_consume_action(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(25))
    state.turn_no = 3
    state.turn_player_id = "P1"
    _attacker_card, attacker = _add_battlefield_unit(state, "P1", "1-0-025")
    _exhausted_card, exhausted = _add_battlefield_unit(state, "P2", "1-0-004")
    _ready_card, ready = _add_battlefield_unit(state, "P2", "1-0-001")
    exhausted.exhausted = True
    initial_state = snapshot_initial_state(state)

    attack_player(state, "P1", attacker.unit_id)
    if not ready.exhausted:
        raise AssertionError("attack consume scenario expected ready rival unit to be exhausted")
    return state, initial_state


def _scenario_oc_consume_action(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(16))
    state.turn_player_id = "P1"
    source = _create_initial_deck_card(state, "P1", "1-0-016")
    first_material = _create_initial_deck_card(state, "P1", "1-0-016")
    second_material = _create_initial_deck_card(state, "P1", "1-0-016")
    initial_discard_cards = [
        _create_initial_deck_card(state, "P1", "1-0-038"),
        _create_initial_deck_card(state, "P1", "1-0-046"),
        _create_initial_deck_card(state, "P1", "1-0-009"),
    ]
    _exhausted_card, exhausted = _add_battlefield_unit(state, "P2", "1-0-004")
    _ready_card, ready = _add_battlefield_unit(state, "P2", "1-0-001")
    exhausted.exhausted = True
    state.players["P1"].hand.add(source.instance_id)
    state.players["P1"].hand.add(first_material.instance_id)
    state.players["P1"].hand.add(second_material.instance_id)
    for card in reversed(initial_discard_cards):
        state.players["P1"].discard_pile.add(card.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    override_card(state, "P1", source.instance_id, first_material.instance_id)
    override_card(state, "P1", source.instance_id, second_material.instance_id)
    drive_unit(state, "P1", source.instance_id)
    if not ready.exhausted:
        raise AssertionError("OC consume scenario expected ready rival unit to be exhausted")
    return state, initial_state


def _scenario_hand_limit_draw(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(71))
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

    state = create_game_state(catalog, seed=_scenario_seed(7))
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

    state = create_game_state(catalog, seed=_scenario_seed(20))
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


def _scenario_leafia_block_bp_modifier(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(45))
    state.turn_no = 3
    state.turn_player_id = "P1"
    attackers = [
        _add_battlefield_unit(state, "P1", "1-0-001", level=1)[1],
        _add_battlefield_unit(state, "P1", "1-0-001", level=2)[1],
        _add_battlefield_unit(state, "P1", "1-0-001", level=3)[1],
        _add_battlefield_unit(state, "P1", "1-0-032", level=3)[1],
    ]
    _blocker_card, blocker = _add_battlefield_unit(state, "P2", "1-0-045")
    initial_state = snapshot_initial_state(state)

    for attacker in attackers:
        attack_unit(state, "P1", attacker.unit_id, blocker.unit_id)
    end_turn(state, "P1")
    return state, initial_state


def _scenario_jumpoo_bounce_hand_limit(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(19))
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

    state = create_game_state(catalog, seed=_scenario_seed(99))
    state.turn_player_id = "P1"
    entering = _create_initial_deck_card(state, "P1", "1-0-041")
    howling = _create_initial_deck_card(state, "P1", "1-0-099")
    first_draw = _create_initial_deck_card(state, "P1", "1-0-004")
    second_draw = _create_initial_deck_card(state, "P1", "1-0-005")
    state.players["P1"].hand.add(entering.instance_id)
    state.players["P1"].trigger_zone.add(howling.instance_id)
    state.players["P1"].deck.cards.extend([first_draw.instance_id, second_draw.instance_id])
    state.players["P1"].current_cp = 3
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering.instance_id)
    process_windows_for_events(state, 1, choose_intercept=_choose_first_intercept)
    return state, initial_state


def _scenario_raguel_exhausted_damage(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(23))
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

    state = create_game_state(catalog, seed=_scenario_seed(97))
    state.turn_player_id = "P1"
    entering = _create_initial_deck_card(state, "P1", "1-0-041")
    tailwind = _create_initial_deck_card(state, "P1", "1-0-097")
    state.players["P1"].hand.add(entering.instance_id)
    state.players["P1"].trigger_zone.add(tailwind.instance_id)
    state.players["P1"].current_cp = 3
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering.instance_id)
    process_windows_for_events(state, 1, choose_intercept=_choose_first_intercept)
    return state, initial_state


def _scenario_rairyu_evolve_damage(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(24))
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

    state = create_game_state(catalog, seed=_scenario_seed(61))
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


def _scenario_new_armor_surprise_box_chain(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(57))
    state.turn_player_id = "P1"
    new_armor = _create_initial_deck_card(state, "P1", "1-0-061")
    surprise_box = _create_initial_deck_card(state, "P1", "1-0-057")
    entering = _create_initial_deck_card(state, "P1", "1-0-001")
    unit_card = _create_initial_deck_card(state, "P1", "1-0-004")
    intercept_card = _create_initial_deck_card(state, "P1", "1-0-097")
    first_trigger = _create_initial_deck_card(state, "P1", "1-0-062")
    second_trigger = _create_initial_deck_card(state, "P1", "1-0-061")
    state.players["P1"].trigger_zone.add(new_armor.instance_id)
    state.players["P1"].trigger_zone.add(surprise_box.instance_id)
    state.players["P1"].hand.add(entering.instance_id)
    state.players["P1"].deck.cards.extend([unit_card.instance_id, intercept_card.instance_id, first_trigger.instance_id, second_trigger.instance_id])
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", entering.instance_id)
    process_windows_for_events(state, 1)
    activated_cards = [event.payload["card"]["card_no"] for event in state.event_store.events if event.type == "trigger_activated"]
    if activated_cards != ["1-0-061", "1-0-057"]:
        raise AssertionError(f"expected New Armor then Surprise Box activation, got {activated_cards}")
    return state, initial_state


def _scenario_battle_intercepts(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(81))
    state.turn_player_id = "P1"
    attacker_card, attacker = _add_battlefield_unit(state, "P1", "1-0-001")
    blocker_card, blocker = _add_battlefield_unit(state, "P2", "1-0-045")
    evil_awaken = _create_initial_deck_card(state, "P1", "1-0-081")
    impervious_wall = _create_initial_deck_card(state, "P2", "1-0-096")
    state.players["P1"].trigger_zone.add(evil_awaken.instance_id)
    state.players["P2"].trigger_zone.add(impervious_wall.instance_id)
    state.players["P1"].current_cp = 0
    state.players["P2"].current_cp = 0
    initial_state = snapshot_initial_state(state)

    attack_event = declare_attack(state, "P1", attacker.unit_id)
    declare_block(
        state,
        "P2",
        blocker.unit_id,
        attacker.unit_id,
        attack_event.event_no,
        battle_started_callback=lambda scenario_state, event_no: process_windows_for_events(
            scenario_state, event_no, choose_intercept=_choose_first_intercept
        ),
    )
    activated_cards = [event.payload["card"]["card_no"] for event in state.event_store.events if event.type == "intercept_activated"]
    if activated_cards != ["1-0-081", "1-0-096"]:
        raise AssertionError(f"expected battle intercepts to activate from attacker then blocker, got {activated_cards}")
    _ = attacker_card, blocker_card
    return state, initial_state


def _scenario_power_shortage_battle(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(65))
    state.turn_player_id = "P1"
    _attacker_card, attacker = _add_battlefield_unit(state, "P1", "1-0-001")
    _blocker_card, blocker = _add_battlefield_unit(state, "P2", "1-0-001")
    power_shortage = _create_initial_deck_card(state, "P1", "1-0-065")
    state.players["P1"].trigger_zone.add(power_shortage.instance_id)
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    attack_event = declare_attack(state, "P1", attacker.unit_id)
    declare_block(
        state,
        "P2",
        blocker.unit_id,
        attacker.unit_id,
        attack_event.event_no,
        battle_started_callback=lambda scenario_state, event_no: process_windows_for_events(
            scenario_state, event_no, choose_intercept=_choose_first_intercept
        ),
    )
    bp_event = next(event for event in state.event_store.events if event.type == "bp_modified")
    if bp_event.payload.get("target_unit_id") != blocker.unit_id or bp_event.payload.get("after_bp") != 1000:
        raise AssertionError("power shortage scenario expected rival battle unit BP to become 1000")
    if blocker.unit_id in state.units:
        raise AssertionError("power shortage scenario expected weakened blocker to be destroyed")
    return state, initial_state


def _scenario_exquisite_provocation_no_oc(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(69))
    state.turn_player_id = "P1"
    entering = _create_initial_deck_card(state, "P1", "1-0-040")
    _target_card, target = _add_battlefield_unit(state, "P2", "1-0-001")
    provocation = _create_initial_deck_card(state, "P1", "1-0-069")
    state.players["P1"].hand.add(entering.instance_id)
    state.players["P1"].trigger_zone.add(provocation.instance_id)
    state.players["P1"].current_cp = 1
    initial_state = snapshot_initial_state(state)

    first_event_no = len(state.event_store.events) + 1
    drive_unit(state, "P1", entering.instance_id)
    process_windows_for_events(state, first_event_no, choose_intercept=_choose_first_intercept)
    if target.level != 3:
        raise AssertionError("exquisite provocation scenario expected rival unit to become LV3")
    if any(event.type == "unit_overclocked" and event.source.unit_id == target.unit_id for event in state.event_store.events):
        raise AssertionError("exquisite provocation scenario expected no target overclock event")
    if any(event.type == "damage_dealt" for event in state.event_store.events):
        raise AssertionError("exquisite provocation scenario expected suppressed OC effect")
    return state, initial_state


def _scenario_heroic_sword_battle(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.rules import get_unit_bp
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(74))
    state.turn_player_id = "P1"
    _attacker_card, attacker = _add_battlefield_unit(state, "P1", "1-0-001")
    _blocker_card, blocker = _add_battlefield_unit(state, "P2", "1-0-040")
    heroic_sword = _create_initial_deck_card(state, "P1", "1-0-074")
    state.players["P1"].trigger_zone.add(heroic_sword.instance_id)
    state.players["P1"].current_cp = 0
    initial_state = snapshot_initial_state(state)

    attack_event = declare_attack(state, "P1", attacker.unit_id)
    declare_block(
        state,
        "P2",
        blocker.unit_id,
        attacker.unit_id,
        attack_event.event_no,
        battle_started_callback=lambda scenario_state, event_no: process_windows_for_events(
            scenario_state, event_no, choose_intercept=_choose_first_intercept
        ),
    )
    bp_event = next(event for event in state.event_store.events if event.type == "bp_modified")
    if bp_event.payload.get("target_unit_id") != attacker.unit_id or bp_event.payload.get("after_bp") != 5000:
        raise AssertionError("heroic sword scenario expected owner battle unit BP to become 5000")
    if blocker.unit_id in state.units:
        raise AssertionError("heroic sword scenario expected blocker to be destroyed")
    end_turn(state, "P1")
    if get_unit_bp(state, attacker) != 4000:
        raise AssertionError("heroic sword scenario expected attacker BP to return to LV2 base after turn end")
    return state, initial_state


def _scenario_barbatos_base_bp(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.rules import get_unit_base_bp, get_unit_bp
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(51))
    state.turn_player_id = "P1"
    base_card, base_unit = _add_battlefield_unit(state, "P1", "1-0-040")
    _blocker_card, blocker = _add_battlefield_unit(state, "P1", "1-0-040")
    barbatos = _create_initial_deck_card(state, "P1", "1-0-051")
    _target_card, target = _add_battlefield_unit(state, "P2", "1-0-048")
    state.players["P1"].hand.add(barbatos.instance_id)
    state.players["P1"].current_cp = 7
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", barbatos.instance_id, evolve_target_unit_id=base_unit.unit_id)
    if not target.base_bp_modifiers:
        raise AssertionError("barbatos scenario expected permanent base BP modifier")
    if get_unit_base_bp(state, target) != 3000:
        raise AssertionError("barbatos scenario expected Giga Mammoth base BP to become 3000")
    end_turn(state, "P1")
    if get_unit_base_bp(state, target) != 3000:
        raise AssertionError("barbatos scenario expected permanent base BP modifier after P1 turn end")
    start_turn(state, "P2", draw_count=0, cp=3)
    attack_unit(state, "P2", target.unit_id, blocker.unit_id)
    if target.unit_id not in state.units or blocker.unit_id in state.units:
        raise AssertionError("barbatos scenario expected Giga Mammoth to win against Happaloid")
    if get_unit_bp(state, target) != 4000:
        raise AssertionError("barbatos scenario expected Giga Mammoth BP to be 4000 after battle win")
    end_turn(state, "P2")
    if get_unit_bp(state, target) != 4000:
        raise AssertionError("barbatos scenario expected permanent base BP modifier after P2 turn end")
    _ = base_card
    return state, initial_state


def _scenario_ectoplasm_destroy(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(92))
    state.turn_player_id = "P1"
    _destroyed_card, destroyed = _add_battlefield_unit(state, "P1", "1-0-031")
    _rival_card, rival = _add_battlefield_unit(state, "P2", "1-0-040")
    ectoplasm = _create_initial_deck_card(state, "P1", "1-0-092")
    state.players["P1"].trigger_zone.add(ectoplasm.instance_id)
    state.players["P1"].current_cp = 3
    initial_state = snapshot_initial_state(state)

    first_event_no = len(state.event_store.events) + 1
    destroy_unit(state, destroyed, first_event_no, reason="scenario")
    process_windows_for_events(state, first_event_no, choose_intercept=_choose_first_intercept)
    if rival.unit_id in state.units or destroyed.unit_id in state.units:
        raise AssertionError("ectoplasm scenario expected source and rival units to be destroyed")
    event_types = [event.type for event in state.event_store.events]
    destroyed_move_index = next(
        index
        for index, event in enumerate(state.event_store.events)
        if event.type == "card_moved" and event.source.unit_id == destroyed.unit_id
    )
    last_pass_index = max(index for index, event in enumerate(state.event_store.events) if event.type == "intercept_passed")
    if not event_types.index("unit_destroyed") < event_types.index("intercept_window_opened") < last_pass_index < destroyed_move_index:
        raise AssertionError("ectoplasm scenario expected source unit to move after unit_destroyed intercept window")
    return state, initial_state


def _scenario_lina_discard_choice(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(31))
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

    state = create_game_state(catalog, seed=_scenario_seed(33))
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


def _scenario_trigger_lost_random(catalog: dict[str, Any]) -> tuple[GameState, dict[str, Any]]:
    from tojs_reborn.engine.state import create_game_state

    state = create_game_state(catalog, seed=_scenario_seed(5))
    state.turn_player_id = "P1"
    breaker = _create_initial_deck_card(state, "P1", "1-0-005")
    rival_trigger = _create_initial_deck_card(state, "P2", "1-0-061")
    rival_display = _create_initial_deck_card(state, "P2", "1-0-062")
    rival_tailwind = _create_initial_deck_card(state, "P2", "1-0-097")
    state.players["P1"].hand.add(breaker.instance_id)
    state.players["P2"].trigger_zone.add(rival_trigger.instance_id)
    state.players["P2"].trigger_zone.add(rival_display.instance_id)
    state.players["P2"].trigger_zone.add(rival_tailwind.instance_id)
    state.players["P1"].current_cp = 10
    initial_state = snapshot_initial_state(state)

    drive_unit(state, "P1", breaker.instance_id)
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
