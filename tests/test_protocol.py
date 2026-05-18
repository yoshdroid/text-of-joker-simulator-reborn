import sys
import os
import json
import subprocess
import unittest
from collections import Counter
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tests.test_engine import build_catalog, draw_window_card
from tojs_reborn.engine.rules import card_bp_to_game_bp
from tojs_reborn.engine.state import AbilityDefinition, CardDefinition, create_game_state
from tojs_reborn.io.decklist import parse_decklist
from tojs_reborn.io.gui_player import build_model_from_message, make_response, tile_display_size
from tojs_reborn.io.gui_view_model import build_gui_view_model, find_card_image
from tojs_reborn.io.match_runner import FirstLegalPlayer, MatchRunner, replay_match_record, snapshot_match_initial_state
from tojs_reborn.io.match_cli import run_match_cli
from tojs_reborn.io.match_batch_cli import parse_seed_spec, run_match_batch_cli
from tojs_reborn.io.match_setup import MatchSetupConfig, setup_match_state
from tojs_reborn.io.player_runner import (
    JsonLinePlayer,
    TextIOJsonLineTransport,
    encode_action_response,
    encode_choice_response,
    encode_mulligan_response,
)
from tojs_reborn.io.process_player import start_process_player
from tojs_reborn.io.replay_cli import run_replay_cli
from tojs_reborn.io.replay_gui import DEFAULT_REPLAY_CARD_WIDTH, ReplayTkGui, run_replay_gui_cli
from tojs_reborn.io.replay_gui_model import build_replay_gui_model
from tojs_reborn.io.replay_viewer import format_replay_actions, format_replay_events, run_replay_viewer_cli
from tojs_reborn.io.scenario_cli import run_scenario_cli
from tojs_reborn.io.sample_strategies import SampleStrategyPlayer, choose_aggressive_action, choose_sample_action
from tojs_reborn.io.views import build_private_view, build_public_state
from tojs_reborn.io.protocol import (
    action_selected_message,
    choice_request_message,
    choice_selected_message,
    decode_message,
    encode_message,
    mulligan_selected_message,
    public_state_message,
    request_action_message,
    request_mulligan_message,
    state_update_message,
)


class MemoryTransport:
    def __init__(self, responses: list[str | None] | None = None) -> None:
        self.responses = list(responses or [])
        self.written: list[str] = []

    def write_line(self, line: str) -> None:
        self.written.append(line)

    def read_line(self, timeout_seconds: float) -> str | None:
        if not self.responses:
            return None
        return self.responses.pop(0)


def optional_draw_unit(card_no: str) -> CardDefinition:
    return CardDefinition(
        card_no=card_no,
        category="unit",
        color="test",
        name="Optional Draw Unit",
        cp=1,
        bp_by_level=(1, 1, 1),
        abilities=(
            AbilityDefinition(
                ability_id=f"{card_no}:a1",
                name="optional draw",
                status="supported",
                timing="SELF_CIP",
                optional=True,
                effect_steps=({"effect": "draw_cards", "player": "owner", "count": 1},),
                raw={
                    "selector": None,
                    "condition": None,
                },
            ),
        ),
    )


class ProtocolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_catalog()

    def test_json_lines_protocol_round_trips_request_action(self) -> None:
        state = create_game_state(self.catalog)
        message = request_action_message(state, "P1", request_id="r1")

        decoded = decode_message(encode_message(message))

        self.assertEqual(decoded["type"], "request_action")
        self.assertEqual(decoded["request_id"], "r1")
        self.assertEqual(decoded["legal_actions"][0]["type"], "pass")
        self.assertEqual(decoded["request_context"]["kind"], "turn_action")
        self.assertIn("display", decoded["legal_actions"][0])
        self.assertIn("public_state", decoded)
        self.assertIn("private_view", decoded)
        self.assertEqual(decoded["state_revision"], 0)

    def test_json_lines_protocol_round_trips_action_selected(self) -> None:
        message = action_selected_message({"type": "pass"}, request_id="r1", player_id="P1")

        decoded = decode_message(encode_message(message))

        self.assertEqual(decoded["type"], "action_selected")
        self.assertEqual(decoded["action"], {"type": "pass"})

    def test_json_lines_protocol_round_trips_choice_messages(self) -> None:
        request = choice_request_message(
            request_id="c1",
            player_id="P1",
            choice={"type": "unit", "choice_id": "target"},
            legal_choices=[{"unit_id": "u0001"}],
        )
        selected = choice_selected_message({"unit_id": "u0001"}, request_id="c1", player_id="P1")

        self.assertEqual(decode_message(encode_message(request))["type"], "choice_request")
        self.assertEqual(decode_message(encode_message(selected))["type"], "choice_selected")

    def test_choice_request_includes_unit_target_display_when_state_is_available(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P2")
        unit = state.create_unit(card.instance_id)
        unit.current_damage = 200
        unit.bp_modifiers.append({"amount": 1000, "expires": "turn"})
        state.players["P2"].battlefield.add(unit.unit_id)

        request = choice_request_message(
            request_id="c1",
            player_id="P1",
            choice={"type": "unit", "choice_id": "target", "required": True, "count": 1},
            legal_choices=[{"unit_id": unit.unit_id}],
            state=state,
        )

        legal_choice = request["legal_choices"][0]
        self.assertEqual(request["display"]["label"], "対象ユニットを1体選択")
        self.assertEqual(legal_choice["unit_id"], unit.unit_id)
        self.assertIn("display", legal_choice)
        self.assertEqual(legal_choice["target"]["card_no"], "1-0-001")
        self.assertEqual(legal_choice["target"]["controller"], "P2")
        self.assertEqual(legal_choice["target"]["base_bp"], card_bp_to_game_bp(self.catalog["1-0-001"].bp_by_level[0]))
        self.assertEqual(legal_choice["target"]["modified_bp"], 1000)
        self.assertEqual(legal_choice["target"]["current_bp"], card_bp_to_game_bp(self.catalog["1-0-001"].bp_by_level[0]) + 1000)
        self.assertEqual(legal_choice["target"]["damage"], 200)

    def test_public_state_hides_opponent_private_zones(self) -> None:
        state = create_game_state(self.catalog)
        opponent_card = state.create_card_instance("1-0-001", "P2")
        trigger_card = state.create_card_instance("1-0-065", "P2")
        state.players["P2"].hand.add(opponent_card.instance_id)
        state.players["P2"].trigger_zone.add(trigger_card.instance_id)

        message = public_state_message(state, "P1", request_id="s1")

        self.assertEqual(message["public_state"]["players"]["P2"]["hand_count"], 1)
        self.assertEqual(message["public_state"]["players"]["P2"]["deck_count"], 0)
        self.assertNotIn("hand", message["public_state"]["players"]["P2"])
        self.assertEqual(message["public_state"]["players"]["P2"]["trigger_zone"]["count"], 1)
        self.assertEqual(
            message["public_state"]["players"]["P2"]["trigger_zone"]["items"][0]["color"],
            self.catalog["1-0-065"].color,
        )
        self.assertIsNone(message["public_state"]["players"]["P2"]["trigger_zone"]["items"][0]["revealed_card_no"])
        self.assertNotIn("category", message["public_state"]["players"]["P2"]["trigger_zone"]["items"][0])

    def test_views_include_own_private_hand_and_trigger_zone(self) -> None:
        state = create_game_state(self.catalog)
        hand_card = state.create_card_instance("1-0-040", "P1")
        trigger_card = state.create_card_instance("1-0-097", "P1")
        state.players["P1"].hand.add(hand_card.instance_id)
        state.players["P1"].trigger_zone.add(trigger_card.instance_id)

        public_state = build_public_state(state, "P1")
        private_view = build_private_view(state, "P1")

        self.assertEqual(public_state["players"]["P1"]["hand_count"], 1)
        self.assertEqual(private_view["hand"][0]["card_no"], "1-0-040")
        self.assertEqual(private_view["hand"][0]["name"], self.catalog["1-0-040"].name)
        self.assertEqual(private_view["hand"][0]["category"], "unit")
        self.assertEqual(private_view["hand"][0]["cp"], 1)
        self.assertEqual(private_view["trigger_zone"][0]["card_no"], "1-0-097")

    def test_gui_view_model_contains_visible_zones_and_card_images(self) -> None:
        state = create_game_state(self.catalog)
        hand_card = state.create_card_instance("1-0-040", "P1")
        trigger_card = state.create_card_instance("1-0-097", "P1")
        own_unit_card = state.create_card_instance("1-0-001", "P1")
        opponent_unit_card = state.create_card_instance("1-0-004", "P2")
        own_unit = state.create_unit(own_unit_card.instance_id)
        opponent_unit = state.create_unit(opponent_unit_card.instance_id)
        state.players["P1"].hand.add(hand_card.instance_id)
        state.players["P1"].trigger_zone.add(trigger_card.instance_id)
        state.players["P1"].battlefield.add(own_unit.unit_id)
        state.players["P2"].battlefield.add(opponent_unit.unit_id)
        image_dir = ROOT / "test_output" / "gui_images"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / "1-0-040_sample.jpg"
        image_path.write_bytes(b"fake image")

        model = build_gui_view_model(
            build_public_state(state, "P1"),
            build_private_view(state, "P1"),
            images_dir=image_dir,
        )

        self.assertEqual(model["player_id"], "P1")
        self.assertEqual(model["opponent"]["player_id"], "P2")
        self.assertEqual(model["own"]["hand"][0]["card_no"], "1-0-040")
        self.assertEqual(model["own"]["hand"][0]["image_path"], str(image_path))
        self.assertEqual(model["own"]["trigger_zone"][0]["card_no"], "1-0-097")
        self.assertEqual(model["own"]["battlefield"][0]["unit_id"], own_unit.unit_id)
        self.assertEqual(model["opponent"]["battlefield"][0]["unit_id"], opponent_unit.unit_id)
        self.assertEqual(find_card_image(image_dir, "NO-SUCH-CARD"), None)

    def test_gui_player_builds_model_and_auto_responses(self) -> None:
        state = create_game_state(self.catalog)
        hand_card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(hand_card.instance_id)
        request = request_action_message(state, "P1", request_id="P1:action")

        model = build_model_from_message(request, ROOT / "carddata" / "images")
        response = make_response(request, mode="pass")

        self.assertIsNotNone(model)
        self.assertEqual(model["own"]["hand"][0]["card_no"], "1-0-001")
        self.assertEqual(response["type"], "action_selected")
        self.assertEqual(response["request_id"], "P1:action")
        self.assertEqual(response["action"]["type"], "pass")

    def test_gui_player_uses_landscape_tile_for_exhausted_field_units(self) -> None:
        self.assertEqual(tile_display_size({"kind": "unit", "exhausted": True}, 96, 139), (139, 96))
        self.assertEqual(tile_display_size({"kind": "unit", "exhausted": False}, 96, 139), (96, 139))
        self.assertEqual(tile_display_size({"kind": "card", "exhausted": True}, 96, 139), (96, 139))

    def test_gui_player_no_window_process_responds_to_protocol(self) -> None:
        command = f"{sys.executable} -m tojs_reborn.io.gui_player --no-window --mode pass --images carddata/images"
        player = start_process_player(command, timeout_seconds=2.0)
        try:
            action = player.choose_action(
                "P1",
                [
                    {"type": "drive_unit", "card_instance_id": "c0001"},
                    {"type": "pass"},
                ],
            )
            choice = player.choose_choice(
                "P1",
                request_id="P1:choice",
                choice={"type": "unit"},
                legal_choices=[{"unit_id": "u0001"}],
            )
            do_mulligan = player.choose_mulligan("P1")
        finally:
            player.close()

        self.assertEqual(action["type"], "pass")
        self.assertEqual(choice, {"unit_id": "u0001"})
        self.assertFalse(do_mulligan)

    def test_sample_random_is_seeded_and_aggressive_prioritizes_pressure(self) -> None:
        legal_actions = [
            {"type": "pass"},
            {"type": "set_trigger", "card_instance_id": "c0001"},
            {"type": "attack", "attacker_unit_id": "u0001"},
            {"type": "drive_unit", "card_instance_id": "c0002"},
        ]
        first_random = SampleStrategyPlayer(mode="random", seed=12, player_id_hint="P1")
        second_random = SampleStrategyPlayer(mode="random", seed=12, player_id_hint="P1")

        self.assertEqual(
            [first_random.choose_action("P1", legal_actions) for _ in range(5)],
            [second_random.choose_action("P1", legal_actions) for _ in range(5)],
        )
        self.assertEqual(choose_aggressive_action(legal_actions)["type"], "attack")
        self.assertEqual(
            choose_aggressive_action(
                [
                    {"type": "pass"},
                    {"type": "drive_unit", "card_instance_id": "c0001"},
                    {"type": "drive_unit", "card_instance_id": "c0002", "evolve_target_unit_id": "u0001"},
                ]
            )["evolve_target_unit_id"],
            "u0001",
        )
        self.assertEqual(choose_sample_action(legal_actions, "pass")["type"], "pass")

    def test_state_update_and_mulligan_messages_round_trip(self) -> None:
        state = create_game_state(self.catalog)

        state_update = decode_message(encode_message(state_update_message(state, "P1", request_id="s1")))
        mulligan_request = decode_message(encode_message(request_mulligan_message(state, "P1", request_id="m1")))
        mulligan_selected = decode_message(
            encode_message(mulligan_selected_message(request_id="m1", player_id="P1", do_mulligan=False))
        )

        self.assertEqual(state_update["type"], "state_update")
        self.assertIn("private_view", mulligan_request)
        self.assertEqual(mulligan_selected["type"], "mulligan_selected")
        self.assertFalse(mulligan_selected["do_mulligan"])

    def test_match_runner_applies_first_legal_action(self) -> None:
        state = create_game_state(self.catalog)
        state.players["P1"].current_cp = 1
        card = state.create_card_instance("1-0-040", "P1")
        state.players["P1"].hand.add(card.instance_id)
        runner = MatchRunner(
            state,
            players={"P1": FirstLegalPlayer(), "P2": FirstLegalPlayer()},
        )

        selected = runner.run_turn_action("P1")

        self.assertEqual(selected["type"], "drive_unit")
        self.assertEqual(len(state.players["P1"].battlefield.units), 1)

    def test_match_runner_requests_defender_block_after_attack(self) -> None:
        class PassPlayer:
            def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
                if legal_actions and legal_actions[0]["type"] == "no_block":
                    return legal_actions[0]
                return next(action for action in legal_actions if action["type"] == "attack")

        state = create_game_state(self.catalog)
        state.turn_no = 3
        attacker_card = state.create_card_instance("1-0-001", "P1")
        blocker_card = state.create_card_instance("1-0-001", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        blocker = state.create_unit(blocker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(blocker.unit_id)
        runner = MatchRunner(state, players={"P1": PassPlayer(), "P2": PassPlayer()})

        selected = runner.run_turn_action("P1")

        self.assertEqual(selected["type"], "attack")
        self.assertEqual(state.players["P2"].life, 6)
        self.assertNotIn("battle_started", [event.type for event in state.event_store.events])

    def test_match_runner_skips_block_choice_for_valkyrie_clara_attack(self) -> None:
        class BlockingPlayer:
            def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
                block = next((action for action in legal_actions if action["type"] == "block"), None)
                if block is not None:
                    return block
                return next(action for action in legal_actions if action["type"] == "attack")

        state = create_game_state(self.catalog)
        state.turn_no = 3
        attacker_card = state.create_card_instance("1-0-008", "P1")
        blocker_card = state.create_card_instance("1-0-045", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        blocker = state.create_unit(blocker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(blocker.unit_id)
        runner = MatchRunner(state, players={"P1": BlockingPlayer(), "P2": BlockingPlayer()})

        selected = runner.run_turn_action("P1")

        self.assertEqual(selected["type"], "attack")
        self.assertEqual(state.players["P2"].life, 6)
        self.assertFalse(blocker.exhausted)
        self.assertNotIn("block_declared", [event.type for event in state.event_store.events])

    def test_match_runner_processes_trigger_window_after_drive(self) -> None:
        catalog = dict(self.catalog)
        catalog["T-TRG-001"] = draw_window_card("T-TRG-001", "trigger", "TRIGGER_UNIT_ENTERED")
        state = create_game_state(catalog)
        state.players["P1"].current_cp = 1
        unit_card = state.create_card_instance("1-0-040", "P1")
        trigger_card = state.create_card_instance("T-TRG-001", "P1")
        first_draw = state.create_card_instance("1-0-001", "P1")
        second_draw = state.create_card_instance("1-0-004", "P1")
        state.players["P1"].hand.add(unit_card.instance_id)
        state.players["P1"].trigger_zone.add(trigger_card.instance_id)
        state.players["P1"].deck.cards.extend([first_draw.instance_id, second_draw.instance_id])
        runner = MatchRunner(state, players={"P1": FirstLegalPlayer(), "P2": FirstLegalPlayer()})

        runner.run_turn_action("P1")

        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].hand.cards, [first_draw.instance_id, second_draw.instance_id])
        trigger_event = next(event for event in state.event_store.events if event.type == "trigger_activated")
        self.assertEqual(trigger_event.payload["card"]["card_no"], "T-TRG-001")
        self.assertEqual(trigger_event.payload["card"]["category"], "trigger")

    def test_match_runner_processes_intercept_window_after_attack(self) -> None:
        class WindowAwarePlayer:
            def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
                for action in legal_actions:
                    if action["type"] == "activate_intercept":
                        return action
                if legal_actions and legal_actions[0]["type"] == "no_block":
                    return legal_actions[0]
                for action in legal_actions:
                    if action["type"] == "attack":
                        return action
                return legal_actions[0]

        catalog = dict(self.catalog)
        catalog["T-INT-001"] = draw_window_card("T-INT-001", "intercept", "INTERCEPT_ATTACK")
        state = create_game_state(catalog)
        state.turn_no = 3
        attacker_card = state.create_card_instance("1-0-001", "P1")
        intercept_card = state.create_card_instance("T-INT-001", "P1")
        draw_target = state.create_card_instance("1-0-004", "P1")
        attacker = state.create_unit(attacker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P1"].trigger_zone.add(intercept_card.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)
        runner = MatchRunner(state, players={"P1": WindowAwarePlayer(), "P2": WindowAwarePlayer()})

        runner.run_turn_action("P1")

        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].hand.cards, [draw_target.instance_id])
        self.assertEqual(state.players["P2"].life, 6)
        self.assertIn("intercept_activated", [event.type for event in state.event_store.events])

    def test_match_runner_processes_tailwind_intercept_after_owner_unit_enters(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        state.players["P1"].current_cp = 3
        unit_card = state.create_card_instance("1-0-041", "P1")
        intercept_card = state.create_card_instance("1-0-097", "P1")
        state.players["P1"].hand.add(unit_card.instance_id)
        state.players["P1"].trigger_zone.add(intercept_card.instance_id)
        runner = MatchRunner(state, players={"P1": FirstLegalPlayer(), "P2": FirstLegalPlayer()})

        runner.run_turn_action("P1")

        self.assertEqual(state.players["P1"].current_cp, 4)
        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [intercept_card.instance_id])
        self.assertIn("intercept_activated", [event.type for event in state.event_store.events])

    def test_unit_entered_intercept_does_not_activate_for_opponent_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P2"
        state.players["P2"].current_cp = 1
        unit_card = state.create_card_instance("1-0-001", "P2")
        intercept_card = state.create_card_instance("1-0-097", "P1")
        state.players["P2"].hand.add(unit_card.instance_id)
        state.players["P1"].trigger_zone.add(intercept_card.instance_id)
        runner = MatchRunner(state, players={"P1": FirstLegalPlayer(), "P2": FirstLegalPlayer()})

        runner.run_turn_action("P2")

        self.assertEqual(state.players["P1"].trigger_zone.cards, [intercept_card.instance_id])
        self.assertNotIn("intercept_activated", [event.type for event in state.event_store.events])

    def test_match_runner_replay_record_replays_window_choices(self) -> None:
        state = create_game_state(self.catalog, seed=7)
        state.turn_player_id = "P1"
        state.players["P1"].current_cp = 3
        unit_card = state.create_card_instance("1-0-041", "P1")
        intercept_card = state.create_card_instance("1-0-097", "P1")
        state.players["P1"].hand.add(unit_card.instance_id)
        state.players["P1"].trigger_zone.add(intercept_card.instance_id)
        initial_state = snapshot_match_initial_state(state)
        runner = MatchRunner(state, players={"P1": FirstLegalPlayer(), "P2": FirstLegalPlayer()})

        runner.run_turn_action("P1")
        record = runner.build_replay_record(initial_state)
        replayed = replay_match_record(self.catalog, record)

        self.assertEqual(replayed.event_store.to_list(), state.event_store.to_list())
        self.assertEqual(record["intents"][0]["type"], "match_turn_action")
        self.assertEqual(
            [choice["role"] for choice in record["intents"][0]["choices"]],
            ["turn_action", "window_action", "window_action", "window_action"],
        )

    def test_match_runner_replay_preserves_invalid_response_fallback(self) -> None:
        class InvalidPlayer:
            def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
                return {"type": "not_legal"}

        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        initial_state = snapshot_match_initial_state(state)
        runner = MatchRunner(state, players={"P1": InvalidPlayer(), "P2": InvalidPlayer()})

        runner.run_turn_action("P1")
        record = runner.build_replay_record(initial_state)
        replayed = replay_match_record(self.catalog, record)

        self.assertEqual(replayed.event_store.to_list(), state.event_store.to_list())
        self.assertIn("invalid_response", [event.type for event in state.event_store.events])

    def test_match_runner_runs_full_match_to_max_turns(self) -> None:
        class PassOnlyPlayer:
            def choose_action(self, _player_id: str, legal_actions: list[dict]) -> dict:
                for action in legal_actions:
                    if action.get("type") == "pass":
                        return action
                return legal_actions[-1]

        deck1 = parse_decklist({"cards": [{"card_no": "1-0-040", "count": 4}]}, self.catalog)
        deck2 = parse_decklist({"cards": [{"card_no": "1-0-001", "count": 4}]}, self.catalog)
        state = setup_match_state(
            self.catalog,
            {"P1": deck1, "P2": deck2},
            config=MatchSetupConfig(seed=3),
        )
        runner = MatchRunner(state, players={"P1": PassOnlyPlayer(), "P2": PassOnlyPlayer()})

        result = runner.run_match(max_turns=2, max_actions_per_turn=100)

        self.assertEqual(result.reason, "max_turns")
        self.assertEqual(result.turn_count, 2)
        self.assertIn(result.winner_player_id, {"P1", "P2", None})
        event_types = [event.type for event in state.event_store.events]
        self.assertEqual(event_types[0], "match_started")
        self.assertIn("turn_started", event_types)
        self.assertEqual(event_types[-1], "match_ended")

    def test_full_match_replay_record_replays_match_events(self) -> None:
        deck1 = parse_decklist({"cards": [{"card_no": "1-0-040", "count": 4}]}, self.catalog)
        deck2 = parse_decklist({"cards": [{"card_no": "1-0-001", "count": 4}]}, self.catalog)
        state = setup_match_state(
            self.catalog,
            {"P1": deck1, "P2": deck2},
            config=MatchSetupConfig(seed=4),
        )
        initial_state = snapshot_match_initial_state(state)
        runner = MatchRunner(state, players={"P1": FirstLegalPlayer(), "P2": FirstLegalPlayer()})

        runner.run_match(max_turns=2, max_actions_per_turn=10)
        record = runner.build_replay_record(initial_state)
        replayed = replay_match_record(self.catalog, record)

        self.assertEqual(replayed.event_store.to_list(), state.event_store.to_list())
        self.assertEqual(record["intents"][0]["type"], "match_started")
        self.assertEqual(record["intents"][-1]["type"], "match_ended")

    def test_match_runner_mulligan_phase_records_and_replays_result(self) -> None:
        class MulliganOncePlayer:
            def __init__(self) -> None:
                self.count_by_player: dict[str, int] = {}

            def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
                return legal_actions[0]

            def choose_mulligan_with_state(self, player_id: str, *, state) -> bool:
                count = self.count_by_player.get(player_id, 0)
                self.count_by_player[player_id] = count + 1
                return player_id == "P1" and count == 0

        deck1 = parse_decklist({"cards": [{"card_no": "1-0-040", "count": 8}]}, self.catalog)
        deck2 = parse_decklist({"cards": [{"card_no": "1-0-001", "count": 8}]}, self.catalog)
        state = setup_match_state(
            self.catalog,
            {"P1": deck1, "P2": deck2},
            config=MatchSetupConfig(seed=9),
        )
        initial_state = snapshot_match_initial_state(state)
        initial_hand = list(state.players["P1"].hand.cards)
        runner = MatchRunner(state, players={"P1": MulliganOncePlayer(), "P2": MulliganOncePlayer()})

        result = runner.run_match(max_turns=1, max_actions_per_turn=1)
        record = runner.build_replay_record(initial_state)
        replayed = replay_match_record(self.catalog, record)

        self.assertEqual(result.reason, "max_actions_per_turn")
        self.assertNotEqual(state.players["P1"].hand.cards, initial_hand)
        self.assertEqual(replayed.event_store.to_list(), state.event_store.to_list())
        mulligan_intents = [intent for intent in record["intents"] if intent["type"] == "mulligan"]
        self.assertEqual([intent["do_mulligan"] for intent in mulligan_intents], [True, False, False])
        self.assertIn("mulligan_performed", [event.type for event in state.event_store.events])

    def test_optional_unit_ability_passes_by_default_when_engine_called_directly(self) -> None:
        catalog = dict(self.catalog)
        catalog["T-OPT-001"] = optional_draw_unit("T-OPT-001")
        state = create_game_state(catalog)
        optional_card = state.create_card_instance("T-OPT-001", "P1")
        draw_target = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(optional_card.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)
        state.players["P1"].current_cp = 1

        from tojs_reborn.engine.actions import drive_unit

        drive_unit(state, "P1", optional_card.instance_id)

        event_types = [event.type for event in state.event_store.events]
        self.assertIn("choice_requested", event_types)
        self.assertIn("choice_selected", event_types)
        self.assertNotIn("ability_resolved", event_types)
        self.assertEqual(state.players["P1"].hand.cards, [])

    def test_match_runner_optional_unit_ability_choice_replays(self) -> None:
        class UseOptionalPlayer(FirstLegalPlayer):
            def choose_choice(self, player_id: str, *, request_id: str, choice: dict, legal_choices: list[dict]) -> dict:
                for legal_choice in legal_choices:
                    if legal_choice["type"] == "use_ability":
                        return legal_choice
                return legal_choices[0]

        catalog = dict(self.catalog)
        catalog["T-OPT-001"] = optional_draw_unit("T-OPT-001")
        state = create_game_state(catalog, seed=11)
        optional_card = state.create_card_instance("T-OPT-001", "P1")
        draw_target = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(optional_card.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)
        state.players["P1"].current_cp = 1
        initial_state = snapshot_match_initial_state(state)
        runner = MatchRunner(state, players={"P1": UseOptionalPlayer(), "P2": FirstLegalPlayer()})

        runner.run_turn_action("P1")
        record = runner.build_replay_record(initial_state)
        replayed = replay_match_record(catalog, record)

        self.assertEqual(state.players["P1"].hand.cards, [draw_target.instance_id])
        self.assertEqual(replayed.event_store.to_list(), state.event_store.to_list())
        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertEqual(
            [choice["role"] for choice in record["intents"][0]["choices"]],
            ["turn_action", "optional_ability"],
        )

    def test_match_runner_forced_cost_choice_replays(self) -> None:
        class AttackUseCostPlayer(FirstLegalPlayer):
            def __init__(self, cost_card_instance_id: str) -> None:
                self.cost_card_instance_id = cost_card_instance_id

            def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
                for legal_action in legal_actions:
                    if legal_action["type"] == "attack":
                        return legal_action
                return legal_actions[0]

            def choose_choice(self, player_id: str, *, request_id: str, choice: dict, legal_choices: list[dict]) -> dict:
                if choice["type"] == "cost_payment":
                    return {"card_instance_id": self.cost_card_instance_id}
                return legal_choices[0]

        state = create_game_state(self.catalog, seed=12)
        state.turn_no = 2
        attacker_card = state.create_card_instance("1-0-010", "P1")
        attacker = state.create_unit(attacker_card.instance_id)
        first_cost = state.create_card_instance("1-0-040", "P1")
        selected_cost = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P1"].hand.add(first_cost.instance_id)
        state.players["P1"].hand.add(selected_cost.instance_id)
        initial_state = snapshot_match_initial_state(state)
        runner = MatchRunner(
            state,
            players={"P1": AttackUseCostPlayer(selected_cost.instance_id), "P2": FirstLegalPlayer()},
        )

        runner.run_turn_action("P1")
        record = runner.build_replay_record(initial_state)
        replayed = replay_match_record(self.catalog, record)

        self.assertEqual(state.players["P1"].discard_pile.cards, [selected_cost.instance_id])
        self.assertEqual(replayed.event_store.to_list(), state.event_store.to_list())
        self.assertIn("ability_cost_paid", [event.type for event in state.event_store.events])
        self.assertNotIn("optional_ability", [event.payload.get("type") for event in state.event_store.events])
        self.assertEqual(
            [choice["role"] for choice in record["intents"][0]["choices"]],
            ["turn_action", "cost_payment", "block_action"],
        )

    def test_match_cli_runs_sample_match_and_writes_replay(self) -> None:
        output_dir = ROOT / "test_output" / "match_cli"
        output_dir.mkdir(parents=True, exist_ok=True)
        cards_path = output_dir / "cards.normalized.json"
        deck1_path = output_dir / "deck1.json"
        deck2_path = output_dir / "deck2.json"
        replay_path = output_dir / "replay.json"
        cards_path.write_text(
            json.dumps(
                {
                    "cards": [
                        {
                            "card_no": "1-0-040",
                            "category": "unit",
                            "color": "green",
                            "name": "Happaloid",
                            "cp": 1,
                            "bp_by_level": [1000, 1000, 1000],
                            "abilities": [],
                        },
                        {
                            "card_no": "1-0-001",
                            "category": "unit",
                            "color": "red",
                            "name": "Bloodhound",
                            "cp": 1,
                            "bp_by_level": [1000, 1000, 1000],
                            "abilities": [],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        deck1_path.write_text('{"cards":[{"card_name":"Happaloid","count":4}]}', encoding="utf-8")
        deck2_path.write_text('{"cards":[{"card_name":"Bloodhound","count":4}]}', encoding="utf-8")

        with redirect_stdout(StringIO()):
            exit_code = run_match_cli(
                [
                    "--cards",
                    str(cards_path),
                    "--deck1",
                    str(deck1_path),
                    "--deck2",
                    str(deck2_path),
                    "--p1",
                    "sample:pass",
                    "--p2",
                    "sample:pass",
                    "--seed",
                    "5",
                    "--max-turns",
                    "2",
                    "--max-actions-per-turn",
                    "100",
                    "--replay",
                    str(replay_path),
                    "--verify-replay",
                    "--check-integrity",
                ]
            )

        self.assertEqual(exit_code, 0)
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        self.assertEqual(replay["match_result"]["reason"], "max_turns")
        self.assertEqual(replay["intents"][0]["type"], "match_started")

    def test_match_cli_runs_random_and_aggressive_sample_players(self) -> None:
        output_dir = ROOT / "test_output" / "match_cli_v7_bots"
        output_dir.mkdir(parents=True, exist_ok=True)
        replay_path = output_dir / "replay.json"
        with redirect_stdout(StringIO()):
            exit_code = run_match_cli(
                [
                    "--cards",
                    "carddata/generated/cards.normalized.json",
                    "--deck1",
                    "decklists/sample_p1.json",
                    "--deck2",
                    "decklists/sample_p2.json",
                    "--p1",
                    "sample:random",
                    "--p2",
                    "sample:aggressive",
                    "--seed",
                    "7",
                    "--max-turns",
                    "2",
                    "--replay",
                    str(replay_path),
                    "--verify-replay",
                ]
            )

        self.assertEqual(exit_code, 0)
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        self.assertEqual(replay["seed"], 7)
        self.assertIn(replay["match_result"]["reason"], {"max_turns", "life_zero", "max_actions_per_turn"})
        action_choices = [
            choice
            for intent in replay["intents"]
            for choice in intent.get("choices", [])
            if choice.get("role") == "turn_action"
        ]
        self.assertTrue(any("legal_actions" in choice for choice in action_choices))

    def test_match_batch_cli_runs_multiple_seeds_with_replay_verification(self) -> None:
        self.assertEqual(parse_seed_spec("1,3-5"), [1, 3, 4, 5])
        output_dir = ROOT / "test_output" / "match_batch"
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = run_match_batch_cli(
                [
                    "--cards",
                    "carddata/generated/cards.normalized.json",
                    "--deck1",
                    "decklists/sample_p1.json",
                    "--deck2",
                    "decklists/sample_p2.json",
                    "--p1",
                    "sample:random",
                    "--p2",
                    "sample:aggressive",
                    "--seeds",
                    "1-2",
                    "--max-turns",
                    "2",
                    "--verify-replay",
                    "--check-integrity",
                    "--output-dir",
                    str(output_dir),
                ]
            )

        self.assertEqual(exit_code, 0)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([line["seed"] for line in lines], [1, 2])
        self.assertEqual({line["status"] for line in lines}, {"ok"})
        self.assertTrue(all("last_event" in line for line in lines))
        self.assertFalse(any(output_dir.glob("replay_seed_*.json")))

    def test_replay_cli_verifies_match_cli_replay(self) -> None:
        output_dir = ROOT / "test_output" / "replay_cli"
        output_dir.mkdir(parents=True, exist_ok=True)
        cards_path = output_dir / "cards.normalized.json"
        deck1_path = output_dir / "deck1.json"
        deck2_path = output_dir / "deck2.json"
        replay_path = output_dir / "replay.json"
        cards_path.write_text(
            json.dumps(
                {
                    "cards": [
                        {
                            "card_no": "1-0-040",
                            "category": "unit",
                            "color": "green",
                            "name": "Happaloid",
                            "cp": 1,
                            "bp_by_level": [1000, 1000, 1000],
                            "abilities": [],
                        },
                        {
                            "card_no": "1-0-001",
                            "category": "unit",
                            "color": "red",
                            "name": "Bloodhound",
                            "cp": 1,
                            "bp_by_level": [1000, 1000, 1000],
                            "abilities": [],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        deck1_path.write_text('{"cards":[{"card_name":"Happaloid","count":4}]}', encoding="utf-8")
        deck2_path.write_text('{"cards":[{"card_name":"Bloodhound","count":4}]}', encoding="utf-8")
        with redirect_stdout(StringIO()):
            self.assertEqual(
                run_match_cli(
                    [
                        "--cards",
                        str(cards_path),
                        "--deck1",
                        str(deck1_path),
                        "--deck2",
                        str(deck2_path),
                        "--max-turns",
                        "2",
                        "--replay",
                        str(replay_path),
                    ]
                ),
                0,
            )

        with redirect_stdout(StringIO()):
            exit_code = run_replay_cli(["--cards", str(cards_path), "--replay", str(replay_path)])

        self.assertEqual(exit_code, 0)

    def test_replay_viewer_formats_events_as_one_line_logs(self) -> None:
        replay_record = {
            "initial_state": {
                "card_instances": {
                    "c0001": {"card_no": "1-0-040", "owner_player_id": "P1", "level": 1}
                },
                "players": {
                    "P1": {
                        "life": 7,
                        "current_cp": 0,
                        "deck": [],
                        "hand": ["c0001"],
                        "battlefield": [],
                        "trigger_zone": [],
                        "discard_pile": [],
                    }
                },
                "units": {},
            },
            "events": [
                {
                    "event_no": 1,
                    "type": "action_declared",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": None, "ability_id": None},
                    "payload": {"action": "drive_unit", "card_instance_id": "c0001"},
                },
                {
                    "event_no": 2,
                    "type": "card_moved",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": 1,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": None},
                    "payload": {"from_zone": "hand", "to_zone": "battlefield", "owner_player_id": "P1"},
                },
                {
                    "event_no": 3,
                    "type": "turn_ended",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": None, "card_instance_id": None, "unit_id": None, "ability_id": None},
                    "payload": {},
                }
            ],
        }

        lines = format_replay_events(replay_record, card_catalog=self.catalog)

        self.assertEqual(len(lines), 5)
        self.assertIn("0001 R1 T1 actor=P1 cause=- action_declared", lines[0])
        self.assertIn(self.catalog["1-0-040"].name, lines[0])
        self.assertIn('"card_instance_id_card"', lines[0])
        self.assertEqual(lines[3], "     state:")
        self.assertIn("P1 life=7 cp=0 hand=0 deck=0 discard=0", lines[4])
        self.assertIn("u0001:", lines[4])

    def test_replay_viewer_applies_mulligan_and_filters_output(self) -> None:
        replay_record = {
            "initial_state": {
                "card_instances": {
                    "c0001": {"card_no": "1-0-040", "owner_player_id": "P1", "level": 1},
                    "c0002": {"card_no": "1-0-001", "owner_player_id": "P1", "level": 1},
                    "c0003": {"card_no": "1-0-004", "owner_player_id": "P1", "level": 1},
                    "c0004": {"card_no": "1-0-005", "owner_player_id": "P1", "level": 1},
                },
                "players": {
                    "P1": {
                        "life": 7,
                        "current_cp": 0,
                        "deck": ["c0003", "c0004"],
                        "hand": ["c0001", "c0002"],
                        "battlefield": [],
                        "trigger_zone": [],
                        "discard_pile": [],
                    }
                },
                "units": {},
            },
            "events": [
                {
                    "event_no": 1,
                    "type": "mulligan_requested",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": None, "card_instance_id": None, "unit_id": None, "ability_id": None},
                    "payload": {"attempt": 1},
                },
                {
                    "event_no": 2,
                    "type": "mulligan_performed",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": None, "card_instance_id": None, "unit_id": None, "ability_id": None},
                    "payload": {
                        "attempt": 1,
                        "returned_card_instance_ids": ["c0001", "c0002"],
                        "deck_card_instance_ids_after_shuffle": ["c0004", "c0001", "c0003", "c0002"],
                        "drawn_card_instance_ids": ["c0004", "c0001"],
                        "hand_card_instance_ids": ["c0004", "c0001"],
                        "deck_card_instance_ids": ["c0003", "c0002"],
                    },
                },
                {
                    "event_no": 3,
                    "type": "match_ended",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": None,
                    "cause_event_no": None,
                    "source": {"card_no": None, "card_instance_id": None, "unit_id": None, "ability_id": None},
                    "payload": {"winner_player_id": None, "reason": "test", "turn_count": 0},
                },
            ],
        }

        lines = format_replay_events(
            replay_record,
            card_catalog=self.catalog,
            event_types={"match_ended"},
            only_state=True,
        )

        self.assertEqual(lines[0], "     state:")
        self.assertIn("P1 life=7 cp=0 hand=2 deck=2 discard=0", lines[1])

    def test_replay_viewer_formats_recorded_legal_and_selected_actions(self) -> None:
        replay_record = {
            "initial_state": {
                "card_instances": {
                    "c0001": {"card_no": "1-0-040", "owner_player_id": "P1", "level": 1}
                },
                "players": {},
                "units": {},
            },
            "intents": [
                {
                    "type": "match_turn_action",
                    "player_id": "P1",
                    "choices": [
                        {
                            "player_id": "P1",
                            "role": "turn_action",
                            "legal_actions": [
                                {"type": "drive_unit", "card_instance_id": "c0001"},
                                {"type": "pass"},
                            ],
                            "response": {"type": "drive_unit", "card_instance_id": "c0001"},
                        }
                    ],
                }
            ],
            "events": [],
        }

        lines = format_replay_actions(replay_record, card_catalog=self.catalog)

        self.assertEqual(len(lines), 1)
        self.assertIn("role=turn_action", lines[0])
        self.assertIn("selected=drive_unit", lines[0])
        self.assertIn(self.catalog["1-0-040"].name, lines[0])

    def test_replay_gui_model_places_action_lines_on_matching_events(self) -> None:
        replay_record = {
            "initial_state": {
                "round_no": 1,
                "turn_no": 1,
                "turn_player_id": "P1",
                "card_instances": {
                    "c0001": {"card_no": "1-0-040", "owner_player_id": "P1", "level": 1},
                    "c0002": {"card_no": "1-0-001", "owner_player_id": "P1", "level": 1},
                    "c0003": {"card_no": "1-0-004", "owner_player_id": "P1", "level": 1},
                },
                "players": {},
                "units": {},
            },
            "intents": [
                {
                    "type": "match_turn_action",
                    "player_id": "P1",
                    "choices": [
                        {
                            "player_id": "P1",
                            "role": "turn_action",
                            "legal_actions": [{"type": "drive_unit", "card_instance_id": "c0001"}],
                            "response": {"type": "drive_unit", "card_instance_id": "c0001"},
                        },
                        {
                            "player_id": "P1",
                            "role": "turn_action",
                            "legal_actions": [{"type": "set_trigger", "card_instance_id": "c0002"}],
                            "response": {"type": "set_trigger", "card_instance_id": "c0002"},
                        },
                        {
                            "player_id": "P1",
                            "role": "turn_action",
                            "legal_actions": [
                                {
                                    "type": "override_card",
                                    "target_card_instance_id": "c0002",
                                    "material_card_instance_id": "c0003",
                                }
                            ],
                            "response": {
                                "type": "override_card",
                                "target_card_instance_id": "c0002",
                                "material_card_instance_id": "c0003",
                            },
                        },
                        {
                            "player_id": "P1",
                            "role": "turn_action",
                            "legal_actions": [{"type": "attack", "attacker_unit_id": "u0001"}],
                            "response": {"type": "attack", "attacker_unit_id": "u0001"},
                        },
                    ],
                }
            ],
            "events": [
                {
                    "event_no": 1,
                    "type": "action_declared",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": None, "ability_id": None},
                    "payload": {"action": "drive_unit", "card_instance_id": "c0001"},
                },
                {
                    "event_no": 2,
                    "type": "action_declared",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-001", "card_instance_id": "c0002", "unit_id": None, "ability_id": None},
                    "payload": {"action": "set_trigger", "card_instance_id": "c0002"},
                },
                {
                    "event_no": 3,
                    "type": "action_declared",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-001", "card_instance_id": "c0002", "unit_id": None, "ability_id": None},
                    "payload": {
                        "action": "override_card",
                        "target_card_instance_id": "c0002",
                        "material_card_instance_id": "c0003",
                    },
                },
                {
                    "event_no": 4,
                    "type": "action_declared",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": None},
                    "payload": {"action": "attack", "attacker_unit_id": "u0001"},
                },
            ],
        }

        model = build_replay_gui_model(replay_record, card_catalog=self.catalog)

        action_lines = model["action_lines_by_event_index"]
        self.assertIn("selected=drive_unit", action_lines[0][0])
        self.assertIn("selected=set_trigger", action_lines[1][0])
        self.assertIn("selected=override_card", action_lines[2][0])
        self.assertIn("selected=attack", action_lines[3][0])

    def test_replay_gui_model_places_all_choice_selected_lines_on_matching_events(self) -> None:
        replay_record = {
            "initial_state": {
                "round_no": 1,
                "turn_no": 1,
                "turn_player_id": "P1",
                "card_instances": {
                    "c0001": {"card_no": "1-0-040", "owner_player_id": "P1", "level": 1},
                    "c0002": {"card_no": "1-0-001", "owner_player_id": "P1", "level": 1},
                    "c0003": {"card_no": "1-0-004", "owner_player_id": "P1", "level": 1},
                },
                "players": {},
                "units": {},
            },
            "intents": [
                {
                    "type": "match_turn_action",
                    "player_id": "P1",
                    "choices": [
                        {
                            "player_id": "P1",
                            "role": "optional_ability",
                            "response": {"type": "use_ability", "ability_id": "a1"},
                        },
                        {
                            "player_id": "P1",
                            "role": "cost_payment",
                            "response": {"card_instance_ids": ["c0001", "c0002"]},
                        },
                    ],
                }
            ],
            "events": [
                {
                    "event_no": 1,
                    "type": "choice_selected",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": 0,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": "a1"},
                    "payload": {"type": "optional_ability", "ability_id": "a1", "choice": "use_ability"},
                },
                {
                    "event_no": 2,
                    "type": "choice_selected",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": 0,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": "a1"},
                    "payload": {
                        "type": "cost_payment",
                        "effect": "discard_from_hand",
                        "choice": {"card_instance_ids": ["c0001", "c0002"]},
                    },
                },
                {
                    "event_no": 3,
                    "type": "choice_selected",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": 0,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": "a1"},
                    "payload": {
                        "choice_id": "target",
                        "chosen_card_instance_id": "c0003",
                        "fallback": "first_legal",
                    },
                },
            ],
        }

        model = build_replay_gui_model(replay_record, card_catalog=self.catalog)

        action_lines = model["action_lines_by_event_index"]
        self.assertIn("role=optional_ability", action_lines[0][0])
        self.assertIn("selected=use_ability", action_lines[0][0])
        self.assertIn("role=cost_payment", action_lines[1][0])
        self.assertIn("c0002", action_lines[1][0])
        self.assertIn("event=3", action_lines[2][0])
        self.assertIn("c0003", action_lines[2][0])

    def test_replay_gui_model_marks_ability_resolved_event_lines_bold(self) -> None:
        replay_record = {
            "initial_state": {
                "round_no": 1,
                "turn_no": 1,
                "turn_player_id": "P1",
                "card_instances": {
                    "c0001": {"card_no": "1-0-040", "owner_player_id": "P1", "level": 1},
                },
                "players": {},
                "units": {},
            },
            "events": [
                {
                    "event_no": 1,
                    "type": "unit_entered",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": None},
                    "payload": {},
                },
                {
                    "event_no": 2,
                    "type": "ability_resolved",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": 1,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": "1-0-040:a1"},
                    "payload": {"ability_name": "draw", "timing": "SELF_CIP", "optional": False},
                },
            ],
        }

        model = build_replay_gui_model(replay_record, card_catalog=self.catalog)

        self.assertEqual(model["event_line_tags"], [None, "action"])
        self.assertIn("ability_resolved", model["event_lines"][1])

    def test_replay_gui_model_updates_hand_card_level_by_event_timing(self) -> None:
        replay_record = {
            "initial_state": {
                "round_no": 1,
                "turn_no": 1,
                "turn_player_id": "P1",
                "card_instances": {
                    "c0001": {"card_no": "1-0-031", "owner_player_id": "P1", "level": 1},
                    "c0002": {"card_no": "1-0-031", "owner_player_id": "P1", "level": 1},
                    "c0003": {"card_no": "1-0-031", "owner_player_id": "P1", "level": 1},
                },
                "players": {
                    "P1": {
                        "life": 7,
                        "current_cp": 10,
                        "deck": [],
                        "hand": ["c0001", "c0002", "c0003"],
                        "battlefield": [],
                        "trigger_zone": [],
                        "discard_pile": [],
                    }
                },
                "units": {},
            },
            "events": [
                {
                    "event_no": 1,
                    "type": "card_moved",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-031", "card_instance_id": "c0002", "unit_id": None, "ability_id": None},
                    "payload": {"from_zone": "hand", "to_zone": "discard_pile", "owner_player_id": "P1"},
                },
                {
                    "event_no": 2,
                    "type": "card_level_changed",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-031", "card_instance_id": "c0001", "unit_id": None, "ability_id": None},
                    "payload": {"before_level": 1, "after_level": 2, "zone": "hand"},
                },
                {
                    "event_no": 3,
                    "type": "card_moved",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-031", "card_instance_id": "c0003", "unit_id": None, "ability_id": None},
                    "payload": {"from_zone": "hand", "to_zone": "discard_pile", "owner_player_id": "P1"},
                },
                {
                    "event_no": 4,
                    "type": "card_level_changed",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-031", "card_instance_id": "c0001", "unit_id": None, "ability_id": None},
                    "payload": {"before_level": 2, "after_level": 3, "zone": "hand"},
                },
            ],
        }

        model = build_replay_gui_model(replay_record, card_catalog=self.catalog)

        self.assertEqual(model["frames"][0]["players"][0]["hand"][0]["level"], 1)
        self.assertEqual(model["frames"][2]["players"][0]["hand"][0]["level"], 2)
        self.assertEqual(model["frames"][4]["players"][0]["hand"][0]["level"], 3)

    def test_replay_gui_model_applies_card_moved_after_level_to_returned_hand_card(self) -> None:
        replay_record = {
            "initial_state": {
                "round_no": 1,
                "turn_no": 1,
                "turn_player_id": "P1",
                "card_instances": {
                    "c0001": {"card_no": "1-0-001", "owner_player_id": "P2", "level": 2},
                },
                "players": {
                    "P1": {
                        "life": 7,
                        "current_cp": 0,
                        "deck": [],
                        "hand": [],
                        "battlefield": [],
                        "trigger_zone": [],
                        "discard_pile": [],
                    },
                    "P2": {
                        "life": 7,
                        "current_cp": 0,
                        "deck": [],
                        "hand": [],
                        "battlefield": ["u0001"],
                        "trigger_zone": [],
                        "discard_pile": [],
                    },
                },
                "units": {
                    "u0001": {
                        "card_instance_id": "c0001",
                        "card_no": "1-0-001",
                        "owner_player_id": "P2",
                        "level": 2,
                        "exhausted": False,
                        "attack_restricted_turn_no": None,
                        "current_damage": 0,
                    }
                },
            },
            "events": [
                {
                    "event_no": 1,
                    "type": "card_moved",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P2",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-001", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": None},
                    "payload": {
                        "from_zone": "battlefield",
                        "to_zone": "hand",
                        "owner_player_id": "P2",
                        "reason": "return_unit",
                        "before_level": 2,
                        "after_level": 1,
                    },
                }
            ],
        }

        model = build_replay_gui_model(replay_record, card_catalog=self.catalog)

        p2_after_return = model["frames"][1]["players"][1]
        self.assertEqual(p2_after_return["battlefield"], [])
        self.assertEqual(p2_after_return["hand"][0]["card_instance_id"], "c0001")
        self.assertEqual(p2_after_return["hand"][0]["level"], 1)

    def test_replay_gui_model_builds_seekable_full_information_frames(self) -> None:
        replay_record = {
            "seed": 7,
            "initial_state": {
                "round_no": 1,
                "turn_no": 1,
                "turn_player_id": "P1",
                "card_instances": {
                    "c0001": {"card_no": "1-0-040", "owner_player_id": "P1", "level": 1},
                    "c0002": {"card_no": "1-0-001", "owner_player_id": "P1", "level": 1},
                    "c0003": {"card_no": "1-0-004", "owner_player_id": "P2", "level": 1},
                },
                "players": {
                    "P1": {
                        "life": 7,
                        "current_cp": 2,
                        "deck": ["c0002"],
                        "hand": ["c0001"],
                        "battlefield": [],
                        "trigger_zone": [],
                        "discard_pile": [],
                    },
                    "P2": {
                        "life": 7,
                        "current_cp": 3,
                        "deck": ["c0003"],
                        "hand": [],
                        "battlefield": [],
                        "trigger_zone": [],
                        "discard_pile": [],
                    },
                },
                "units": {},
            },
            "events": [
                {
                    "event_no": 1,
                    "type": "card_moved",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": None},
                    "payload": {"from_zone": "hand", "to_zone": "battlefield", "owner_player_id": "P1"},
                },
                {
                    "event_no": 2,
                    "type": "unit_attacked",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": 1,
                    "source": {"card_no": "1-0-040", "card_instance_id": "c0001", "unit_id": "u0001", "ability_id": None},
                    "payload": {"attacker_unit_id": "u0001"},
                },
                {
                    "event_no": 3,
                    "type": "match_ended",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": None,
                    "cause_event_no": None,
                    "source": {"card_no": None, "card_instance_id": None, "unit_id": None, "ability_id": None},
                    "payload": {"winner_player_id": "P1", "reason": "test", "turn_count": 1},
                },
            ],
        }
        image_dir = ROOT / "test_output" / "replay_gui_images"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / "1-0-040_sample.jpg"
        image_path.write_bytes(b"fake image")

        model = build_replay_gui_model(replay_record, card_catalog=self.catalog, images_dir=image_dir)

        self.assertEqual(model["seed"], 7)
        self.assertEqual(model["match_result"]["winner_player_id"], "P1")
        self.assertEqual(len(model["frames"]), 4)
        initial_p1 = model["frames"][0]["players"][0]
        after_move_p1 = model["frames"][1]["players"][0]
        after_attack_p1 = model["frames"][2]["players"][0]
        self.assertEqual(initial_p1["status"]["hand_count"], 1)
        self.assertEqual(initial_p1["status"]["deck_count"], 1)
        self.assertEqual(initial_p1["hand"][0]["level"], 1)
        self.assertEqual(after_move_p1["status"]["hand_count"], 0)
        self.assertEqual(after_move_p1["status"]["battlefield_count"], 1)
        self.assertEqual(after_move_p1["battlefield"][0]["unit_id"], "u0001")
        self.assertEqual(after_move_p1["battlefield"][0]["image_path"], str(image_path))
        self.assertEqual(after_move_p1["battlefield"][0]["level"], 1)
        self.assertEqual(after_move_p1["battlefield"][0]["current_bp"], card_bp_to_game_bp(self.catalog["1-0-040"].bp_by_level[0]))
        self.assertFalse(after_move_p1["battlefield"][0]["exhausted"])
        self.assertTrue(after_attack_p1["battlefield"][0]["exhausted"])
        self.assertEqual(model["frames"][1]["current_event"]["description"], "#1 card_moved actor=P1")

    def test_replay_gui_model_inserts_evolve_unit_at_recorded_battlefield_index(self) -> None:
        replay_record = {
            "initial_state": {
                "round_no": 1,
                "turn_no": 1,
                "turn_player_id": "P1",
                "card_instances": {
                    "c0001": {"card_no": "1-0-028", "owner_player_id": "P1", "level": 1},
                    "c0002": {"card_no": "1-0-021", "owner_player_id": "P1", "level": 1},
                    "c0003": {"card_no": "1-0-027", "owner_player_id": "P1", "level": 1},
                    "c0004": {"card_no": "1-0-026", "owner_player_id": "P1", "level": 1},
                },
                "players": {
                    "P1": {
                        "life": 7,
                        "current_cp": 7,
                        "deck": [],
                        "hand": ["c0004"],
                        "battlefield": ["u0001", "u0002", "u0003"],
                        "trigger_zone": [],
                        "discard_pile": [],
                    }
                },
                "units": {
                    "u0001": {"card_instance_id": "c0001", "card_no": "1-0-028", "owner_player_id": "P1", "level": 1, "exhausted": False, "attack_restricted_turn_no": None, "current_damage": 0},
                    "u0002": {"card_instance_id": "c0002", "card_no": "1-0-021", "owner_player_id": "P1", "level": 1, "exhausted": False, "attack_restricted_turn_no": None, "current_damage": 0},
                    "u0003": {"card_instance_id": "c0003", "card_no": "1-0-027", "owner_player_id": "P1", "level": 1, "exhausted": False, "attack_restricted_turn_no": None, "current_damage": 0},
                },
            },
            "events": [
                {
                    "event_no": 1,
                    "type": "card_moved",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-021", "card_instance_id": "c0002", "unit_id": "u0002", "ability_id": None},
                    "payload": {"from_zone": "battlefield", "to_zone": "discard_pile", "owner_player_id": "P1", "reason": "evolve_source"},
                },
                {
                    "event_no": 2,
                    "type": "card_moved",
                    "round_no": 1,
                    "turn_no": 1,
                    "actor_player_id": "P1",
                    "cause_event_no": None,
                    "source": {"card_no": "1-0-026", "card_instance_id": "c0004", "unit_id": "u0004", "ability_id": None},
                    "payload": {"from_zone": "hand", "to_zone": "battlefield", "owner_player_id": "P1", "battlefield_index": 1},
                },
            ],
        }

        model = build_replay_gui_model(replay_record, card_catalog=self.catalog)

        battlefield = model["frames"][2]["players"][0]["battlefield"]
        self.assertEqual([unit["unit_id"] for unit in battlefield], ["u0001", "u0004", "u0003"])

    def test_replay_viewer_cli_prints_match_cli_replay(self) -> None:
        output_dir = ROOT / "test_output" / "replay_viewer"
        output_dir.mkdir(parents=True, exist_ok=True)
        cards_path = output_dir / "cards.normalized.json"
        deck1_path = output_dir / "deck1.json"
        deck2_path = output_dir / "deck2.json"
        replay_path = output_dir / "replay.json"
        cards_path.write_text(
            json.dumps(
                {
                    "cards": [
                        {
                            "card_no": "1-0-040",
                            "category": "unit",
                            "color": "green",
                            "name": "Happaloid",
                            "cp": 1,
                            "bp_by_level": [1000, 1000, 1000],
                            "abilities": [],
                        },
                        {
                            "card_no": "1-0-001",
                            "category": "unit",
                            "color": "red",
                            "name": "Bloodhound",
                            "cp": 1,
                            "bp_by_level": [1000, 1000, 1000],
                            "abilities": [],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        deck1_path.write_text('{"cards":[{"card_name":"Happaloid","count":4}]}', encoding="utf-8")
        deck2_path.write_text('{"cards":[{"card_name":"Bloodhound","count":4}]}', encoding="utf-8")
        with redirect_stdout(StringIO()):
            self.assertEqual(
                run_match_cli(
                    [
                        "--cards",
                        str(cards_path),
                        "--deck1",
                        str(deck1_path),
                        "--deck2",
                        str(deck2_path),
                        "--max-turns",
                        "1",
                        "--replay",
                        str(replay_path),
                    ]
                ),
                0,
            )
        output = StringIO()
        with redirect_stdout(output):
            exit_code = run_replay_viewer_cli(["--cards", str(cards_path), "--replay", str(replay_path)])

        self.assertEqual(exit_code, 0)
        lines = output.getvalue().splitlines()
        self.assertGreater(len(lines), 1)
        self.assertTrue(lines[0].startswith("0001 R1 T1 actor=- cause=- match_started"))
        self.assertTrue(any(line == "     state:" for line in lines))
        self.assertTrue(any("battlefield=[" in line for line in lines))

    def test_replay_gui_cli_no_window_prints_selected_frame_summary(self) -> None:
        output_dir = ROOT / "test_output" / "replay_gui_cli"
        output_dir.mkdir(parents=True, exist_ok=True)
        replay_path = output_dir / "replay.json"
        replay_path.write_text(
            json.dumps(
                {
                    "seed": 11,
                    "initial_state": {
                        "round_no": 1,
                        "turn_no": 1,
                        "turn_player_id": "P1",
                        "card_instances": {
                            "c0001": {"card_no": "1-0-040", "owner_player_id": "P1", "level": 1}
                        },
                        "players": {
                            "P1": {
                                "life": 7,
                                "current_cp": 2,
                                "deck": [],
                                "hand": ["c0001"],
                                "battlefield": [],
                                "trigger_zone": [],
                                "discard_pile": [],
                            }
                        },
                        "units": {},
                    },
                    "events": [
                        {
                            "event_no": 1,
                            "type": "card_moved",
                            "round_no": 1,
                            "turn_no": 1,
                            "actor_player_id": "P1",
                            "cause_event_no": None,
                            "source": {
                                "card_no": "1-0-040",
                                "card_instance_id": "c0001",
                                "unit_id": "u0001",
                                "ability_id": None,
                            },
                            "payload": {"from_zone": "hand", "to_zone": "battlefield", "owner_player_id": "P1"},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        output = StringIO()
        with redirect_stdout(output):
            exit_code = run_replay_gui_cli(
                [
                    "--replay",
                    str(replay_path),
                    "--cards",
                    str(output_dir / "missing_cards.json"),
                    "--images",
                    str(output_dir / "images"),
                    "--start-event-no",
                    "1",
                    "--fullscreen",
                    "--no-window",
                ]
            )

        self.assertEqual(exit_code, 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["seed"], 11)
        self.assertEqual(summary["frame_index"], 1)
        self.assertEqual(summary["current_event"]["type"], "card_moved")
        self.assertEqual(summary["players"][0]["status"]["hand_count"], 0)
        self.assertEqual(summary["players"][0]["status"]["battlefield_count"], 1)

    def test_replay_gui_fullscreen_uses_zoomed_window_state(self) -> None:
        class FakeRoot:
            def __init__(self) -> None:
                self.states: list[str] = []
                self.attributes_calls: list[tuple[str, bool]] = []

            def state(self, value: str) -> None:
                self.states.append(value)

            def attributes(self, name: str, value: bool) -> None:
                self.attributes_calls.append((name, value))

        gui = ReplayTkGui.__new__(ReplayTkGui)
        gui.root = FakeRoot()
        gui.tk = type("FakeTk", (), {"TclError": RuntimeError})

        gui._apply_fullscreen(True)

        self.assertEqual(gui.root.states, ["zoomed"])
        self.assertEqual(gui.root.attributes_calls, [])

    def test_scenario_cli_generates_replays_for_gui_inspection(self) -> None:
        output_dir = ROOT / "test_output" / "scenario_cli"
        output_dir.mkdir(parents=True, exist_ok=True)

        output = StringIO()
        with redirect_stdout(output):
            exit_code = run_scenario_cli(
                [
                    "--cards",
                    "carddata/generated/cards.normalized.json",
                    "--scenario",
                    "all",
                    "--output-dir",
                    str(output_dir),
                    "--verify",
                ]
            )

        self.assertEqual(exit_code, 0)
        result = json.loads(output.getvalue())
        scenario_names = {item["scenario"] for item in result["outputs"]}
        self.assertEqual(
            scenario_names,
            {
                "attack_bp_modifier",
                "attack_consume_action",
                "bishamon_evolve_destroy_all",
                "block_bypass_player_attack",
                "bloodhound_level3_damage",
                "dartagnan_cip_attack_draw",
                "display_stand_trigger_draw",
                "goliath_level3_life_damage",
                "hand_limit_draw",
                "happaloid_cip_draw",
                "howling_intercept_draw_two",
                "jumpoo_bounce_hand_limit",
                "kaim_cip_trigger_search",
                "leafia_block_bp_modifier",
                "lina_discard_choice",
                "new_armor_trigger",
                "oc_consume_action",
                "raguel_exhausted_damage",
                "rairyu_evolve_damage",
                "tailwind_intercept_cp",
                "viper_discard_unit_recover",
            },
        )
        for item in result["outputs"]:
            replay = json.loads((output_dir / f"{item['scenario']}.json").read_text(encoding="utf-8"))
            initial_card_counts_by_owner: dict[str, Counter[str]] = {}
            for card in replay["initial_state"]["card_instances"].values():
                initial_card_counts_by_owner.setdefault(card["owner_player_id"], Counter())[card["card_no"]] += 1
            for player_id, player in replay["initial_state"]["players"].items():
                initial_deck_card_nos = player["initial_deck_card_nos"]
                if initial_deck_card_nos:
                    initial_deck_counts = Counter(initial_deck_card_nos)
                    self.assertLessEqual(max(initial_deck_counts.values()), 3)
                    self.assertEqual(initial_card_counts_by_owner.get(player_id, Counter()), initial_deck_counts)
        bishamon = json.loads((output_dir / "bishamon_evolve_destroy_all.json").read_text(encoding="utf-8"))
        attack_bp = json.loads((output_dir / "attack_bp_modifier.json").read_text(encoding="utf-8"))
        self.assertIn("bp_modified", [event["type"] for event in attack_bp["events"]])
        self.assertIn("modifier_expired", [event["type"] for event in attack_bp["events"]])
        attack_consume = json.loads((output_dir / "attack_consume_action.json").read_text(encoding="utf-8"))
        self.assertIn("unit_action_consumed", [event["type"] for event in attack_consume["events"]])
        attack_consume_choices = [event for event in attack_consume["events"] if event["type"] == "choice_requested"]
        self.assertEqual(len(attack_consume_choices[-1]["payload"].get("candidate_unit_ids")), 1)
        block_bypass = json.loads((output_dir / "block_bypass_player_attack.json").read_text(encoding="utf-8"))
        self.assertIn("life_changed", [event["type"] for event in block_bypass["events"]])
        self.assertNotIn("block_declared", [event["type"] for event in block_bypass["events"]])
        self.assertEqual(block_bypass["final_state"]["players"]["P2"]["life"], 6)
        self.assertEqual([event["type"] for event in bishamon["events"]].count("unit_destroyed"), 3)
        initial_bishamon_units = bishamon["initial_state"]["players"]["P1"]["battlefield"]
        self.assertEqual(
            [
                bishamon["initial_state"]["units"][unit_id]["card_no"]
                for unit_id in initial_bishamon_units
            ],
            ["1-0-028", "1-0-021", "1-0-027"],
        )
        bishamon_move = next(
            event
            for event in bishamon["events"]
            if event["type"] == "card_moved" and event["source"].get("card_no") == "1-0-026"
        )
        self.assertEqual(bishamon_move["payload"].get("battlefield_index"), 1)
        bishamon_model = build_replay_gui_model(bishamon, card_catalog=self.catalog)
        bishamon_frame = bishamon_model["frames"][bishamon["events"].index(bishamon_move) + 1]
        self.assertEqual(
            [unit["card_no"] for unit in bishamon_frame["players"][0]["battlefield"]],
            ["1-0-028", "1-0-026", "1-0-027"],
        )
        final_bishamon = bishamon["final_state"]
        p1_battlefield = final_bishamon["players"]["P1"]["battlefield"]
        self.assertEqual(len(p1_battlefield), 1)
        self.assertEqual(final_bishamon["units"][p1_battlefield[0]]["card_no"], "1-0-026")
        self.assertTrue(final_bishamon["units"][p1_battlefield[0]]["exhausted"])
        self.assertEqual(final_bishamon["players"]["P2"]["life"], 6)
        p1_hand_card_nos = [
            final_bishamon["card_instances"][card_instance_id]["card_no"]
            for card_instance_id in final_bishamon["players"]["P1"]["hand"]
        ]
        self.assertIn("1-0-021", p1_hand_card_nos)
        self.assertEqual(len(final_bishamon["players"]["P2"]["hand"]), 2)
        self.assertEqual(len(final_bishamon["players"]["P2"]["deck"]), 1)
        p2_hand_card_nos = [
            final_bishamon["card_instances"][card_instance_id]["card_no"]
            for card_instance_id in final_bishamon["players"]["P2"]["hand"]
        ]
        self.assertIn("1-0-097", p2_hand_card_nos)
        bloodhound = json.loads((output_dir / "bloodhound_level3_damage.json").read_text(encoding="utf-8"))
        damage_events = [event for event in bloodhound["events"] if event["type"] == "damage_dealt"]
        self.assertEqual(damage_events[-1]["payload"].get("amount"), 4000)
        self.assertIn("unit_destroyed", [event["type"] for event in bloodhound["events"]])
        dartagnan = json.loads((output_dir / "dartagnan_cip_attack_draw.json").read_text(encoding="utf-8"))
        dartagnan_ability_ids = [
            event["source"].get("ability_id") for event in dartagnan["events"] if event["type"] == "ability_resolved"
        ]
        self.assertEqual(dartagnan_ability_ids, ["1-0-047:a1", "1-0-047:a2"])
        self.assertEqual([event for event in dartagnan["events"] if event["type"] == "cards_drawn"][-1]["payload"].get("count"), 1)
        self.assertEqual(dartagnan["final_state"]["players"]["P2"]["life"], 6)
        display_stand = json.loads((output_dir / "display_stand_trigger_draw.json").read_text(encoding="utf-8"))
        self.assertIn("trigger_activated", [event["type"] for event in display_stand["events"]])
        self.assertIn("cards_drawn", [event["type"] for event in display_stand["events"]])
        goliath = json.loads((output_dir / "goliath_level3_life_damage.json").read_text(encoding="utf-8"))
        goliath_life_events = [event for event in goliath["events"] if event["type"] == "life_changed"]
        self.assertEqual(goliath_life_events[-1]["payload"].get("amount"), -1)
        self.assertEqual(goliath["final_state"]["players"]["P2"]["life"], 6)
        self.assertIn("unit_overclocked", [event["type"] for event in goliath["events"]])
        happaloid = json.loads((output_dir / "happaloid_cip_draw.json").read_text(encoding="utf-8"))
        self.assertIn("cards_drawn", [event["type"] for event in happaloid["events"]])
        hand_limit = json.loads((output_dir / "hand_limit_draw.json").read_text(encoding="utf-8"))
        self.assertEqual(hand_limit["scenario"]["name"], "hand_limit_draw")
        self.assertIn("draw_skipped", [event["type"] for event in hand_limit["events"]])
        howling = json.loads((output_dir / "howling_intercept_draw_two.json").read_text(encoding="utf-8"))
        self.assertIn("intercept_activated", [event["type"] for event in howling["events"]])
        self.assertEqual([event for event in howling["events"] if event["type"] == "cards_drawn"][-1]["payload"].get("count"), 2)
        self.assertEqual(len(howling["final_state"]["players"]["P1"]["hand"]), 2)
        kaim = json.loads((output_dir / "kaim_cip_trigger_search.json").read_text(encoding="utf-8"))
        kaim_deck_moves = [
            event for event in kaim["events"]
            if event["type"] == "card_moved" and event["payload"].get("from_zone") == "deck"
        ]
        self.assertEqual(kaim_deck_moves[-1]["payload"].get("category"), "trigger")
        jumpoo = json.loads((output_dir / "jumpoo_bounce_hand_limit.json").read_text(encoding="utf-8"))
        jumpoo_return_moves = [
            event for event in jumpoo["events"]
            if event["type"] == "card_moved" and event["payload"].get("reason") == "return_unit"
        ]
        self.assertEqual([event["payload"].get("to_zone") for event in jumpoo_return_moves], ["hand", "discard_pile"])
        self.assertEqual([event["payload"].get("after_level") for event in jumpoo_return_moves], [1, 1])
        self.assertFalse(jumpoo_return_moves[0]["payload"].get("hand_limit_exceeded"))
        self.assertTrue(jumpoo_return_moves[1]["payload"].get("hand_limit_exceeded"))
        leafia = json.loads((output_dir / "leafia_block_bp_modifier.json").read_text(encoding="utf-8"))
        leafia_event_types = [event["type"] for event in leafia["events"]]
        self.assertEqual(leafia_event_types.count("block_declared"), 4)
        self.assertEqual(leafia_event_types.count("bp_modified"), 4)
        leafia_level_events = [event for event in leafia["events"] if event["type"] == "unit_level_changed"]
        self.assertEqual([event["payload"].get("after_level") for event in leafia_level_events], [2, 3])
        self.assertEqual([event["payload"].get("after_bp") for event in leafia_level_events], [9000, 12000])
        leafia_damage_clear_events = [event for event in leafia["events"] if event["type"] == "unit_damage_cleared"]
        self.assertEqual([event["payload"].get("reason") for event in leafia_damage_clear_events], ["battle_win", "battle_win", "turn_end"])
        self.assertEqual(leafia_damage_clear_events[-1]["payload"].get("before_damage"), 10000)
        self.assertIn("modifier_expired", leafia_event_types)
        leafia_model = build_replay_gui_model(leafia, card_catalog=self.catalog)
        leafia_first_level_frame = leafia_model["frames"][leafia["events"].index(leafia_level_events[0]) + 1]
        self.assertEqual(leafia_first_level_frame["players"][1]["battlefield"][0]["level"], 2)
        self.assertEqual(leafia_first_level_frame["players"][1]["battlefield"][0]["damage"], 3000)
        self.assertEqual(leafia_first_level_frame["players"][1]["battlefield"][0]["current_bp"], 6000)
        third_battle_start = next(
            index
            for index, event in enumerate(leafia["events"])
            if event["type"] == "damage_dealt" and event["payload"].get("after_damage") == 5000
        )
        self.assertEqual(leafia_model["frames"][third_battle_start + 1]["players"][1]["battlefield"][0]["damage"], 5000)
        self.assertEqual(leafia_model["frames"][third_battle_start + 1]["players"][1]["battlefield"][0]["current_bp"], 9000)
        fourth_battle_end = next(
            index
            for index, event in enumerate(leafia["events"])
            if event["type"] == "damage_dealt" and event["payload"].get("after_damage") == 10000
        )
        self.assertEqual(leafia_model["frames"][fourth_battle_end + 1]["players"][1]["battlefield"][0]["damage"], 10000)
        self.assertEqual(leafia_model["frames"][fourth_battle_end + 1]["players"][1]["battlefield"][0]["current_bp"], 6000)
        leafia_turn_end_clear_frame = leafia_model["frames"][leafia["events"].index(leafia_damage_clear_events[-1]) + 1]
        self.assertEqual(leafia_turn_end_clear_frame["players"][1]["battlefield"][0]["damage"], 0)
        self.assertEqual(leafia_turn_end_clear_frame["players"][1]["battlefield"][0]["current_bp"], 8000)
        final_leafia_unit_id = leafia["final_state"]["players"]["P2"]["battlefield"][0]
        self.assertEqual(leafia["final_state"]["units"][final_leafia_unit_id]["level"], 3)
        self.assertEqual(leafia["final_state"]["units"][final_leafia_unit_id]["current_damage"], 0)
        new_armor = json.loads((output_dir / "new_armor_trigger.json").read_text(encoding="utf-8"))
        self.assertIn("trigger_activated", [event["type"] for event in new_armor["events"]])
        oc_consume = json.loads((output_dir / "oc_consume_action.json").read_text(encoding="utf-8"))
        self.assertIn("unit_overclocked", [event["type"] for event in oc_consume["events"]])
        self.assertIn("unit_action_consumed", [event["type"] for event in oc_consume["events"]])
        oc_consume_choices = [event for event in oc_consume["events"] if event["type"] == "choice_requested"]
        self.assertEqual(len(oc_consume_choices[-1]["payload"].get("candidate_unit_ids")), 1)
        raguel = json.loads((output_dir / "raguel_exhausted_damage.json").read_text(encoding="utf-8"))
        raguel_damage_events = [event for event in raguel["events"] if event["type"] == "damage_dealt"]
        self.assertEqual(len(raguel_damage_events), 2)
        damaged_unit_ids = {event["payload"]["target_unit_id"] for event in raguel_damage_events}
        ready_unit_id = raguel["initial_state"]["players"]["P2"]["battlefield"][0]
        self.assertNotIn(ready_unit_id, damaged_unit_ids)
        rairyu = json.loads((output_dir / "rairyu_evolve_damage.json").read_text(encoding="utf-8"))
        self.assertTrue(
            any(event["type"] == "card_moved" and event["payload"].get("reason") == "evolve_source" for event in rairyu["events"])
        )
        self.assertEqual([event for event in rairyu["events"] if event["type"] == "damage_dealt"][-1]["payload"].get("amount"), 7000)
        tailwind = json.loads((output_dir / "tailwind_intercept_cp.json").read_text(encoding="utf-8"))
        self.assertIn("intercept_activated", [event["type"] for event in tailwind["events"]])
        tailwind_cp_events = [event for event in tailwind["events"] if event["type"] == "cp_changed"]
        self.assertEqual(tailwind_cp_events[-1]["payload"].get("amount"), 4)
        self.assertEqual(tailwind["final_state"]["players"]["P1"]["current_cp"], 4)
        lina = json.loads((output_dir / "lina_discard_choice.json").read_text(encoding="utf-8"))
        self.assertIn("choice_selected", [event["type"] for event in lina["events"]])
        initial_lina_deck = lina["initial_state"]["players"]["P1"]["deck"]
        self.assertEqual(len(initial_lina_deck), 5)
        self.assertEqual(lina["initial_state"]["card_instances"][initial_lina_deck[0]]["card_no"], "1-0-033")
        cp_set_events = [event for event in lina["events"] if event["type"] == "cp_set"]
        self.assertEqual(cp_set_events[-1]["payload"].get("after_cp"), 7)
        lina_drive_events = [
            event
            for event in lina["events"]
            if event["type"] == "action_declared" and event["payload"].get("action") == "drive_unit"
        ]
        self.assertEqual([event["source"].get("card_no") for event in lina_drive_events], ["1-0-033", "1-0-031"])
        lina_override_events = [
            event
            for event in lina["events"]
            if event["type"] == "action_declared" and event["payload"].get("action") == "override_card"
        ]
        self.assertEqual([event["source"].get("card_no") for event in lina_override_events], ["1-0-031"] * 3)
        cards_drawn_by_override = [
            event
            for event in lina["events"]
            if event["type"] == "cards_drawn" and event["cause_event_no"] in {override["event_no"] for override in lina_override_events}
        ]
        self.assertEqual([event["payload"].get("count") for event in cards_drawn_by_override], [1, 1, 1])
        final_lina = lina["final_state"]
        final_lina_hand = [
            card_instance_id
            for card_instance_id in final_lina["players"]["P1"]["hand"]
            if final_lina["card_instances"][card_instance_id]["card_no"] == "1-0-031"
        ]
        self.assertEqual(len(final_lina_hand), 1)
        self.assertEqual(final_lina["card_instances"][final_lina_hand[0]]["level"], 2)
        self.assertEqual(
            [final_lina["units"][unit_id]["card_no"] for unit_id in final_lina["players"]["P1"]["battlefield"]],
            ["1-0-033", "1-0-031"],
        )
        viper = json.loads((output_dir / "viper_discard_unit_recover.json").read_text(encoding="utf-8"))
        random_events = [event for event in viper["events"] if event["type"] == "random_resolved"]
        self.assertEqual(random_events[-1]["payload"].get("kind"), "discard_pile_card")
        self.assertEqual(random_events[-1]["payload"].get("category"), "unit")

    def test_replay_gui_render_ignores_scale_set_callback_reentry(self) -> None:
        class FakeCanvas:
            def delete(self, _tag: str) -> None:
                return

        class FakePosition:
            def configure(self, **_kwargs) -> None:
                return

        class FakeScale:
            def __init__(self, gui: ReplayTkGui) -> None:
                self.gui = gui
                self.set_count = 0

            def set(self, value: int) -> None:
                self.set_count += 1
                self.gui.seek(str(value))

        gui = ReplayTkGui.__new__(ReplayTkGui)
        gui.frames = [{"event_index": 0}]
        gui.frame_index = 0
        gui.board_canvas = FakeCanvas()
        gui.position = FakePosition()
        gui._updating_scale = False
        gui._sash_initialized = True
        gui._render_board = lambda _frame: None
        gui._render_log = lambda _frame: None
        gui.scale = FakeScale(gui)

        gui.render()

        self.assertEqual(gui.scale.set_count, 1)

    def test_replay_gui_default_card_width_keeps_tiles_compact(self) -> None:
        self.assertEqual(DEFAULT_REPLAY_CARD_WIDTH, 36)

    def test_replay_gui_uses_zone_specific_tile_dimensions(self) -> None:
        gui = ReplayTkGui.__new__(ReplayTkGui)
        gui.card_width = 36
        gui.card_height = 51

        self.assertEqual(gui._tile_dimensions("battlefield", {"kind": "unit", "exhausted": False}), (72, 102))
        self.assertEqual(gui._tile_dimensions("battlefield", {"kind": "unit", "exhausted": True}), (102, 72))
        self.assertEqual(gui._tile_dimensions("deck", {"kind": "card"}), (18, 26))

    def test_json_line_player_uses_valid_action_response(self) -> None:
        legal_actions = [{"type": "pass"}, {"type": "drive_unit", "card_instance_id": "c0001"}]
        response = encode_action_response(legal_actions[1], request_id="P1:action", player_id="P1")
        transport = MemoryTransport([response])
        player = JsonLinePlayer(transport)

        selected = player.choose_action("P1", legal_actions)

        self.assertEqual(selected, legal_actions[1])
        request = decode_message(transport.written[0])
        self.assertEqual(request["type"], "request_action")
        self.assertEqual(request["request_id"], "P1:action")

    def test_legal_actions_include_display_and_machine_readable_card(self) -> None:
        state = create_game_state(self.catalog)
        state.players["P1"].current_cp = 1
        card = state.create_card_instance("1-0-040", "P1")
        state.players["P1"].hand.add(card.instance_id)

        message = request_action_message(state, "P1", request_id="r1")
        drive_action = next(action for action in message["legal_actions"] if action["type"] == "drive_unit")

        self.assertEqual(drive_action["display"]["card_name"], self.catalog["1-0-040"].name)
        self.assertEqual(drive_action["card"]["card_no"], "1-0-040")
        self.assertIn("フィールドに出す", drive_action["display"]["label"])

    def test_json_line_player_sends_state_update_before_stateful_action_request(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-040", "P1")
        state.players["P1"].hand.add(card.instance_id)
        legal_actions = [{"type": "pass"}]
        response = encode_action_response(legal_actions[0], request_id="P1:action", player_id="P1")
        transport = MemoryTransport([response])
        player = JsonLinePlayer(transport)

        selected = player.choose_action_with_state("P1", legal_actions, state=state)

        self.assertEqual(selected, legal_actions[0])
        self.assertEqual(len(transport.written), 2)
        state_update = decode_message(transport.written[0])
        request = decode_message(transport.written[1])
        self.assertEqual(state_update["type"], "state_update")
        self.assertEqual(request["type"], "request_action")
        self.assertEqual(request["request_context"]["kind"], "turn_action")
        self.assertIn("private_view", request)
        self.assertEqual(request["private_view"]["hand"][0]["card_no"], "1-0-040")

    def test_json_line_player_can_send_event_state_update_without_waiting_response(self) -> None:
        state = create_game_state(self.catalog)
        transport = MemoryTransport()
        player = JsonLinePlayer(transport)

        player.send_state_update(
            "P1",
            state=state,
            request_id="P1:event:1",
            event={"event_no": 1, "type": "match_started"},
        )

        message = decode_message(transport.written[0])
        self.assertEqual(message["type"], "state_update")
        self.assertEqual(message["request_id"], "P1:event:1")
        self.assertEqual(message["event"]["type"], "match_started")

    def test_match_runner_publishes_state_update_per_event(self) -> None:
        class WatchingPassPlayer:
            def __init__(self) -> None:
                self.event_nos: list[int] = []

            def send_state_update(self, player_id, *, state, request_id, event=None) -> None:
                self.event_nos.append(event["event_no"])

            def choose_mulligan(self, player_id) -> bool:
                return False

            def choose_action(self, player_id, legal_actions):
                for action in legal_actions:
                    if action["type"] == "pass":
                        return action
                return legal_actions[0]

        state = create_game_state(self.catalog)
        p1 = WatchingPassPlayer()
        p2 = WatchingPassPlayer()
        runner = MatchRunner(state, players={"P1": p1, "P2": p2})

        runner.run_match(max_turns=1, max_actions_per_turn=1)

        event_nos = [event.event_no for event in state.event_store.events]
        self.assertEqual(p1.event_nos, event_nos)
        self.assertEqual(p2.event_nos, event_nos)

    def test_json_line_player_sends_request_action_context(self) -> None:
        state = create_game_state(self.catalog)
        legal_actions = [{"type": "pass_window", "window": "attack", "cause_event_no": 12}]
        response = encode_action_response(legal_actions[0], request_id="P1:action", player_id="P1")
        transport = MemoryTransport([response])
        player = JsonLinePlayer(transport)

        selected = player.choose_action_with_state(
            "P1",
            legal_actions,
            state=state,
            request_context={"kind": "intercept_window", "cause_event_no": 12, "window": "attack"},
        )

        self.assertEqual(selected, legal_actions[0])
        request = decode_message(transport.written[1])
        self.assertEqual(request["request_context"]["kind"], "intercept_window")
        self.assertEqual(request["request_context"]["window"], "attack")

    def test_json_line_player_uses_valid_mulligan_response(self) -> None:
        response = encode_mulligan_response(True, request_id="P1:mulligan", player_id="P1")
        transport = MemoryTransport([response])
        player = JsonLinePlayer(transport)

        do_mulligan = player.choose_mulligan("P1")

        self.assertTrue(do_mulligan)
        request = decode_message(transport.written[0])
        self.assertEqual(request["type"], "request_mulligan")
        self.assertEqual(request["request_id"], "P1:mulligan")

    def test_json_line_player_sends_stateful_mulligan_request(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-040", "P1")
        state.players["P1"].hand.add(card.instance_id)
        response = encode_mulligan_response(False, request_id="P1:mulligan", player_id="P1")
        transport = MemoryTransport([response])
        player = JsonLinePlayer(transport)

        do_mulligan = player.choose_mulligan_with_state("P1", state=state)

        self.assertFalse(do_mulligan)
        request = decode_message(transport.written[0])
        self.assertEqual(request["type"], "request_mulligan")
        self.assertIn("private_view", request)
        self.assertEqual(request["private_view"]["hand"][0]["card_no"], "1-0-040")

    def test_json_line_player_falls_back_on_timeout_invalid_json_and_illegal_action(self) -> None:
        legal_actions = [{"type": "pass"}]
        cases = [
            None,
            "not json\n",
            encode_action_response({"type": "not_legal"}, request_id="P1:action", player_id="P1"),
        ]

        for response in cases:
            with self.subTest(response=response):
                player = JsonLinePlayer(MemoryTransport([response]))

                selected = player.choose_action("P1", legal_actions)

                self.assertEqual(selected, legal_actions[0])

    def test_match_runner_logs_json_line_player_fallback_reason(self) -> None:
        state = create_game_state(self.catalog)
        player = JsonLinePlayer(MemoryTransport([None]))
        runner = MatchRunner(state, players={"P1": player, "P2": FirstLegalPlayer()})

        runner.run_turn_action("P1")

        fallback_events = [event for event in state.event_store.events if event.type == "player_response_fallback"]
        self.assertEqual(len(fallback_events), 1)
        self.assertEqual(fallback_events[0].payload["reason"], "timeout")

    def test_match_runner_ends_player_error_after_fallback_limit(self) -> None:
        deck1 = parse_decklist({"cards": [{"card_no": "1-0-040", "count": 4}]}, self.catalog)
        deck2 = parse_decklist({"cards": [{"card_no": "1-0-001", "count": 4}]}, self.catalog)
        state = setup_match_state(
            self.catalog,
            {"P1": deck1, "P2": deck2},
            config=MatchSetupConfig(seed=12),
        )
        runner = MatchRunner(
            state,
            players={"P1": JsonLinePlayer(MemoryTransport([None])), "P2": FirstLegalPlayer()},
        )

        result = runner.run_match(max_turns=1, max_actions_per_turn=1, max_fallbacks_per_player=1)

        self.assertEqual(result.reason, "player_error")
        self.assertEqual(result.error_player_id, "P1")
        self.assertEqual(result.winner_player_id, "P2")
        fallback_event = next(event for event in state.event_store.events if event.type == "player_response_fallback")
        self.assertEqual(fallback_event.payload["fallback_count"], 1)
        self.assertEqual(fallback_event.payload["max_fallbacks_per_player"], 1)
        match_ended = state.event_store.events[-1]
        self.assertEqual(match_ended.payload["error_player_id"], "P1")

    def test_match_runner_passes_state_to_json_line_player(self) -> None:
        legal_actions = [{"type": "pass"}]
        response = encode_action_response(legal_actions[0], request_id="P1:action", player_id="P1")
        transport = MemoryTransport([response])
        state = create_game_state(self.catalog)
        runner = MatchRunner(state, players={"P1": JsonLinePlayer(transport), "P2": FirstLegalPlayer()})

        runner.run_turn_action("P1")

        self.assertEqual(decode_message(transport.written[0])["type"], "state_update")
        self.assertEqual(decode_message(transport.written[1])["type"], "request_action")

    def test_json_line_player_uses_same_transport_for_choice_request(self) -> None:
        legal_choices = [{"unit_id": "u0001"}, {"unit_id": "u0002"}]
        response = encode_choice_response(legal_choices[1], request_id="choice-1", player_id="P1")
        transport = MemoryTransport([response])
        player = JsonLinePlayer(transport)

        selected = player.choose_choice(
            "P1",
            request_id="choice-1",
            choice={"type": "unit", "choice_id": "target"},
            legal_choices=legal_choices,
        )

        self.assertEqual(selected, legal_choices[1])
        request = decode_message(transport.written[0])
        self.assertEqual(request["type"], "choice_request")

    def test_json_line_player_maps_decorated_choice_response_to_engine_choice(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P2")
        unit = state.create_unit(card.instance_id)
        state.players["P2"].battlefield.add(unit.unit_id)
        request = choice_request_message(
            request_id="choice-1",
            player_id="P1",
            choice={"type": "unit", "choice_id": "target"},
            legal_choices=[{"unit_id": unit.unit_id}],
            state=state,
        )
        response = encode_choice_response(request["legal_choices"][0], request_id="choice-1", player_id="P1")
        transport = MemoryTransport([response])
        player = JsonLinePlayer(transport)

        selected = player.choose_choice_with_state(
            "P1",
            request_id="choice-1",
            choice={"type": "unit", "choice_id": "target"},
            legal_choices=[{"unit_id": unit.unit_id}],
            state=state,
        )

        self.assertEqual(selected, {"unit_id": unit.unit_id})

    def test_json_line_player_accepts_multi_card_cost_choice_response(self) -> None:
        state = create_game_state(self.catalog)
        first = state.create_card_instance("1-0-040", "P1")
        second = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(first.instance_id)
        state.players["P1"].hand.add(second.instance_id)
        selected_cost = {"card_instance_ids": [first.instance_id, second.instance_id]}
        response = encode_choice_response(selected_cost, request_id="cost-1", player_id="P1")
        transport = MemoryTransport([response])
        player = JsonLinePlayer(transport)

        selected = player.choose_choice_with_state(
            "P1",
            request_id="cost-1",
            choice={"type": "cost_payment", "count": 2},
            legal_choices=[
                {"card_instance_id": first.instance_id},
                {"card_instance_id": second.instance_id},
            ],
            state=state,
        )

        self.assertEqual(selected, selected_cost)

    def test_json_line_player_falls_back_on_invalid_choice_response(self) -> None:
        legal_choices = [{"unit_id": "u0001"}]
        player = JsonLinePlayer(MemoryTransport([encode_choice_response({"unit_id": "bad"}, request_id="c1", player_id="P1")]))

        selected = player.choose_choice(
            "P1",
            request_id="c1",
            choice={"type": "unit", "choice_id": "target"},
            legal_choices=legal_choices,
        )

        self.assertEqual(selected, legal_choices[0])

    def test_sample_child_programs_can_choose_actions_over_json_lines(self) -> None:
        legal_actions = [{"type": "pass"}, {"type": "drive_unit", "card_instance_id": "c0001"}]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC_PATH)
        first_process = subprocess.Popen(
            [sys.executable, "-m", "tojs_reborn.io.sample_player", "--mode", "first"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        pass_process = subprocess.Popen(
            [sys.executable, "-m", "tojs_reborn.io.sample_player", "--mode", "pass"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            first_player = JsonLinePlayer(TextIOJsonLineTransport(first_process.stdout, first_process.stdin))
            pass_player = JsonLinePlayer(TextIOJsonLineTransport(pass_process.stdout, pass_process.stdin))

            self.assertEqual(first_player.choose_action("P1", legal_actions), legal_actions[1])
            self.assertEqual(pass_player.choose_action("P1", legal_actions), legal_actions[0])
            self.assertEqual(
                first_player.choose_choice(
                    "P1",
                    request_id="choice-1",
                    choice={"type": "unit", "choice_id": "target"},
                    legal_choices=[{"unit_id": "u0001"}],
                ),
                {"unit_id": "u0001"},
            )
            self.assertFalse(first_player.choose_mulligan("P1"))
        finally:
            for process in (first_process, pass_process):
                process.kill()
                process.wait(timeout=5)
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

    def test_process_player_starts_sample_player_command(self) -> None:
        legal_actions = [{"type": "pass"}, {"type": "drive_unit", "card_instance_id": "c0001"}]
        process_player = start_process_player(f'"{sys.executable}" -m tojs_reborn.io.sample_player --mode first')
        try:
            self.assertEqual(process_player.choose_action("P1", legal_actions), legal_actions[1])
        finally:
            process_player.close()

    def test_process_player_reports_process_closed(self) -> None:
        legal_actions = [{"type": "pass"}]
        process_player = start_process_player(f'"{sys.executable}" -c "pass"')
        try:
            process_player.process.wait(timeout=5)
            self.assertEqual(process_player.choose_action("P1", legal_actions), legal_actions[0])
            self.assertEqual(process_player.last_fallback_reason, "process_closed")
        finally:
            process_player.close()

    def test_match_cli_runs_external_process_sample_players(self) -> None:
        output_dir = ROOT / "test_output" / "match_cli_process"
        output_dir.mkdir(parents=True, exist_ok=True)
        cards_path = output_dir / "cards.normalized.json"
        deck1_path = output_dir / "deck1.json"
        deck2_path = output_dir / "deck2.json"
        replay_path = output_dir / "replay.json"
        cards_path.write_text(
            json.dumps(
                {
                    "cards": [
                        {
                            "card_no": "1-0-040",
                            "category": "unit",
                            "color": "green",
                            "name": "Happaloid",
                            "cp": 1,
                            "bp_by_level": [1000, 1000, 1000],
                            "abilities": [],
                        },
                        {
                            "card_no": "1-0-001",
                            "category": "unit",
                            "color": "red",
                            "name": "Bloodhound",
                            "cp": 1,
                            "bp_by_level": [1000, 1000, 1000],
                            "abilities": [],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        deck1_path.write_text('{"cards":[{"card_name":"Happaloid","count":4}]}', encoding="utf-8")
        deck2_path.write_text('{"cards":[{"card_name":"Bloodhound","count":4}]}', encoding="utf-8")

        with redirect_stdout(StringIO()):
            exit_code = run_match_cli(
                [
                    "--cards",
                    str(cards_path),
                    "--deck1",
                    str(deck1_path),
                    "--deck2",
                    str(deck2_path),
                    "--p1",
                    f'cmd:"{sys.executable}" -m tojs_reborn.io.sample_player --mode first',
                    "--p2",
                    f'cmd:"{sys.executable}" -m tojs_reborn.io.sample_player --mode pass',
                    "--max-turns",
                    "2",
                    "--replay",
                    str(replay_path),
                    "--verify-replay",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(replay_path.exists())


if __name__ == "__main__":
    unittest.main()
