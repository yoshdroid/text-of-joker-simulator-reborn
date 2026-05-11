import sys
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tests.test_engine import build_catalog, draw_window_card
from tojs_reborn.engine.state import create_game_state
from tojs_reborn.io.match_runner import FirstLegalPlayer, MatchRunner, replay_match_record, snapshot_match_initial_state
from tojs_reborn.io.player_runner import (
    JsonLinePlayer,
    TextIOJsonLineTransport,
    encode_action_response,
    encode_choice_response,
)
from tojs_reborn.io.protocol import (
    action_selected_message,
    choice_request_message,
    choice_selected_message,
    decode_message,
    encode_message,
    public_state_message,
    request_action_message,
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
        self.assertEqual(decoded["legal_actions"], [{"type": "pass"}])

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

    def test_public_state_hides_opponent_private_zones(self) -> None:
        state = create_game_state(self.catalog)
        opponent_card = state.create_card_instance("1-0-001", "P2")
        trigger_card = state.create_card_instance("1-0-065", "P2")
        state.players["P2"].hand.add(opponent_card.instance_id)
        state.players["P2"].trigger_zone.add(trigger_card.instance_id)

        message = public_state_message(state, "P1", request_id="s1")

        self.assertEqual(message["state"]["players"]["P2"]["hand"], {"count": 1})
        self.assertEqual(message["state"]["players"]["P2"]["trigger_zone"]["count"], 1)
        self.assertEqual(
            message["state"]["players"]["P2"]["trigger_zone"]["colors"],
            [self.catalog["1-0-065"].color],
        )

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


if __name__ == "__main__":
    unittest.main()
