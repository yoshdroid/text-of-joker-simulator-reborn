import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tojs_reborn.cardpool.normalizer import normalize_cardpool
from tojs_reborn.engine.actions import draw_cards, drive_unit
from tojs_reborn.engine.events import EventStore
from tojs_reborn.engine.state import AbilityDefinition, CardDefinition, create_game_state


EXCEL_PATH = ROOT / "carddata" / "text-of-joker.cardpool.xlsx"
MAPPING_PATH = ROOT / "carddata" / "manual" / "ability_mapping.json"


def build_catalog():
    normalized, _report = normalize_cardpool(EXCEL_PATH, MAPPING_PATH)
    catalog = {}
    for item in normalized["cards"]:
        catalog[item["card_no"]] = CardDefinition(
            card_no=item["card_no"],
            category=item["category"],
            color=item["color"],
            name=item["name"],
            cp=item.get("cp"),
            bp_by_level=tuple(item.get("bp_by_level", [])),
            abilities=tuple(
                AbilityDefinition(
                    ability_id=ability["ability_key"],
                    name=ability["ability_name"],
                    status=ability["status"],
                    timing=ability["timing"],
                    optional=ability["optional"],
                    effect_steps=tuple(ability.get("effect_steps", [])),
                    raw=ability,
                )
                for ability in item.get("abilities", [])
            ),
        )
    return catalog


def draw_watcher_card(card_no: str, name: str, timing: str) -> CardDefinition:
    return CardDefinition(
        card_no=card_no,
        category="unit",
        color="test",
        name=name,
        cp=1,
        bp_by_level=(1, 1, 1),
        abilities=(
            AbilityDefinition(
                ability_id=f"{card_no}:a1",
                name=f"{timing} watcher",
                status="supported",
                timing=timing,
                optional=False,
                effect_steps=({"effect": "draw_cards", "player": "owner", "count": 1},),
                raw={},
            ),
        ),
    )


class EngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_catalog()

    def test_event_store_assigns_sequential_event_numbers(self) -> None:
        store = EventStore()

        first = store.append("match_started", round_no=1, turn_no=1, actor_player_id=None)
        second = store.append("turn_started", round_no=1, turn_no=1, actor_player_id="P1")

        self.assertEqual(first.event_no, 1)
        self.assertEqual(second.event_no, 2)

    def test_draw_cards_moves_deck_top_to_hand_and_records_events(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].deck.cards.append(card.instance_id)

        drawn = draw_cards(state, "P1", 1)

        self.assertEqual(drawn, [card.instance_id])
        self.assertEqual(state.players["P1"].deck.cards, [])
        self.assertEqual(state.players["P1"].hand.cards, [card.instance_id])
        self.assertEqual([event.type for event in state.event_store.events], ["card_moved", "cards_drawn"])

    def test_drive_happaloid_resolves_self_cip_draw(self) -> None:
        state = create_game_state(self.catalog)
        happaloid = state.create_card_instance("1-0-040", "P1")
        draw_target = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(happaloid.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)

        unit = drive_unit(state, "P1", happaloid.instance_id)

        self.assertEqual(state.players["P1"].battlefield.units, [unit.unit_id])
        self.assertEqual(state.players["P1"].hand.cards, [draw_target.instance_id])
        self.assertEqual(
            [event.type for event in state.event_store.events],
            [
                "action_declared",
                "card_moved",
                "unit_entered",
                "ability_resolved",
                "card_moved",
                "cards_drawn",
            ],
        )
        ability_event = state.event_store.events[3]
        self.assertEqual(ability_event.source.ability_id, "1-0-040:a1")

    def test_existing_happaloid_self_cip_does_not_trigger_for_new_happaloid(self) -> None:
        state = create_game_state(self.catalog)
        existing = state.create_card_instance("1-0-040", "P1")
        existing_unit = state.create_unit(existing.instance_id)
        state.players["P1"].battlefield.add(existing_unit.unit_id)
        new_happaloid = state.create_card_instance("1-0-040", "P1")
        first_draw = state.create_card_instance("1-0-001", "P1")
        second_draw = state.create_card_instance("1-0-004", "P1")
        state.players["P1"].hand.add(new_happaloid.instance_id)
        state.players["P1"].deck.cards.extend([first_draw.instance_id, second_draw.instance_id])

        drive_unit(state, "P1", new_happaloid.instance_id)

        self.assertEqual(state.players["P1"].hand.cards, [first_draw.instance_id])
        self.assertEqual(state.players["P1"].deck.cards, [second_draw.instance_id])
        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual(len(ability_events), 1)
        self.assertEqual(ability_events[0].source.card_instance_id, new_happaloid.instance_id)

    def test_your_cip_existing_unit_triggers_after_entering_self_cip(self) -> None:
        catalog = dict(self.catalog)
        catalog["T-0-001"] = draw_watcher_card("T-0-001", "Your CIP Watcher", "YOUR_CIP")
        state = create_game_state(catalog)
        watcher_card = state.create_card_instance("T-0-001", "P1")
        watcher_unit = state.create_unit(watcher_card.instance_id)
        state.players["P1"].battlefield.add(watcher_unit.unit_id)
        entering = state.create_card_instance("1-0-040", "P1")
        first_draw = state.create_card_instance("1-0-001", "P1")
        second_draw = state.create_card_instance("1-0-004", "P1")
        state.players["P1"].hand.add(entering.instance_id)
        state.players["P1"].deck.cards.extend([first_draw.instance_id, second_draw.instance_id])

        drive_unit(state, "P1", entering.instance_id)

        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual([event.source.ability_id for event in ability_events], ["1-0-040:a1", "T-0-001:a1"])
        self.assertEqual(state.players["P1"].hand.cards, [first_draw.instance_id, second_draw.instance_id])

    def test_rival_cip_existing_opponent_unit_triggers_but_opponent_happaloid_self_cip_does_not(self) -> None:
        catalog = dict(self.catalog)
        catalog["T-0-002"] = draw_watcher_card("T-0-002", "Rival CIP Watcher", "RIVAL_CIP")
        state = create_game_state(catalog)
        opponent_happaloid = state.create_card_instance("1-0-040", "P2")
        opponent_happaloid_unit = state.create_unit(opponent_happaloid.instance_id)
        state.players["P2"].battlefield.add(opponent_happaloid_unit.unit_id)
        rival_watcher = state.create_card_instance("T-0-002", "P2")
        rival_watcher_unit = state.create_unit(rival_watcher.instance_id)
        state.players["P2"].battlefield.add(rival_watcher_unit.unit_id)
        entering = state.create_card_instance("1-0-001", "P1")
        opponent_draw = state.create_card_instance("1-0-004", "P2")
        state.players["P1"].hand.add(entering.instance_id)
        state.players["P2"].deck.cards.append(opponent_draw.instance_id)

        drive_unit(state, "P1", entering.instance_id)

        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual([event.source.ability_id for event in ability_events], ["T-0-002:a1"])
        self.assertEqual(state.players["P2"].hand.cards, [opponent_draw.instance_id])


if __name__ == "__main__":
    unittest.main()
