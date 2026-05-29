import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tojs_reborn.engine.state import CardDefinition
from tojs_reborn.engine.state import load_card_catalog, load_joker_catalog
from tojs_reborn.io.deck_builder import card_detail_text, decklist_json, filtered_card_nos, regulation_status, run_deck_builder_cli
from tojs_reborn.io.decklist import DecklistError, load_decklist, parse_decklist
from tojs_reborn.io.match_setup import MatchSetupConfig, setup_match_state


class DecklistTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_card_catalog(ROOT / "carddata" / "generated" / "cards.normalized.json")
        self.joker_catalog = load_joker_catalog(ROOT / "carddata" / "generated" / "cards.normalized.json")

    def test_parse_decklist_expands_entries(self) -> None:
        decklist = parse_decklist(
            {
                "deck_name": "sample",
                "joker": "JK-01",
                "cards": [
                    {"card_name": self.catalog["1-0-040"].name, "count": 2},
                    {"card_name": self.catalog["1-0-004"].name, "count": 1},
                ],
            },
            self.catalog,
        )

        self.assertEqual(decklist.deck_name, "sample")
        self.assertEqual(decklist.joker_no, "JK-01")
        self.assertEqual(decklist.expanded_card_nos(), ["1-0-040", "1-0-040", "1-0-004"])

    def test_parse_decklist_defaults_to_crimson_break(self) -> None:
        decklist = parse_decklist({"cards": [{"card_no": "1-0-040", "count": 1}]}, self.catalog)

        self.assertEqual(decklist.joker_no, "JK-01")

    def test_parse_decklist_keeps_card_no_compatibility(self) -> None:
        decklist = parse_decklist({"cards": [{"card_no": "1-0-040", "count": 1}]}, self.catalog)

        self.assertEqual(decklist.expanded_card_nos(), ["1-0-040"])

    def test_parse_decklist_rejects_unknown_card_no(self) -> None:
        with self.assertRaisesRegex(DecklistError, "unknown card_no"):
            parse_decklist({"cards": [{"card_no": "NO-SUCH-CARD", "count": 1}]}, self.catalog)

    def test_parse_decklist_rejects_unknown_card_name(self) -> None:
        with self.assertRaisesRegex(DecklistError, "unknown card_name"):
            parse_decklist({"cards": [{"card_name": "存在しないカード", "count": 1}]}, self.catalog)

    def test_parse_decklist_rejects_ambiguous_card_name(self) -> None:
        catalog = {
            "T-1": CardDefinition("T-1", "unit", "red", "Duplicate", 1, (1000, 1000, 1000), ()),
            "T-2": CardDefinition("T-2", "unit", "blue", "Duplicate", 1, (1000, 1000, 1000), ()),
        }

        with self.assertRaisesRegex(DecklistError, "ambiguous card_name"):
            parse_decklist({"cards": [{"card_name": "Duplicate", "count": 1}]}, catalog)

    def test_parse_decklist_rejects_entry_with_both_card_no_and_card_name(self) -> None:
        with self.assertRaisesRegex(DecklistError, "either card_no or card_name"):
            parse_decklist(
                {"cards": [{"card_no": "1-0-040", "card_name": self.catalog["1-0-040"].name, "count": 1}]},
                self.catalog,
            )

    def test_parse_decklist_rejects_non_positive_count(self) -> None:
        with self.assertRaisesRegex(DecklistError, "count"):
            parse_decklist({"cards": [{"card_name": self.catalog["1-0-040"].name, "count": 0}]}, self.catalog)

    def test_parse_decklist_rejects_invalid_joker_field(self) -> None:
        with self.assertRaisesRegex(DecklistError, "joker"):
            parse_decklist({"joker": "", "cards": [{"card_no": "1-0-040", "count": 1}]}, self.catalog)

    def test_parse_decklist_allows_small_test_deck_by_default(self) -> None:
        decklist = parse_decklist({"cards": [{"card_name": self.catalog["1-0-040"].name, "count": 1}]}, self.catalog)

        self.assertEqual(decklist.expanded_card_nos(), ["1-0-040"])

    def test_parse_decklist_strict_rule_requires_40_cards_and_3_copy_limit(self) -> None:
        with self.assertRaisesRegex(DecklistError, "exactly 40"):
            parse_decklist(
                {"cards": [{"card_no": "1-0-040", "count": 1}]},
                self.catalog,
                strict_deck_rule=True,
            )

        with self.assertRaisesRegex(DecklistError, "at most 3"):
            parse_decklist(
                {"cards": [{"card_no": "1-0-040", "count": 40}]},
                self.catalog,
                strict_deck_rule=True,
            )

    def test_load_decklist_reads_json_file(self) -> None:
        output_dir = ROOT / "test_output" / "decklist"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "deck.json"
        path.write_text(
            '{"deck_name":"file","cards":[{"card_name":"' + self.catalog["1-0-040"].name + '","count":1}]}',
            encoding="utf-8",
        )

        decklist = load_decklist(path, self.catalog)

        self.assertEqual(decklist.deck_name, "file")
        self.assertEqual(decklist.expanded_card_nos(), ["1-0-040"])

    def test_v6_decklists_load_by_card_name(self) -> None:
        deck1 = load_decklist(ROOT / "decklists" / "v6_p1.json", self.catalog)
        deck2 = load_decklist(ROOT / "decklists" / "v6_p2.json", self.catalog)

        self.assertIn("1-0-042", deck1.expanded_card_nos())
        self.assertIn("1-0-041", deck1.expanded_card_nos())
        self.assertIn("1-0-003", deck2.expanded_card_nos())
        self.assertIn("1-0-007", deck2.expanded_card_nos())
        self.assertIn("1-0-010", deck2.expanded_card_nos())

    def test_codex_yellow_deck_uses_yellow_and_colorless_cards(self) -> None:
        deck = load_decklist(ROOT / "decklists" / "codex_yellow_v1_0.json", self.catalog, strict_deck_rule=True)

        card_nos = deck.expanded_card_nos()
        self.assertEqual(deck.deck_name, "codex_yellow_v1_0")
        self.assertEqual(len(card_nos), 40)
        self.assertTrue(all(self.catalog[card_no].color in {"黄", "無"} for card_no in card_nos))

    def test_deck_builder_regulation_status_reports_pass_and_violate(self) -> None:
        valid = ["1-0-040"] * 3 + ["1-0-001"] * 3 + ["1-0-004"] * 3 + ["1-0-005"] * 3
        valid += ["1-0-006"] * 3 + ["1-0-007"] * 3 + ["1-0-010"] * 3 + ["1-0-016"] * 3
        valid += ["1-0-017"] * 3 + ["1-0-018"] * 3 + ["1-0-019"] * 3 + ["1-0-020"] * 3
        valid += ["1-0-021"] * 3 + ["1-0-023"]

        self.assertTrue(regulation_status(valid).passed)
        invalid = ["1-0-040"] * 4
        status = regulation_status(invalid)
        self.assertFalse(status.passed)
        self.assertEqual(status.total_cards, 4)
        self.assertEqual(status.over_limit, {"1-0-040": 4})

    def test_deck_builder_outputs_card_name_decklist_json(self) -> None:
        data = decklist_json("builder_sample", ["1-0-040", "1-0-040", "1-0-001"], self.catalog)

        self.assertEqual(data["deck_name"], "builder_sample")
        self.assertEqual({tuple(sorted(item)) for item in data["cards"]}, {("card_name", "count")})
        parsed = parse_decklist(data, self.catalog)
        self.assertEqual(sorted(parsed.expanded_card_nos()), ["1-0-001", "1-0-040", "1-0-040"])

    def test_deck_builder_filters_and_formats_card_details(self) -> None:
        filtered = filtered_card_nos(
            self.catalog,
            search=self.catalog["1-0-040"].name,
            color=self.catalog["1-0-040"].color,
            category="unit",
        )
        detail = card_detail_text("1-0-040", self.catalog["1-0-040"])

        self.assertIn("1-0-040", filtered)
        self.assertIn(self.catalog["1-0-040"].name, detail)
        self.assertIn("category=unit", detail)

    def test_deck_builder_cli_no_window_loads_cards(self) -> None:
        exit_code = run_deck_builder_cli(["--cards", "carddata/generated/cards.normalized.json", "--no-window"])

        self.assertEqual(exit_code, 0)

    def test_setup_match_state_registers_decks_and_initial_hands(self) -> None:
        deck1 = parse_decklist(
            {
                "deck_name": "p1",
                "cards": [
                    {"card_no": "1-0-040", "count": 2},
                    {"card_no": "1-0-004", "count": 3},
                ],
            },
            self.catalog,
        )
        deck2 = parse_decklist(
            {
                "deck_name": "p2",
                "cards": [
                    {"card_no": "1-0-001", "count": 5},
                ],
            },
            self.catalog,
        )

        state = setup_match_state(
            self.catalog,
            {"P1": deck1, "P2": deck2},
            joker_catalog=self.joker_catalog,
            config=MatchSetupConfig(seed=9, initial_hand_size=4),
        )

        self.assertEqual(state.seed, 9)
        self.assertEqual(state.turn_player_id, "P1")
        self.assertEqual(state.players["P1"].joker_no, "JK-01")
        self.assertEqual(state.players["P1"].life, 7)
        self.assertEqual(state.players["P1"].initial_deck_card_nos, ["1-0-040", "1-0-040", "1-0-004", "1-0-004", "1-0-004"])
        self.assertEqual(len(state.players["P1"].hand.cards), 4)
        self.assertEqual(len(state.players["P1"].deck.cards), 1)
        self.assertEqual(len(state.players["P2"].hand.cards), 4)
        self.assertEqual(len(state.players["P2"].deck.cards), 1)


if __name__ == "__main__":
    unittest.main()
