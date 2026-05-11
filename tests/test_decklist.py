import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tests.test_engine import build_catalog
from tojs_reborn.io.decklist import DecklistError, load_decklist, parse_decklist


class DecklistTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_catalog()

    def test_parse_decklist_expands_entries(self) -> None:
        decklist = parse_decklist(
            {
                "deck_name": "sample",
                "cards": [
                    {"card_no": "1-0-040", "count": 2},
                    {"card_no": "1-0-004", "count": 1},
                ],
            },
            self.catalog,
        )

        self.assertEqual(decklist.deck_name, "sample")
        self.assertEqual(decklist.expanded_card_nos(), ["1-0-040", "1-0-040", "1-0-004"])

    def test_parse_decklist_rejects_unknown_card_no(self) -> None:
        with self.assertRaisesRegex(DecklistError, "unknown card_no"):
            parse_decklist({"cards": [{"card_no": "NO-SUCH-CARD", "count": 1}]}, self.catalog)

    def test_parse_decklist_rejects_non_positive_count(self) -> None:
        with self.assertRaisesRegex(DecklistError, "count"):
            parse_decklist({"cards": [{"card_no": "1-0-040", "count": 0}]}, self.catalog)

    def test_parse_decklist_allows_small_test_deck_by_default(self) -> None:
        decklist = parse_decklist({"cards": [{"card_no": "1-0-040", "count": 1}]}, self.catalog)

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
        path.write_text('{"deck_name":"file","cards":[{"card_no":"1-0-040","count":1}]}', encoding="utf-8")

        decklist = load_decklist(path, self.catalog)

        self.assertEqual(decklist.deck_name, "file")
        self.assertEqual(decklist.expanded_card_nos(), ["1-0-040"])


if __name__ == "__main__":
    unittest.main()
