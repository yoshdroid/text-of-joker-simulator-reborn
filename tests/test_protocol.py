import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tests.test_engine import build_catalog
from tojs_reborn.engine.state import create_game_state
from tojs_reborn.io.match_runner import FirstLegalPlayer, MatchRunner
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
        state.players["P2"].hand.add(opponent_card.instance_id)

        message = public_state_message(state, "P1", request_id="s1")

        self.assertEqual(message["state"]["players"]["P2"]["hand"], {"count": 1})

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


if __name__ == "__main__":
    unittest.main()
