import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tojs_reborn.cardpool.normalizer import normalize_cardpool
from tojs_reborn.engine.actions import draw_cards, drive_unit
from tojs_reborn.engine.combat import attack_player, attack_unit, destroy_lethal_units
from tojs_reborn.engine.events import EventStore
from tojs_reborn.engine.state import AbilityDefinition, CardDefinition, create_game_state
from tojs_reborn.engine.turn import end_turn, start_turn


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
        state.players["P1"].current_cp = 1

        unit = drive_unit(state, "P1", happaloid.instance_id)

        self.assertEqual(state.players["P1"].battlefield.units, [unit.unit_id])
        self.assertEqual(state.players["P1"].current_cp, 0)
        self.assertEqual(state.players["P1"].hand.cards, [draw_target.instance_id])
        self.assertEqual(
            [event.type for event in state.event_store.events],
            [
                "action_declared",
                "cp_changed",
                "card_moved",
                "unit_entered",
                "ability_resolved",
                "card_moved",
                "cards_drawn",
            ],
        )
        ability_event = state.event_store.events[4]
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
        state.players["P1"].current_cp = 1

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
        state.players["P1"].current_cp = 1

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
        state.players["P1"].current_cp = 1

        drive_unit(state, "P1", entering.instance_id)

        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual([event.source.ability_id for event in ability_events], ["T-0-002:a1"])
        self.assertEqual(state.players["P2"].hand.cards, [opponent_draw.instance_id])

    def test_start_turn_sets_cp_and_draws_cards(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].deck.cards.append(card.instance_id)

        start_turn(state, "P1", draw_count=1, cp=2)

        self.assertEqual(state.turn_player_id, "P1")
        self.assertEqual(state.players["P1"].current_cp, 2)
        self.assertEqual(state.players["P1"].hand.cards, [card.instance_id])
        self.assertEqual(
            [event.type for event in state.event_store.events],
            ["turn_started", "cp_set", "card_moved", "cards_drawn"],
        )

    def test_start_turn_recovers_exhausted_units_before_cp_and_draw(self) -> None:
        state = create_game_state(self.catalog)
        unit_card = state.create_card_instance("1-0-001", "P1")
        unit = state.create_unit(unit_card.instance_id)
        unit.exhausted = True
        state.players["P1"].battlefield.add(unit.unit_id)

        start_turn(state, "P1", draw_count=0, cp=2)

        self.assertFalse(unit.exhausted)
        self.assertEqual(
            [event.type for event in state.event_store.events],
            ["turn_started", "unit_action_recovered", "cp_set", "cards_drawn"],
        )

    def test_end_turn_switches_player_and_increments_round_after_p2(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"

        end_turn(state, "P1")
        self.assertEqual(state.turn_player_id, "P2")
        self.assertEqual(state.round_no, 1)
        self.assertEqual(state.turn_no, 2)

        end_turn(state, "P2")
        self.assertEqual(state.turn_player_id, "P1")
        self.assertEqual(state.round_no, 2)
        self.assertEqual(state.turn_no, 3)

    def test_attack_player_deals_one_life_damage(self) -> None:
        state = create_game_state(self.catalog)
        attacker_card = state.create_card_instance("1-0-001", "P1")
        attacker = state.create_unit(attacker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)

        attack_player(state, "P1", attacker.unit_id)

        self.assertTrue(attacker.exhausted)
        self.assertEqual(state.players["P2"].life, 6)
        self.assertEqual(
            [event.type for event in state.event_store.events],
            ["action_declared", "unit_attacked", "life_changed"],
        )

    def test_blocked_battle_destroys_both_units_and_moves_to_discard(self) -> None:
        state = create_game_state(self.catalog)
        attacker_card = state.create_card_instance("1-0-001", "P1")
        blocker_card = state.create_card_instance("1-0-001", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        blocker = state.create_unit(blocker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(blocker.unit_id)

        attack_unit(state, "P1", attacker.unit_id, blocker.unit_id)

        self.assertEqual(state.players["P1"].battlefield.units, [])
        self.assertEqual(state.players["P2"].battlefield.units, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [attacker_card.instance_id])
        self.assertEqual(state.players["P2"].discard_pile.cards, [blocker_card.instance_id])
        self.assertNotIn(attacker.unit_id, state.units)
        self.assertNotIn(blocker.unit_id, state.units)
        self.assertEqual(
            [event.type for event in state.event_store.events],
            [
                "action_declared",
                "unit_attacked",
                "battle_started",
                "damage_dealt",
                "damage_dealt",
                "battle_draw",
                "card_moved",
                "unit_destroyed",
                "card_moved",
                "unit_destroyed",
            ],
        )

    def test_drive_unit_requires_cp_and_turn_player(self) -> None:
        state = create_game_state(self.catalog)
        happaloid = state.create_card_instance("1-0-040", "P1")
        state.players["P1"].hand.add(happaloid.instance_id)

        with self.assertRaises(ValueError):
            drive_unit(state, "P1", happaloid.instance_id)

        state.players["P1"].current_cp = 1
        state.turn_player_id = "P2"
        with self.assertRaises(ValueError):
            drive_unit(state, "P1", happaloid.instance_id)

    def test_simultaneous_destroyed_self_pig_resolves_turn_player_first(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        mummy_card = state.create_card_instance("1-0-027", "P1")
        crow_card = state.create_card_instance("1-0-029", "P2")
        mummy = state.create_unit(mummy_card.instance_id)
        crow = state.create_unit(crow_card.instance_id)
        state.players["P1"].battlefield.add(mummy.unit_id)
        state.players["P2"].battlefield.add(crow.unit_id)
        p2_hand = state.create_card_instance("1-0-001", "P2")
        p2_intercept = state.create_card_instance("1-0-065", "P2")
        state.players["P2"].hand.add(p2_hand.instance_id)
        state.players["P2"].deck.cards.append(p2_intercept.instance_id)

        attack_unit(state, "P1", mummy.unit_id, crow.unit_id)

        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual(
            [event.source.ability_id for event in ability_events],
            ["1-0-027:a1", "1-0-029:a1"],
        )
        self.assertIn(p2_hand.instance_id, state.players["P2"].discard_pile.cards)
        self.assertIn(p2_intercept.instance_id, state.players["P2"].hand.cards)
        random_index = next(
            index for index, event in enumerate(state.event_store.events) if event.type == "random_resolved"
        )
        random_event = state.event_store.events[random_index]
        self.assertEqual(random_event.payload["candidate_card_instance_ids"], [p2_hand.instance_id])
        crow_ability_index = next(
            index
            for index, event in enumerate(state.event_store.events)
            if event.type == "ability_resolved" and event.source.ability_id == "1-0-029:a1"
        )
        self.assertLess(random_index, crow_ability_index)

    def test_same_player_simultaneous_destroyed_self_pig_resolves_left_to_right(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        mummy_card = state.create_card_instance("1-0-027", "P1")
        crow_card = state.create_card_instance("1-0-029", "P1")
        mummy = state.create_unit(mummy_card.instance_id)
        crow = state.create_unit(crow_card.instance_id)
        state.players["P1"].battlefield.units.extend([mummy.unit_id, crow.unit_id])
        mummy.current_damage = 1
        crow.current_damage = 1
        p2_hand = state.create_card_instance("1-0-001", "P2")
        p1_intercept = state.create_card_instance("1-0-065", "P1")
        state.players["P2"].hand.add(p2_hand.instance_id)
        state.players["P1"].deck.cards.append(p1_intercept.instance_id)

        destroy_lethal_units(state, [crow, mummy], cause_event_no=0)

        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual(
            [event.source.ability_id for event in ability_events],
            ["1-0-027:a1", "1-0-029:a1"],
        )

    def test_battle_won_event_when_attacker_survives_and_blocker_destroyed(self) -> None:
        catalog = dict(self.catalog)
        catalog["T-9-001"] = CardDefinition(
            card_no="T-9-001",
            category="unit",
            color="test",
            name="Big Unit",
            cp=1,
            bp_by_level=(5, 5, 5),
            abilities=(),
        )
        state = create_game_state(catalog)
        attacker_card = state.create_card_instance("T-9-001", "P1")
        blocker_card = state.create_card_instance("1-0-001", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        blocker = state.create_unit(blocker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(blocker.unit_id)

        attack_unit(state, "P1", attacker.unit_id, blocker.unit_id)

        self.assertIn("battle_won", [event.type for event in state.event_store.events])
        self.assertIn(attacker.unit_id, state.units)
        self.assertNotIn(blocker.unit_id, state.units)


if __name__ == "__main__":
    unittest.main()
