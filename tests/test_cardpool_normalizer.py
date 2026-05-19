import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tojs_reborn.cardpool.excel_loader import load_cardpool_from_xlsx
from tojs_reborn.cardpool.normalizer import normalize_cardpool, write_normalized_outputs


EXCEL_PATH = ROOT / "carddata" / "text-of-joker.cardpool.xlsx"
MAPPING_PATH = ROOT / "carddata" / "manual" / "ability_mapping.json"


def excel_card(card_no: str):
    return next(card for card in load_cardpool_from_xlsx(EXCEL_PATH) if card.card_no == card_no)


class CardpoolNormalizerTest(unittest.TestCase):
    def test_load_cardpool_from_xlsx_reads_initial_cards(self) -> None:
        cards = load_cardpool_from_xlsx(EXCEL_PATH)
        card_by_no = {card.card_no: card for card in cards}

        self.assertGreaterEqual(len(cards), 100)
        self.assertEqual(card_by_no["1-0-040"].name, excel_card("1-0-040").name)
        self.assertEqual(card_by_no["1-0-040"].abilities[0].name, excel_card("1-0-040").abilities[0].name)

    def test_normalize_cardpool_outputs_happaloid_supported_draw(self) -> None:
        normalized, report = normalize_cardpool(EXCEL_PATH, MAPPING_PATH)
        card_by_no = {card["card_no"]: card for card in normalized["cards"]}
        happaloid = card_by_no["1-0-040"]
        ability = happaloid["abilities"][0]

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["supported_ability_count"], 38)
        self.assertEqual(report["status_counts"]["supported"], 38)
        self.assertGreater(report["timing_counts"]["SELF_CIP"], 0)
        self.assertGreater(report["effect_counts"]["draw_cards"], 0)
        self.assertGreater(report["effect_counts"]["discard_from_hand"], 0)
        self.assertEqual(happaloid["name"], excel_card("1-0-040").name)
        self.assertEqual(ability["status"], "supported")
        self.assertEqual(ability["timing"], "SELF_CIP")
        self.assertEqual(
            ability["effect_steps"],
            [{"effect": "draw_cards", "player": "owner", "count": 1}],
        )
        display_stand = card_by_no["1-0-062"]["abilities"][0]
        new_armor = card_by_no["1-0-061"]["abilities"][0]
        surprise_box = card_by_no["1-0-057"]["abilities"][0]
        self.assertEqual(surprise_box["timing"], "TRIGGER_UNIT_ENTERED")
        self.assertEqual(
            surprise_box["effect_steps"],
            [{"effect": "draw_card_by_category", "player": "owner", "category": "trigger", "count": 2}],
        )
        self.assertEqual(display_stand["timing"], "TRIGGER_UNIT_ENTERED")
        self.assertEqual(display_stand["effect_steps"], [{"effect": "draw_cards", "player": "owner", "count": 1}])
        self.assertEqual(new_armor["timing"], "TRIGGER_UNIT_ENTERED")
        self.assertEqual(
            new_armor["effect_steps"],
            [{"effect": "draw_card_by_category", "player": "owner", "category": "intercept", "count": 1}],
        )
        tailwind = card_by_no["1-0-097"]["abilities"][0]
        howling = card_by_no["1-0-099"]["abilities"][0]
        self.assertEqual(tailwind["timing"], "INTERCEPT_UNIT_ENTERED")
        self.assertEqual(tailwind["effect_steps"], [{"effect": "change_cp", "player": "owner", "amount": 4}])
        self.assertEqual(howling["timing"], "INTERCEPT_UNIT_ENTERED")
        self.assertEqual(howling["effect_steps"], [{"effect": "draw_cards", "player": "owner", "count": 2}])
        lina = card_by_no["1-0-031"]["abilities"][0]
        self.assertEqual(lina["timing"], "SELF_OC")
        self.assertEqual(lina["selector"]["type"], "discard_pile_card")
        self.assertEqual(lina["effect_steps"], [{"effect": "move_discard_to_hand", "target": "target"}])

    def test_normalize_cardpool_accepts_window_timing_prefixes(self) -> None:
        card = excel_card("1-0-040")
        mapping = {
            "schema_version": 1,
            "cards": {
                "1-0-040": {
                    "card_name": card.name,
                    "abilities": [
                        {
                            "ability_key": "1-0-040:test",
                            "ability_name": card.abilities[0].name,
                            "source_text": card.abilities[0].text,
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
        mapping_path = _write_mapping("ability_mapping_window_timing.json", mapping)

        _normalized, report = normalize_cardpool(EXCEL_PATH, mapping_path)

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["supported_ability_count"], 1)

    def test_normalize_cardpool_warns_when_supported_ability_has_no_source_reference(self) -> None:
        card = excel_card("1-0-040")
        mapping = {
            "schema_version": 1,
            "cards": {
                "1-0-040": {
                    "card_name": card.name,
                    "abilities": [
                        {
                            "ability_key": "1-0-040:test",
                            "ability_name": card.abilities[0].name,
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
        mapping_path = _write_mapping("ability_mapping_missing_source.json", mapping)

        _normalized, report = normalize_cardpool(EXCEL_PATH, mapping_path)

        warning_codes = {warning["code"] for warning in report["warnings"]}
        self.assertIn("missing_source_reference", warning_codes)

    def test_normalize_cardpool_warns_for_known_but_unsupported_engine_effect(self) -> None:
        card = excel_card("1-0-040")
        mapping = {
            "schema_version": 1,
            "cards": {
                "1-0-040": {
                    "card_name": card.name,
                    "abilities": [
                        {
                            "ability_key": "1-0-040:test",
                            "ability_name": card.abilities[0].name,
                            "source_text": "",
                            "notes": "schema-known effect test",
                            "status": "supported",
                            "timing": "SELF_CIP",
                            "optional": False,
                            "priority": {"band": "unit", "order": "source_only"},
                            "condition": None,
                            "cost_steps": [],
                            "selector": None,
                            "effect_steps": [{"effect": "move_card", "from_zone": "deck", "to_zone": "hand"}],
                        }
                    ],
                }
            },
        }
        mapping_path = _write_mapping("ability_mapping_unsupported_engine_effect.json", mapping)

        _normalized, report = normalize_cardpool(EXCEL_PATH, mapping_path)

        warning_codes = {warning["code"] for warning in report["warnings"]}
        self.assertIn("unsupported_engine_effect", warning_codes)
        self.assertEqual(report["effect_counts"]["move_card"], 1)

    def test_write_normalized_outputs_creates_json_files(self) -> None:
        output_dir = ROOT / "test_output" / "normalizer"

        cards_path, report_path = write_normalized_outputs(EXCEL_PATH, MAPPING_PATH, output_dir)

        self.assertTrue(cards_path.exists())
        self.assertTrue(report_path.exists())


def _write_mapping(filename: str, mapping: dict) -> Path:
    mapping_dir = ROOT / "test_output" / "normalizer_mapping_tests"
    mapping_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = mapping_dir / filename
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return mapping_path


if __name__ == "__main__":
    unittest.main()
