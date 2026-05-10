import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tojs_reborn.cardpool.excel_loader import load_cardpool_from_xlsx
from tojs_reborn.cardpool.normalizer import normalize_cardpool, write_normalized_outputs


EXCEL_PATH = ROOT / "carddata" / "text-of-joker.cardpool.xlsx"
MAPPING_PATH = ROOT / "carddata" / "manual" / "ability_mapping.json"


class CardpoolNormalizerTest(unittest.TestCase):
    def test_load_cardpool_from_xlsx_reads_initial_cards(self) -> None:
        cards = load_cardpool_from_xlsx(EXCEL_PATH)
        card_by_no = {card.card_no: card for card in cards}

        self.assertGreaterEqual(len(cards), 100)
        self.assertEqual(card_by_no["1-0-040"].name, "ハッパロイド")
        self.assertEqual(card_by_no["1-0-040"].abilities[0].name, "ドロー")

    def test_normalize_cardpool_outputs_happaloid_supported_draw(self) -> None:
        normalized, report = normalize_cardpool(EXCEL_PATH, MAPPING_PATH)
        card_by_no = {card["card_no"]: card for card in normalized["cards"]}
        happaloid = card_by_no["1-0-040"]
        ability = happaloid["abilities"][0]

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["supported_ability_count"], 1)
        self.assertEqual(happaloid["name"], "ハッパロイド")
        self.assertEqual(ability["status"], "supported")
        self.assertEqual(ability["timing"], "SELF_CIP")
        self.assertEqual(
            ability["effect_steps"],
            [{"effect": "draw_cards", "player": "owner", "count": 1}],
        )

    def test_write_normalized_outputs_creates_json_files(self) -> None:
        output_dir = ROOT / "test_output" / "normalizer"

        cards_path, report_path = write_normalized_outputs(EXCEL_PATH, MAPPING_PATH, output_dir)

        self.assertTrue(cards_path.exists())
        self.assertTrue(report_path.exists())


if __name__ == "__main__":
    unittest.main()
