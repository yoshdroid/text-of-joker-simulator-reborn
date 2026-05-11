import unittest
import json
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
        self.assertEqual(report["supported_ability_count"], 12)
        self.assertEqual(happaloid["name"], "ハッパロイド")
        self.assertEqual(ability["status"], "supported")
        self.assertEqual(ability["timing"], "SELF_CIP")
        self.assertEqual(
            ability["effect_steps"],
            [{"effect": "draw_cards", "player": "owner", "count": 1}],
        )

    def test_normalize_cardpool_accepts_window_timing_prefixes(self) -> None:
        mapping = {
            "schema_version": 1,
            "cards": {
                "1-0-040": {
                    "card_name": "ハッパロイド",
                    "abilities": [
                        {
                            "ability_key": "1-0-040:test",
                            "ability_name": "ドロー",
                            "source_text": "このユニットがフィールドに出た時、あなたはカードを１枚引く。",
                            "status": "supported",
                            "timing": "TRIGGER_UNIT_ENTERED",
                            "optional": False,
                            "priority": {"band": "trigger", "order": "left_to_right"},
                            "condition": None,
                            "cost_steps": [],
                            "selector": None,
                            "effect_steps": [{"effect": "draw_cards", "player": "owner", "count": 1}],
                        }
                    ],
                }
            },
        }
        mapping_dir = ROOT / "test_output" / "normalizer_mapping_tests"
        mapping_dir.mkdir(parents=True, exist_ok=True)
        mapping_path = mapping_dir / "ability_mapping_window_timing.json"
        mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")

        _normalized, report = normalize_cardpool(EXCEL_PATH, mapping_path)

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["supported_ability_count"], 1)

    def test_normalize_cardpool_warns_when_supported_ability_has_no_source_reference(self) -> None:
        mapping = {
            "schema_version": 1,
            "cards": {
                "1-0-040": {
                    "card_name": "ハッパロイド",
                    "abilities": [
                        {
                            "ability_key": "1-0-040:test",
                            "ability_name": "ドロー",
                            "source_text": "",
                            "status": "supported",
                            "timing": "SELF_CIP",
                            "optional": False,
                            "priority": {"band": "unit", "order": "source_only"},
                            "condition": None,
                            "cost_steps": [],
                            "selector": None,
                            "effect_steps": [{"effect": "draw_cards", "player": "owner", "count": 1}],
                        }
                    ],
                }
            },
        }
        mapping_dir = ROOT / "test_output" / "normalizer_mapping_tests"
        mapping_dir.mkdir(parents=True, exist_ok=True)
        mapping_path = mapping_dir / "ability_mapping_missing_source.json"
        mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")

        _normalized, report = normalize_cardpool(EXCEL_PATH, mapping_path)

        warning_codes = {warning["code"] for warning in report["warnings"]}
        self.assertIn("missing_source_reference", warning_codes)

    def test_write_normalized_outputs_creates_json_files(self) -> None:
        output_dir = ROOT / "test_output" / "normalizer"

        cards_path, report_path = write_normalized_outputs(EXCEL_PATH, MAPPING_PATH, output_dir)

        self.assertTrue(cards_path.exists())
        self.assertTrue(report_path.exists())


if __name__ == "__main__":
    unittest.main()
