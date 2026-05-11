import sys
import os
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tests.test_engine import build_catalog, draw_window_card
from tojs_reborn.engine.state import create_game_state
from tojs_reborn.io.decklist import parse_decklist
from tojs_reborn.io.match_runner import FirstLegalPlayer, MatchRunner, replay_match_record, snapshot_match_initial_state
from tojs_reborn.io.match_cli import run_match_cli
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
from tojs_reborn.io.replay_viewer import format_replay_events, run_replay_viewer_cli
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
        self.assertEqual(legal_choice["target"]["base_bp"], self.catalog["1-0-001"].bp_by_level[0])
        self.assertEqual(legal_choice["target"]["modified_bp"], 1000)
        self.assertEqual(legal_choice["target"]["current_bp"], self.catalog["1-0-001"].bp_by_level[0] + 1000)
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
        self.assertIn("trigger_activated", [event.type for event in state.event_store.events])

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
        state.players["P1"].current_cp = 1
        unit_card = state.create_card_instance("1-0-001", "P1")
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
        state.players["P1"].current_cp = 1
        unit_card = state.create_card_instance("1-0-001", "P1")
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
        deck1 = parse_decklist({"cards": [{"card_no": "1-0-040", "count": 4}]}, self.catalog)
        deck2 = parse_decklist({"cards": [{"card_no": "1-0-001", "count": 4}]}, self.catalog)
        state = setup_match_state(
            self.catalog,
            {"P1": deck1, "P2": deck2},
            config=MatchSetupConfig(seed=3),
        )
        runner = MatchRunner(state, players={"P1": FirstLegalPlayer(), "P2": FirstLegalPlayer()})

        result = runner.run_match(max_turns=2, max_actions_per_turn=10)

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
                    "sample:first",
                    "--p2",
                    "sample:pass",
                    "--seed",
                    "5",
                    "--max-turns",
                    "2",
                    "--replay",
                    str(replay_path),
                    "--verify-replay",
                ]
            )

        self.assertEqual(exit_code, 0)
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        self.assertEqual(replay["match_result"]["reason"], "max_turns")
        self.assertEqual(replay["intents"][0]["type"], "match_started")

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
