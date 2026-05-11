import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tests.test_engine import build_catalog, draw_window_card
from tojs_reborn.engine.state import create_game_state
from tojs_reborn.io.match_runner import FirstLegalPlayer, MatchRunner, replay_match_record, snapshot_match_initial_state
from tojs_reborn.io.protocol import decode_message, encode_message, public_state_message, request_action_message


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


if __name__ == "__main__":
    unittest.main()
