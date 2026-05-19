import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tojs_reborn.cardpool.normalizer import normalize_cardpool
from tojs_reborn.engine.actions import EFFECT_FIZZLED_REASONS, draw_cards, drive_unit, overclock_unit, override_card, set_trigger
from tojs_reborn.engine.combat import attack_player, attack_unit, declare_attack, destroy_lethal_units
from tojs_reborn.engine.events import EventSource, EventStore
from tojs_reborn.engine.integrity import assert_game_state_integrity
from tojs_reborn.engine.legal_actions import list_block_actions, list_legal_actions
from tojs_reborn.engine.replay import (
    build_replay_record,
    replay_record,
    snapshot_initial_state,
    verify_replay_record,
)
from tojs_reborn.engine.rules import MAX_HAND_SIZE, MAX_TRIGGER_ZONE_CARDS, get_unit_base_bp, get_unit_bp, ruleset_to_dict, turn_cp_for
from tojs_reborn.engine.state import AbilityDefinition, CardDefinition, create_game_state
from tojs_reborn.engine.turn import end_turn, start_turn
from tojs_reborn.engine.windows import list_trigger_intercept_window, process_intercept_window, process_trigger_window


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


def draw_window_card(card_no: str, category: str, timing: str) -> CardDefinition:
    return CardDefinition(
        card_no=card_no,
        category=category,
        color="test",
        name=f"{category} draw",
        cp=None,
        bp_by_level=(),
        abilities=(
            AbilityDefinition(
                ability_id=f"{card_no}:a1",
                name=f"{timing} draw",
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

    def _add_battlefield_unit(self, state, player_id: str, card_no: str):
        card = state.create_card_instance(card_no, player_id)
        unit = state.create_unit(card.instance_id)
        state.players[player_id].battlefield.add(unit.unit_id)
        return card, unit

    def test_event_store_assigns_sequential_event_numbers(self) -> None:
        store = EventStore()

        first = store.append("match_started", round_no=1, turn_no=1, actor_player_id=None)
        second = store.append("turn_started", round_no=1, turn_no=1, actor_player_id="P1")

        self.assertEqual(first.event_no, 1)
        self.assertEqual(second.event_no, 2)

    def test_unit_printed_bp_is_scaled_to_game_bp(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P1")
        unit = state.create_unit(card.instance_id)

        self.assertEqual(self.catalog["1-0-001"].bp_by_level[0], 3)
        self.assertEqual(get_unit_base_bp(state, unit), 3000)
        self.assertEqual(get_unit_bp(state, unit), 3000)

    def test_draw_cards_moves_deck_top_to_hand_and_records_events(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].deck.cards.append(card.instance_id)

        drawn = draw_cards(state, "P1", 1)

        self.assertEqual(drawn, [card.instance_id])
        self.assertEqual(state.players["P1"].deck.cards, [])
        self.assertEqual(state.players["P1"].hand.cards, [card.instance_id])
        self.assertEqual([event.type for event in state.event_store.events], ["card_moved", "cards_drawn"])

    def test_draw_cards_refreshes_empty_deck_from_initial_deck_registration(self) -> None:
        state = create_game_state(self.catalog, seed=1)
        old_discard = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].discard_pile.add(old_discard.instance_id)
        state.players["P1"].initial_deck_card_nos = ["1-0-001", "1-0-004"]

        drawn = draw_cards(state, "P1", 1)

        self.assertEqual(len(drawn), 1)
        self.assertEqual(state.players["P1"].discard_pile.cards, [])
        self.assertEqual(len(state.players["P1"].deck.cards), 1)
        event_types = [event.type for event in state.event_store.events]
        self.assertEqual(event_types[0], "deck_refreshed")
        self.assertEqual(event_types[-1], "cards_drawn")
        self.assertEqual(state.event_store.events[0].payload["from_discard_card_instance_ids"], [old_discard.instance_id])

    def test_draw_card_by_category_does_not_refresh_empty_deck(self) -> None:
        state = create_game_state(self.catalog, seed=1)
        state.players["P1"].initial_deck_card_nos = ["1-0-065"]
        crow_card = state.create_card_instance("1-0-029", "P1")
        crow = state.create_unit(crow_card.instance_id)
        state.players["P1"].battlefield.add(crow.unit_id)
        state.turn_player_id = "P1"
        crow.current_damage = get_unit_bp(state, crow)

        destroy_lethal_units(state, [crow], cause_event_no=0)

        cards_drawn = [event for event in state.event_store.events if event.type == "cards_drawn"][-1]
        self.assertEqual(cards_drawn.payload["count"], 0)
        self.assertNotIn("deck_refreshed", [event.type for event in state.event_store.events])
        self.assertEqual(state.players["P1"].deck.cards, [])

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

    def test_yashionotokuri_cip_targets_only_exhausted_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        ready_card = state.create_card_instance("1-0-040", "P2")
        exhausted_card = state.create_card_instance("1-0-048", "P2")
        ready_unit = state.create_unit(ready_card.instance_id)
        exhausted_unit = state.create_unit(exhausted_card.instance_id)
        exhausted_unit.exhausted = True
        state.players["P2"].battlefield.add(ready_unit.unit_id)
        state.players["P2"].battlefield.add(exhausted_unit.unit_id)
        entering_card = state.create_card_instance("1-0-018", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", entering_card.instance_id)

        damage_events = [event for event in state.event_store.events if event.type == "damage_dealt"]
        self.assertEqual(len(damage_events), 1)
        self.assertEqual(damage_events[0].payload["target_unit_id"], exhausted_unit.unit_id)
        choice_requests = [event for event in state.event_store.events if event.type == "choice_requested"]
        self.assertEqual(choice_requests[-1].payload["candidate_unit_ids"], [exhausted_unit.unit_id])

    def test_yashionotokuri_cip_resolves_and_fizzles_when_no_exhausted_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        ready_card = state.create_card_instance("1-0-040", "P2")
        ready_unit = state.create_unit(ready_card.instance_id)
        state.players["P2"].battlefield.add(ready_unit.unit_id)
        entering_card = state.create_card_instance("1-0-018", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", entering_card.instance_id)

        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("damage_dealt", [event.type for event in state.event_store.events])

    def test_rairyu_cip_deals_7000_damage_to_exhausted_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        ready_card = state.create_card_instance("1-0-040", "P2")
        exhausted_card = state.create_card_instance("1-0-048", "P2")
        ready_unit = state.create_unit(ready_card.instance_id)
        exhausted_unit = state.create_unit(exhausted_card.instance_id)
        exhausted_unit.exhausted = True
        state.players["P2"].battlefield.add(ready_unit.unit_id)
        state.players["P2"].battlefield.add(exhausted_unit.unit_id)
        entering_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        rairyu = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertIn(rairyu.unit_id, state.players["P1"].battlefield.units)
        self.assertNotIn(base_unit.unit_id, state.units)
        self.assertIn(exhausted_card.instance_id, state.players["P2"].discard_pile.cards)
        self.assertIn(ready_unit.unit_id, state.units)
        self.assertNotIn(exhausted_unit.unit_id, state.units)
        damage_events = [event for event in state.event_store.events if event.type == "damage_dealt"]
        self.assertEqual(damage_events[-1].payload["amount"], 7000)
        self.assertEqual(damage_events[-1].payload["target_unit_id"], exhausted_unit.unit_id)
        choice_requests = [event for event in state.event_store.events if event.type == "choice_requested"]
        self.assertEqual(choice_requests[-1].payload["candidate_unit_ids"], [exhausted_unit.unit_id])

    def test_rairyu_cip_fizzles_without_exhausted_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        ready_card = state.create_card_instance("1-0-040", "P2")
        ready_unit = state.create_unit(ready_card.instance_id)
        state.players["P2"].battlefield.add(ready_unit.unit_id)
        entering_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("damage_dealt", [event.type for event in state.event_store.events])

    def test_lilim_cip_deals_4000_damage_to_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-004")
        rival_card, rival_unit = self._add_battlefield_unit(state, "P2", "1-0-040")
        entering_card = state.create_card_instance("1-0-012", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        damage_events = [event for event in state.event_store.events if event.type == "damage_dealt"]
        self.assertEqual(damage_events[-1].payload["target_unit_id"], rival_unit.unit_id)
        self.assertEqual(damage_events[-1].payload["amount"], 4000)
        self.assertIn(rival_card.instance_id, state.players["P2"].discard_pile.cards)

    def test_lilim_attack_destroys_random_rival_trigger_zone_card(self) -> None:
        state = create_game_state(self.catalog)
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-004")
        entering_card = state.create_card_instance("1-0-012", "P1")
        rival_trigger = state.create_card_instance("1-0-061", "P2")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P2"].trigger_zone.add(rival_trigger.instance_id)
        state.players["P1"].current_cp = 10
        lilim = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        declare_attack(state, "P1", lilim.unit_id)

        self.assertEqual(state.players["P2"].trigger_zone.cards, [])
        self.assertIn(rival_trigger.instance_id, state.players["P2"].discard_pile.cards)
        self.assertIn("random_resolved", [event.type for event in state.event_store.events])

    def test_hades_cip_destroys_all_level_two_or_higher_rival_units(self) -> None:
        state = create_game_state(self.catalog)
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-027")
        level1_card, level1_unit = self._add_battlefield_unit(state, "P2", "1-0-001")
        level2_card, level2_unit = self._add_battlefield_unit(state, "P2", "1-0-004")
        level3_card, level3_unit = self._add_battlefield_unit(state, "P2", "1-0-007")
        level2_unit.level = 2
        level3_unit.level = 3
        entering_card = state.create_card_instance("1-0-039", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertIn(level1_unit.unit_id, state.units)
        self.assertIn(level1_unit.unit_id, state.players["P2"].battlefield.units)
        self.assertNotIn(level2_unit.unit_id, state.units)
        self.assertNotIn(level3_unit.unit_id, state.units)
        self.assertIn(level2_card.instance_id, state.players["P2"].discard_pile.cards)
        self.assertIn(level3_card.instance_id, state.players["P2"].discard_pile.cards)
        destroyed_events = [event for event in state.event_store.events if event.type == "unit_destroyed"]
        self.assertEqual([event.source.unit_id for event in destroyed_events], [level2_unit.unit_id, level3_unit.unit_id])

    def test_evolve_drive_requires_same_color_battlefield_target(self) -> None:
        state = create_game_state(self.catalog)
        _green_card, green_unit = self._add_battlefield_unit(state, "P1", "1-0-040")
        entering_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        with self.assertRaisesRegex(ValueError, "requires target unit"):
            drive_unit(state, "P1", entering_card.instance_id)
        with self.assertRaisesRegex(ValueError, "same color"):
            drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=green_unit.unit_id)

    def test_evolve_drive_discards_source_and_inherits_action_state(self) -> None:
        state = create_game_state(self.catalog)
        base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        base_unit.exhausted = True
        entering_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        rairyu = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertNotIn(base_unit.unit_id, state.units)
        self.assertNotIn(base_unit.unit_id, state.players["P1"].battlefield.units)
        self.assertIn(base_card.instance_id, state.players["P1"].discard_pile.cards)
        self.assertIn(rairyu.unit_id, state.players["P1"].battlefield.units)
        self.assertTrue(rairyu.exhausted)
        self.assertEqual(rairyu.card_no, "1-0-024")
        self.assertNotIn("unit_destroyed", [event.type for event in state.event_store.events])
        source_moves = [
            event
            for event in state.event_store.events
            if event.type == "card_moved" and event.payload.get("reason") == "evolve_source"
        ]
        self.assertEqual(source_moves[-1].source.card_instance_id, base_card.instance_id)
        evolved_move = [
            event
            for event in state.event_store.events
            if event.type == "card_moved" and event.payload.get("to_zone") == "battlefield"
        ][-1]
        self.assertTrue(evolved_move.payload["exhausted"])
        self.assertIsNone(evolved_move.payload["attack_restricted_turn_no"])

    def test_evolve_drive_places_new_unit_at_source_position(self) -> None:
        state = create_game_state(self.catalog)
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        _second_card, second_unit = self._add_battlefield_unit(state, "P1", "1-0-040")
        entering_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        evolved = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertEqual(state.players["P1"].battlefield.units, [evolved.unit_id, second_unit.unit_id])
        move_events = [
            event
            for event in state.event_store.events
            if event.type == "card_moved" and event.payload.get("to_zone") == "battlefield"
        ]
        self.assertEqual(move_events[-1].payload.get("battlefield_index"), 0)

    def test_level3_evolve_drive_recovers_inherited_exhausted_action_by_overclock(self) -> None:
        state = create_game_state(self.catalog)
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        base_unit.exhausted = True
        entering_card = state.create_card_instance("1-0-024", "P1", level=3)
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        rairyu = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertFalse(rairyu.exhausted)
        self.assertIn("unit_overclocked", [event.type for event in state.event_store.events])
        self.assertIn("unit_action_recovered", [event.type for event in state.event_store.events])

    def test_normal_unit_cannot_attack_on_the_turn_it_entered(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        state.turn_player_id = "P1"
        entering_card = state.create_card_instance("1-0-040", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        happaloid = drive_unit(state, "P1", entering_card.instance_id)
        actions = list_legal_actions(state, "P1")

        self.assertEqual(happaloid.attack_restricted_turn_no, state.turn_no)
        self.assertNotIn(
            happaloid.unit_id,
            [action.get("attacker_unit_id") for action in actions if action["type"] == "attack"],
        )
        with self.assertRaisesRegex(ValueError, "cannot attack on the turn it entered"):
            declare_attack(state, "P1", happaloid.unit_id)

    def test_evolve_unit_can_attack_on_the_turn_it_entered(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        state.turn_player_id = "P1"
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        entering_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        rairyu = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)
        actions = list_legal_actions(state, "P1")

        self.assertIsNone(rairyu.attack_restricted_turn_no)
        self.assertIn(
            rairyu.unit_id,
            [action.get("attacker_unit_id") for action in actions if action["type"] == "attack"],
        )
        declare_attack(state, "P1", rairyu.unit_id)
        self.assertTrue(rairyu.exhausted)

    def test_battlefield_unit_limit_blocks_normal_unit_drive_at_five_units(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        state.players["P1"].current_cp = 10
        for _index in range(5):
            self._add_battlefield_unit(state, "P1", "1-0-040")
        entering_card = state.create_card_instance("1-0-040", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)

        actions = [
            action
            for action in list_legal_actions(state, "P1")
            if action["type"] == "drive_unit" and action["card_instance_id"] == entering_card.instance_id
        ]

        self.assertEqual(actions, [])
        with self.assertRaisesRegex(ValueError, "battlefield unit limit"):
            drive_unit(state, "P1", entering_card.instance_id)
        self.assertEqual(len(state.players["P1"].battlefield.units), 5)
        self.assertIn(entering_card.instance_id, state.players["P1"].hand.cards)

    def test_battlefield_unit_limit_allows_evolve_drive_at_five_units(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        state.players["P1"].current_cp = 10
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        for _index in range(4):
            self._add_battlefield_unit(state, "P1", "1-0-040")
        entering_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)

        actions = [
            action
            for action in list_legal_actions(state, "P1")
            if action["type"] == "drive_unit" and action["card_instance_id"] == entering_card.instance_id
        ]
        rairyu = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertEqual([action["evolve_target_unit_id"] for action in actions], [base_unit.unit_id])
        self.assertEqual(len(state.players["P1"].battlefield.units), 5)
        self.assertIn(rairyu.unit_id, state.players["P1"].battlefield.units)
        self.assertNotIn(base_unit.unit_id, state.players["P1"].battlefield.units)

    def test_kitsune_attack_consumes_ready_rival_unit_action(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        attacker_card = state.create_card_instance("1-0-025", "P1")
        ready_card = state.create_card_instance("1-0-001", "P2")
        exhausted_card = state.create_card_instance("1-0-004", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        ready = state.create_unit(ready_card.instance_id)
        exhausted = state.create_unit(exhausted_card.instance_id)
        exhausted.exhausted = True
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(exhausted.unit_id)
        state.players["P2"].battlefield.add(ready.unit_id)

        declare_attack(state, "P1", attacker.unit_id)

        self.assertTrue(attacker.exhausted)
        self.assertTrue(ready.exhausted)
        self.assertTrue(exhausted.exhausted)
        self.assertIn("unit_action_consumed", [event.type for event in state.event_store.events])
        choice_requests = [event for event in state.event_store.events if event.type == "choice_requested"]
        self.assertEqual(choice_requests[-1].payload["candidate_unit_ids"], [ready.unit_id])

    def test_kitsune_attack_fizzles_without_ready_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        attacker_card = state.create_card_instance("1-0-025", "P1")
        exhausted_card = state.create_card_instance("1-0-004", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        exhausted = state.create_unit(exhausted_card.instance_id)
        exhausted.exhausted = True
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(exhausted.unit_id)

        declare_attack(state, "P1", attacker.unit_id)

        self.assertTrue(attacker.exhausted)
        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("unit_action_consumed", [event.type for event in state.event_store.events])

    def test_sword_fighter_attack_modifies_own_bp_until_turn_end(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        attacker_card = state.create_card_instance("1-0-002", "P1")
        attacker = state.create_unit(attacker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        before_bp = get_unit_bp(state, attacker)

        declare_attack(state, "P1", attacker.unit_id)

        self.assertEqual(get_unit_bp(state, attacker), before_bp + 2000)
        self.assertIn("bp_modified", [event.type for event in state.event_store.events])
        end_turn(state, "P1")
        self.assertEqual(get_unit_bp(state, attacker), before_bp)
        self.assertIn("modifier_expired", [event.type for event in state.event_store.events])

    def test_bishamon_cip_destroys_all_other_units_turn_player_first(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        p1_first_card = state.create_card_instance("1-0-028", "P1")
        p1_second_card = state.create_card_instance("1-0-027", "P1")
        p2_card = state.create_card_instance("1-0-029", "P2")
        p1_first = state.create_unit(p1_first_card.instance_id)
        p1_second = state.create_unit(p1_second_card.instance_id)
        p2_unit = state.create_unit(p2_card.instance_id)
        state.players["P1"].battlefield.add(p1_first.unit_id)
        state.players["P1"].battlefield.add(p1_second.unit_id)
        state.players["P2"].battlefield.add(p2_unit.unit_id)
        entering_card = state.create_card_instance("1-0-026", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        bishamon = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertIn(bishamon.unit_id, state.units)
        self.assertNotIn(p1_first.unit_id, state.units)
        self.assertNotIn(p1_second.unit_id, state.units)
        self.assertNotIn(p2_unit.unit_id, state.units)
        destroyed_events = [event for event in state.event_store.events if event.type == "unit_destroyed"]
        self.assertEqual(
            [event.source.unit_id for event in destroyed_events],
            [p1_first.unit_id, p1_second.unit_id, p2_unit.unit_id],
        )
        self.assertEqual(
            [event.payload["reason"] for event in destroyed_events],
            ["effect", "effect", "effect"],
        )

    def test_bishamon_cip_fizzles_when_no_other_units(self) -> None:
        state = create_game_state(self.catalog)
        _base_card, base_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        entering_card = state.create_card_instance("1-0-026", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        bishamon = drive_unit(state, "P1", entering_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertIn(bishamon.unit_id, state.units)
        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("unit_destroyed", [event.type for event in state.event_store.events])

    def test_raguel_cip_deals_damage_to_all_exhausted_rival_units_only(self) -> None:
        state = create_game_state(self.catalog)
        ready_card = state.create_card_instance("1-0-048", "P2")
        first_exhausted_card = state.create_card_instance("1-0-048", "P2")
        second_exhausted_card = state.create_card_instance("1-0-048", "P2")
        ready_unit = state.create_unit(ready_card.instance_id)
        first_exhausted = state.create_unit(first_exhausted_card.instance_id)
        second_exhausted = state.create_unit(second_exhausted_card.instance_id)
        first_exhausted.exhausted = True
        second_exhausted.exhausted = True
        state.players["P2"].battlefield.add(ready_unit.unit_id)
        state.players["P2"].battlefield.add(first_exhausted.unit_id)
        state.players["P2"].battlefield.add(second_exhausted.unit_id)
        entering_card = state.create_card_instance("1-0-023", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", entering_card.instance_id)

        damage_events = [event for event in state.event_store.events if event.type == "damage_dealt"]
        self.assertEqual(
            [event.payload["target_unit_id"] for event in damage_events],
            [first_exhausted.unit_id, second_exhausted.unit_id],
        )
        self.assertEqual(ready_unit.current_damage, 0)

    def test_raguel_cip_resolves_and_fizzles_when_no_exhausted_rival_units(self) -> None:
        state = create_game_state(self.catalog)
        ready_card = state.create_card_instance("1-0-048", "P2")
        ready_unit = state.create_unit(ready_card.instance_id)
        state.players["P2"].battlefield.add(ready_unit.unit_id)
        entering_card = state.create_card_instance("1-0-023", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", entering_card.instance_id)

        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("damage_dealt", [event.type for event in state.event_store.events])

    def test_kaim_cip_draws_trigger_card_from_deck_without_reordering_other_cards(self) -> None:
        state = create_game_state(self.catalog)
        kaim = state.create_card_instance("1-0-020", "P1")
        unit_card = state.create_card_instance("1-0-001", "P1")
        trigger_card = state.create_card_instance("1-0-061", "P1")
        intercept_card = state.create_card_instance("1-0-097", "P1")
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(kaim.instance_id)
        state.players["P1"].deck.cards.extend([unit_card.instance_id, trigger_card.instance_id, intercept_card.instance_id])

        drive_unit(state, "P1", kaim.instance_id)

        self.assertEqual(state.players["P1"].hand.cards, [trigger_card.instance_id])
        self.assertEqual(state.players["P1"].deck.cards, [unit_card.instance_id, intercept_card.instance_id])
        move_events = [
            event for event in state.event_store.events
            if event.type == "card_moved" and event.payload.get("from_zone") == "deck"
        ]
        self.assertEqual(move_events[-1].payload["category"], "trigger")

    def test_kaim_cip_draws_zero_when_no_trigger_card_in_deck(self) -> None:
        state = create_game_state(self.catalog)
        kaim = state.create_card_instance("1-0-020", "P1")
        unit_card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(kaim.instance_id)
        state.players["P1"].deck.cards.append(unit_card.instance_id)

        drive_unit(state, "P1", kaim.instance_id)

        self.assertEqual(state.players["P1"].hand.cards, [])
        self.assertEqual(state.players["P1"].deck.cards, [unit_card.instance_id])
        draw_events = [event for event in state.event_store.events if event.type == "cards_drawn"]
        self.assertEqual(draw_events[-1].payload["count"], 0)

    def test_jumpoo_cip_returns_rival_unit_to_hand_and_resets_level_to_one(self) -> None:
        state = create_game_state(self.catalog)
        jumpoo = state.create_card_instance("1-0-019", "P1")
        target_card = state.create_card_instance("1-0-001", "P2", level=2)
        target = state.create_unit(target_card.instance_id)
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(jumpoo.instance_id)
        state.players["P2"].battlefield.add(target.unit_id)

        drive_unit(state, "P1", jumpoo.instance_id)

        self.assertNotIn(target.unit_id, state.units)
        self.assertEqual(state.players["P2"].battlefield.units, [])
        self.assertEqual(state.players["P2"].hand.cards, [target_card.instance_id])
        self.assertEqual(state.card_instances[target_card.instance_id].level, 1)
        self.assertIn("unit_returned_to_hand", [event.type for event in state.event_store.events])

    def test_jumpoo_cip_sends_returned_unit_to_discard_when_rival_hand_is_full(self) -> None:
        state = create_game_state(self.catalog)
        jumpoo = state.create_card_instance("1-0-019", "P1")
        target_card = state.create_card_instance("1-0-001", "P2", level=3)
        target = state.create_unit(target_card.instance_id)
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(jumpoo.instance_id)
        state.players["P2"].battlefield.add(target.unit_id)
        for _ in range(7):
            hand_card = state.create_card_instance("1-0-004", "P2")
            state.players["P2"].hand.add(hand_card.instance_id)

        drive_unit(state, "P1", jumpoo.instance_id)

        self.assertNotIn(target.unit_id, state.units)
        self.assertNotIn(target_card.instance_id, state.players["P2"].hand.cards)
        self.assertIn(target_card.instance_id, state.players["P2"].discard_pile.cards)
        self.assertEqual(state.card_instances[target_card.instance_id].level, 1)
        move_events = [
            event for event in state.event_store.events
            if event.type == "card_moved" and event.payload.get("reason") == "return_unit"
        ]
        self.assertEqual(move_events[-1].payload["to_zone"], "discard_pile")
        self.assertTrue(move_events[-1].payload["hand_limit_exceeded"])

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

    def test_turn_draw_respects_hand_limit_across_repeated_turns(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        for _ in range(3):
            state.players["P1"].hand.add(state.create_card_instance("1-0-001", "P1").instance_id)
        for _ in range(2):
            state.players["P2"].hand.add(state.create_card_instance("1-0-001", "P2").instance_id)
        for _ in range(12):
            state.players["P1"].deck.cards.append(state.create_card_instance("1-0-040", "P1").instance_id)
            state.players["P2"].deck.cards.append(state.create_card_instance("1-0-040", "P2").instance_id)

        start_turn(state, "P1", draw_count=0, cp=2)
        self.assertEqual(len(state.players["P1"].hand.cards), 3)
        end_turn(state, "P1")
        start_turn(state, "P2", draw_count=2, cp=3)
        self.assertEqual(len(state.players["P2"].hand.cards), 4)
        end_turn(state, "P2")
        start_turn(state, "P1", draw_count=2, cp=3)
        self.assertEqual(len(state.players["P1"].hand.cards), 5)
        end_turn(state, "P1")
        start_turn(state, "P2", draw_count=2, cp=3)
        self.assertEqual(len(state.players["P2"].hand.cards), 6)
        end_turn(state, "P2")
        start_turn(state, "P1", draw_count=2, cp=4)
        self.assertEqual(len(state.players["P1"].hand.cards), MAX_HAND_SIZE)
        end_turn(state, "P1")

        p2_deck_before_six_to_seven = len(state.players["P2"].deck.cards)
        start_turn(state, "P2", draw_count=2, cp=4)
        self.assertEqual(len(state.players["P2"].hand.cards), MAX_HAND_SIZE)
        self.assertEqual(len(state.players["P2"].deck.cards), p2_deck_before_six_to_seven - 1)
        p2_skip = [event for event in state.event_store.events if event.type == "draw_skipped"][-1]
        self.assertEqual(p2_skip.payload["drawn_count"], 1)
        self.assertEqual(p2_skip.payload["skipped_count"], 1)
        end_turn(state, "P2")

        p1_deck_before_full = len(state.players["P1"].deck.cards)
        start_turn(state, "P1", draw_count=2, cp=5)
        self.assertEqual(len(state.players["P1"].hand.cards), MAX_HAND_SIZE)
        self.assertEqual(len(state.players["P1"].deck.cards), p1_deck_before_full)
        p1_skip = [event for event in state.event_store.events if event.type == "draw_skipped"][-1]
        self.assertEqual(p1_skip.payload["drawn_count"], 0)
        self.assertEqual(p1_skip.payload["skipped_count"], 2)
        cards_drawn = [event for event in state.event_store.events if event.type == "cards_drawn"][-1]
        self.assertEqual(cards_drawn.payload["count"], 0)

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
                "block_declared",
                "battle_started",
                "damage_dealt",
                "damage_dealt",
                "battle_draw",
                "unit_destroyed",
                "card_moved",
                "unit_destroyed",
                "card_moved",
            ],
        )

    def test_battle_win_level_three_overclock_recovers_action(self) -> None:
        catalog = dict(self.catalog)
        catalog["T-WIN-001"] = CardDefinition(
            card_no="T-WIN-001",
            category="unit",
            color="test",
            name="battle winner",
            cp=1,
            bp_by_level=(8, 8, 8),
            abilities=(),
        )
        state = create_game_state(catalog)
        attacker_card = state.create_card_instance("T-WIN-001", "P1", level=2)
        blocker_card = state.create_card_instance("1-0-040", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        blocker = state.create_unit(blocker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(blocker.unit_id)

        attack_unit(state, "P1", attacker.unit_id, blocker.unit_id)

        self.assertIn(attacker.unit_id, state.units)
        self.assertEqual(attacker.level, 3)
        self.assertFalse(attacker.exhausted)
        event_types = [event.type for event in state.event_store.events]
        self.assertIn("unit_overclocked", event_types)
        self.assertIn("unit_action_recovered", event_types)
        recover_event = [event for event in state.event_store.events if event.type == "unit_action_recovered"][-1]
        self.assertEqual(recover_event.payload["unit_id"], attacker.unit_id)
        self.assertEqual(recover_event.payload["reason"], "overclock")

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

    def test_shiranui_attack_cost_discards_selected_hand_card_and_modifies_bp(self) -> None:
        state = create_game_state(self.catalog)
        attacker_card = state.create_card_instance("1-0-010", "P1")
        first_cost_card = state.create_card_instance("1-0-040", "P1")
        selected_cost_card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(attacker_card.instance_id)
        state.players["P1"].hand.add(first_cost_card.instance_id)
        state.players["P1"].hand.add(selected_cost_card.instance_id)
        state.players["P1"].current_cp = 10
        attacker = drive_unit(state, "P1", attacker_card.instance_id)
        state.turn_no += 2

        def choose_cost(_state, _source_unit, _ability, _request_event, _step, legal_choices):
            self.assertEqual(
                [choice["card_instance_id"] for choice in legal_choices],
                [first_cost_card.instance_id, selected_cost_card.instance_id],
            )
            return {"card_instance_id": selected_cost_card.instance_id}

        before_bp = get_unit_bp(state, attacker)
        declare_attack(state, "P1", attacker.unit_id, ability_cost_choice=choose_cost)

        self.assertEqual(state.players["P1"].hand.cards, [first_cost_card.instance_id])
        self.assertEqual(state.players["P1"].discard_pile.cards, [selected_cost_card.instance_id])
        self.assertEqual(get_unit_bp(state, attacker), before_bp + 4000)
        event_types = [event.type for event in state.event_store.events]
        self.assertNotIn("optional_ability", [event.payload.get("type") for event in state.event_store.events])
        self.assertIn("ability_cost_paid", event_types)
        self.assertIn("ability_resolved", event_types)

    def test_shiranui_attack_without_enough_hand_cost_fails_without_bp_modifier(self) -> None:
        state = create_game_state(self.catalog)
        attacker_card = state.create_card_instance("1-0-010", "P1")
        state.players["P1"].hand.add(attacker_card.instance_id)
        state.players["P1"].current_cp = 10
        attacker = drive_unit(state, "P1", attacker_card.instance_id)
        state.turn_no += 2

        before_bp = get_unit_bp(state, attacker)
        declare_attack(state, "P1", attacker.unit_id)

        self.assertEqual(state.players["P1"].hand.cards, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [])
        self.assertEqual(get_unit_bp(state, attacker), before_bp)
        self.assertNotIn("ability_cost_paid", [event.type for event in state.event_store.events])
        self.assertIn("ability_cost_failed", [event.type for event in state.event_store.events])

    def test_fox_commando_oc_cost_discards_two_and_draws_two(self) -> None:
        state = create_game_state(self.catalog)
        target_card = state.create_card_instance("1-0-041", "P1")
        first_material = state.create_card_instance("1-0-041", "P1")
        second_material = state.create_card_instance("1-0-041", "P1")
        first_cost = state.create_card_instance("1-0-040", "P1")
        second_cost = state.create_card_instance("1-0-001", "P1")
        override_draw_one = state.create_card_instance("1-0-006", "P1")
        override_draw_two = state.create_card_instance("1-0-007", "P1")
        draw_one = state.create_card_instance("1-0-004", "P1")
        draw_two = state.create_card_instance("1-0-005", "P1")
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(target_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P1"].hand.add(first_cost.instance_id)
        state.players["P1"].hand.add(second_cost.instance_id)
        state.players["P1"].deck.cards.extend(
            [override_draw_one.instance_id, override_draw_two.instance_id, draw_one.instance_id, draw_two.instance_id]
        )

        def choose_cost(_state, _source_unit, _ability, _request_event, _step, _legal_choices):
            return {"card_instance_ids": [first_cost.instance_id, second_cost.instance_id]}

        override_card(state, "P1", target_card.instance_id, first_material.instance_id)
        override_card(state, "P1", target_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", target_card.instance_id, ability_cost_choice=choose_cost)

        self.assertEqual(
            set(state.players["P1"].discard_pile.cards),
            {first_material.instance_id, second_material.instance_id, first_cost.instance_id, second_cost.instance_id},
        )
        self.assertEqual(
            state.players["P1"].hand.cards,
            [override_draw_one.instance_id, override_draw_two.instance_id, draw_one.instance_id, draw_two.instance_id],
        )
        self.assertIn("ability_cost_paid", [event.type for event in state.event_store.events])
        self.assertIn("cards_drawn", [event.type for event in state.event_store.events])

    def test_bakudalman_oc_deals_damage_to_all_rival_units(self) -> None:
        state = create_game_state(self.catalog)
        target_card = state.create_card_instance("1-0-003", "P1")
        first_material = state.create_card_instance("1-0-003", "P1")
        second_material = state.create_card_instance("1-0-003", "P1")
        first_target_card = state.create_card_instance("1-0-048", "P2")
        second_target_card = state.create_card_instance("1-0-048", "P2")
        own_unit_card = state.create_card_instance("1-0-048", "P1")
        first_target = state.create_unit(first_target_card.instance_id)
        second_target = state.create_unit(second_target_card.instance_id)
        own_unit = state.create_unit(own_unit_card.instance_id)
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(target_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P1"].battlefield.add(own_unit.unit_id)
        state.players["P2"].battlefield.add(first_target.unit_id)
        state.players["P2"].battlefield.add(second_target.unit_id)

        override_card(state, "P1", target_card.instance_id, first_material.instance_id)
        override_card(state, "P1", target_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", target_card.instance_id)

        damage_events = [event for event in state.event_store.events if event.type == "damage_dealt"]
        self.assertEqual(
            [event.payload["target_unit_id"] for event in damage_events],
            [first_target.unit_id, second_target.unit_id],
        )
        self.assertEqual(own_unit.current_damage, 0)

    def test_bakudalman_oc_resolves_and_fizzles_when_no_rival_units(self) -> None:
        state = create_game_state(self.catalog)
        target_card = state.create_card_instance("1-0-003", "P1")
        first_material = state.create_card_instance("1-0-003", "P1")
        second_material = state.create_card_instance("1-0-003", "P1")
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(target_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)

        override_card(state, "P1", target_card.instance_id, first_material.instance_id)
        override_card(state, "P1", target_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", target_card.instance_id)

        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("damage_dealt", [event.type for event in state.event_store.events])

    def test_don_pelotzanno_oc_destroys_level_two_or_higher_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        target_card = state.create_card_instance("1-0-030", "P1")
        first_material = state.create_card_instance("1-0-030", "P1")
        second_material = state.create_card_instance("1-0-030", "P1")
        level_one_card = state.create_card_instance("1-0-040", "P2", level=1)
        level_two_card = state.create_card_instance("1-0-048", "P2", level=2)
        level_one = state.create_unit(level_one_card.instance_id)
        level_two = state.create_unit(level_two_card.instance_id)
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(target_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P2"].battlefield.add(level_one.unit_id)
        state.players["P2"].battlefield.add(level_two.unit_id)

        override_card(state, "P1", target_card.instance_id, first_material.instance_id)
        override_card(state, "P1", target_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", target_card.instance_id)

        self.assertIn(level_one.unit_id, state.units)
        self.assertNotIn(level_two.unit_id, state.units)
        self.assertEqual(state.players["P2"].discard_pile.cards, [level_two.card_instance_id])
        destroyed_events = [event for event in state.event_store.events if event.type == "unit_destroyed"]
        self.assertEqual(destroyed_events[-1].payload["reason"], "effect")

    def test_don_pelotzanno_oc_resolves_and_fizzles_without_level_two_target(self) -> None:
        state = create_game_state(self.catalog)
        target_card = state.create_card_instance("1-0-030", "P1")
        first_material = state.create_card_instance("1-0-030", "P1")
        second_material = state.create_card_instance("1-0-030", "P1")
        level_one_card = state.create_card_instance("1-0-040", "P2", level=1)
        level_one = state.create_unit(level_one_card.instance_id)
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(target_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P2"].battlefield.add(level_one.unit_id)

        override_card(state, "P1", target_card.instance_id, first_material.instance_id)
        override_card(state, "P1", target_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", target_card.instance_id)

        self.assertIn(level_one.unit_id, state.units)
        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("unit_destroyed", [event.type for event in state.event_store.events])

    def test_konjiki_komainu_oc_consumes_ready_rival_unit_action(self) -> None:
        state = create_game_state(self.catalog)
        source_card = state.create_card_instance("1-0-016", "P1")
        first_material = state.create_card_instance("1-0-016", "P1")
        second_material = state.create_card_instance("1-0-016", "P1")
        ready_card = state.create_card_instance("1-0-001", "P2")
        exhausted_card = state.create_card_instance("1-0-004", "P2")
        ready = state.create_unit(ready_card.instance_id)
        exhausted = state.create_unit(exhausted_card.instance_id)
        exhausted.exhausted = True
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(source_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P2"].battlefield.add(exhausted.unit_id)
        state.players["P2"].battlefield.add(ready.unit_id)

        override_card(state, "P1", source_card.instance_id, first_material.instance_id)
        override_card(state, "P1", source_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", source_card.instance_id)

        self.assertTrue(ready.exhausted)
        self.assertTrue(exhausted.exhausted)
        self.assertIn("unit_action_consumed", [event.type for event in state.event_store.events])
        choice_requests = [event for event in state.event_store.events if event.type == "choice_requested"]
        self.assertEqual(choice_requests[-1].payload["candidate_unit_ids"], [ready.unit_id])

    def test_konjiki_komainu_oc_fizzles_without_ready_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        source_card = state.create_card_instance("1-0-016", "P1")
        first_material = state.create_card_instance("1-0-016", "P1")
        second_material = state.create_card_instance("1-0-016", "P1")
        exhausted_card = state.create_card_instance("1-0-004", "P2")
        exhausted = state.create_unit(exhausted_card.instance_id)
        exhausted.exhausted = True
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(source_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P2"].battlefield.add(exhausted.unit_id)

        override_card(state, "P1", source_card.instance_id, first_material.instance_id)
        override_card(state, "P1", source_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", source_card.instance_id)

        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("unit_action_consumed", [event.type for event in state.event_store.events])

    def test_kohan_no_arie_cip_consumes_ready_rival_unit_action(self) -> None:
        state = create_game_state(self.catalog)
        source_card = state.create_card_instance("1-0-017", "P1")
        ready_card = state.create_card_instance("1-0-001", "P2")
        exhausted_card = state.create_card_instance("1-0-004", "P2")
        ready = state.create_unit(ready_card.instance_id)
        exhausted = state.create_unit(exhausted_card.instance_id)
        exhausted.exhausted = True
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(source_card.instance_id)
        state.players["P2"].battlefield.add(exhausted.unit_id)
        state.players["P2"].battlefield.add(ready.unit_id)

        drive_unit(state, "P1", source_card.instance_id)

        self.assertTrue(ready.exhausted)
        self.assertTrue(exhausted.exhausted)
        self.assertIn("unit_action_consumed", [event.type for event in state.event_store.events])
        choice_requests = [event for event in state.event_store.events if event.type == "choice_requested"]
        self.assertEqual(choice_requests[-1].payload["candidate_unit_ids"], [ready.unit_id])

    def test_kohan_no_arie_cip_fizzles_without_ready_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        source_card = state.create_card_instance("1-0-017", "P1")
        exhausted_card = state.create_card_instance("1-0-004", "P2")
        exhausted = state.create_unit(exhausted_card.instance_id)
        exhausted.exhausted = True
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(source_card.instance_id)
        state.players["P2"].battlefield.add(exhausted.unit_id)

        drive_unit(state, "P1", source_card.instance_id)

        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("unit_action_consumed", [event.type for event in state.event_store.events])

    def test_kerol_kid_oc_reduces_rival_unit_base_bp_permanently(self) -> None:
        state = create_game_state(self.catalog)
        source_card = state.create_card_instance("1-0-042", "P1")
        first_material = state.create_card_instance("1-0-042", "P1")
        second_material = state.create_card_instance("1-0-042", "P1")
        target_card = state.create_card_instance("1-0-048", "P2")
        rival_target = state.create_unit(target_card.instance_id)
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(source_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P2"].battlefield.add(rival_target.unit_id)
        before_base_bp = get_unit_base_bp(state, rival_target)

        override_card(state, "P1", source_card.instance_id, first_material.instance_id)
        override_card(state, "P1", source_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", source_card.instance_id)
        end_turn(state, "P1")

        self.assertEqual(get_unit_base_bp(state, rival_target), before_base_bp - 3000)
        self.assertEqual(get_unit_bp(state, rival_target), before_base_bp - 3000)
        self.assertEqual(rival_target.base_bp_modifiers[-1]["duration"], "permanent")
        self.assertIn("base_bp_modified", [event.type for event in state.event_store.events])

    def test_barbatos_cip_reduces_rival_unit_base_bp_permanently(self) -> None:
        state = create_game_state(self.catalog)
        base_card = state.create_card_instance("1-0-040", "P1")
        barbatos_card = state.create_card_instance("1-0-051", "P1")
        target_card = state.create_card_instance("1-0-048", "P2")
        base_unit = state.create_unit(base_card.instance_id)
        rival_target = state.create_unit(target_card.instance_id)
        state.players["P1"].current_cp = 10
        state.players["P1"].battlefield.add(base_unit.unit_id)
        state.players["P1"].hand.add(barbatos_card.instance_id)
        state.players["P2"].battlefield.add(rival_target.unit_id)
        before_level1_base_bp = get_unit_base_bp(state, rival_target)

        drive_unit(state, "P1", barbatos_card.instance_id, evolve_target_unit_id=base_unit.unit_id)
        after_level1_base_bp = get_unit_base_bp(state, rival_target)
        end_turn(state, "P1")
        rival_target.level = 2
        state.card_instances[rival_target.card_instance_id].level = 2

        self.assertIn(rival_target.unit_id, state.units)
        self.assertEqual(rival_target.base_bp_modifiers[-1]["amount"], -4000)
        self.assertEqual(rival_target.base_bp_modifiers[-1]["duration"], "permanent")
        self.assertEqual(after_level1_base_bp, before_level1_base_bp - 4000)
        self.assertEqual(get_unit_base_bp(state, rival_target), self.catalog["1-0-048"].bp_by_level[1] * 1000 - 4000)
        self.assertIn("base_bp_modified", [event.type for event in state.event_store.events])

    def test_barbatos_cip_destroys_rival_unit_when_base_bp_reaches_zero(self) -> None:
        state = create_game_state(self.catalog)
        base_card = state.create_card_instance("1-0-040", "P1")
        barbatos_card = state.create_card_instance("1-0-051", "P1")
        target_card = state.create_card_instance("1-0-040", "P2")
        base_unit = state.create_unit(base_card.instance_id)
        rival_target = state.create_unit(target_card.instance_id)
        state.players["P1"].current_cp = 10
        state.players["P1"].battlefield.add(base_unit.unit_id)
        state.players["P1"].hand.add(barbatos_card.instance_id)
        state.players["P2"].battlefield.add(rival_target.unit_id)

        drive_unit(state, "P1", barbatos_card.instance_id, evolve_target_unit_id=base_unit.unit_id)

        self.assertNotIn(rival_target.unit_id, state.units)
        self.assertIn(target_card.instance_id, state.players["P2"].discard_pile.cards)
        self.assertIn("unit_destroyed", [event.type for event in state.event_store.events])

    def test_battlefield_unit_override_is_rejected(self) -> None:
        state = create_game_state(self.catalog)
        base_card = state.create_card_instance("1-0-048", "P1")
        material_card = state.create_card_instance("1-0-048", "P1")
        unit = state.create_unit(base_card.instance_id)
        state.players["P1"].battlefield.add(unit.unit_id)
        state.players["P1"].hand.add(material_card.instance_id)

        with self.assertRaisesRegex(ValueError, "battlefield unit override"):
            overclock_unit(state, "P1", material_card.instance_id, unit.unit_id)

        self.assertEqual(state.players["P1"].hand.cards, [material_card.instance_id])
        self.assertEqual(state.players["P1"].battlefield.units, [unit.unit_id])
        self.assertEqual(state.event_store.events, ())

    def test_viper_cip_returns_random_unit_from_discard_to_hand_preserving_instance(self) -> None:
        state = create_game_state(self.catalog)
        viper = state.create_card_instance("1-0-033", "P1")
        discarded_unit = state.create_card_instance("1-0-001", "P1")
        discarded_trigger = state.create_card_instance("1-0-061", "P1")
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(viper.instance_id)
        state.players["P1"].discard_pile.add(discarded_trigger.instance_id)
        state.players["P1"].discard_pile.add(discarded_unit.instance_id)

        drive_unit(state, "P1", viper.instance_id)

        self.assertIn(discarded_unit.instance_id, state.players["P1"].hand.cards)
        self.assertNotIn(discarded_unit.instance_id, state.players["P1"].discard_pile.cards)
        self.assertIn(discarded_trigger.instance_id, state.players["P1"].discard_pile.cards)
        random_events = [event for event in state.event_store.events if event.type == "random_resolved"]
        self.assertEqual(random_events[-1].payload["kind"], "discard_pile_card")
        self.assertEqual(random_events[-1].payload["candidate_card_instance_ids"], [discarded_unit.instance_id])

    def test_viper_cip_fizzles_without_unit_in_discard(self) -> None:
        state = create_game_state(self.catalog)
        viper = state.create_card_instance("1-0-033", "P1")
        discarded_trigger = state.create_card_instance("1-0-061", "P1")
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(viper.instance_id)
        state.players["P1"].discard_pile.add(discarded_trigger.instance_id)

        drive_unit(state, "P1", viper.instance_id)

        self.assertEqual(state.players["P1"].hand.cards, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [discarded_trigger.instance_id])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])

    def test_skull_walker_pig_returns_random_unit_from_discard_to_hand(self) -> None:
        state = create_game_state(self.catalog)
        skull_card = state.create_card_instance("1-0-028", "P1")
        attacker_card = state.create_card_instance("1-0-001", "P2")
        revive_target = state.create_card_instance("1-0-001", "P1")
        non_unit = state.create_card_instance("1-0-061", "P1")
        skull = state.create_unit(skull_card.instance_id)
        attacker = state.create_unit(attacker_card.instance_id)
        state.players["P1"].battlefield.add(skull.unit_id)
        state.players["P2"].battlefield.add(attacker.unit_id)
        state.players["P1"].discard_pile.add(non_unit.instance_id)
        state.players["P1"].discard_pile.add(revive_target.instance_id)

        from tojs_reborn.engine.combat import destroy_unit

        destroy_unit(state, skull, cause_event_no=0, reason="test")

        self.assertNotIn(skull.unit_id, state.units)
        self.assertIn(revive_target.instance_id, state.players["P1"].hand.cards)
        self.assertIn(non_unit.instance_id, state.players["P1"].discard_pile.cards)
        random_events = [event for event in state.event_store.events if event.type == "random_resolved"]
        self.assertEqual(random_events[-1].payload["kind"], "discard_pile_card")
        self.assertEqual(
            random_events[-1].payload["candidate_card_instance_ids"],
            [revive_target.instance_id],
        )

    def test_skull_walker_pig_does_not_include_itself_as_revival_candidate(self) -> None:
        state = create_game_state(self.catalog)
        skull_card = state.create_card_instance("1-0-028", "P1")
        non_unit = state.create_card_instance("1-0-061", "P1")
        skull = state.create_unit(skull_card.instance_id)
        state.players["P1"].battlefield.add(skull.unit_id)
        state.players["P1"].discard_pile.add(non_unit.instance_id)

        from tojs_reborn.engine.combat import destroy_unit

        destroy_unit(state, skull, cause_event_no=0, reason="test")

        self.assertEqual(state.players["P1"].hand.cards, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [skull_card.instance_id, non_unit.instance_id])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        event_types = [event.type for event in state.event_store.events]
        self.assertLess(event_types.index("ability_resolved"), event_types.index("card_moved"))

    def test_lina_oc_chooses_card_from_discard_to_hand(self) -> None:
        state = create_game_state(self.catalog)
        lina = state.create_card_instance("1-0-031", "P1")
        first_material = state.create_card_instance("1-0-031", "P1")
        second_material = state.create_card_instance("1-0-031", "P1")
        first_discard = state.create_card_instance("1-0-061", "P1")
        second_discard = state.create_card_instance("1-0-001", "P1")
        first_override_draw = state.create_card_instance("1-0-004", "P1")
        second_override_draw = state.create_card_instance("1-0-005", "P1")
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(lina.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P1"].deck.cards.extend([first_override_draw.instance_id, second_override_draw.instance_id])

        override_card(state, "P1", lina.instance_id, first_material.instance_id)
        override_card(state, "P1", lina.instance_id, second_material.instance_id)
        state.players["P1"].discard_pile.add(second_discard.instance_id)
        state.players["P1"].discard_pile.add(first_discard.instance_id)
        drive_unit(state, "P1", lina.instance_id)

        self.assertIn(first_discard.instance_id, state.players["P1"].hand.cards)
        self.assertIn(second_discard.instance_id, state.players["P1"].discard_pile.cards)
        choice_requests = [event for event in state.event_store.events if event.type == "choice_requested"]
        self.assertEqual(choice_requests[-1].payload["type"], "card")
        self.assertEqual(
            choice_requests[-1].payload["candidate_card_instance_ids"],
            [first_discard.instance_id, second_discard.instance_id, second_material.instance_id, first_material.instance_id],
        )
        choice_selected = [event for event in state.event_store.events if event.type == "choice_selected"][-1]
        self.assertEqual(choice_selected.payload["chosen_card_instance_id"], first_discard.instance_id)

    def test_lina_oc_fizzles_without_discard_target(self) -> None:
        state = create_game_state(self.catalog)
        lina = state.create_card_instance("1-0-031", "P1", level=3)
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(lina.instance_id)

        drive_unit(state, "P1", lina.instance_id)

        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])

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
        mummy.current_damage = get_unit_bp(state, mummy)
        crow.current_damage = get_unit_bp(state, crow)
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

    def test_replay_record_verifies_event_log_and_final_state(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].deck.cards.append(card.instance_id)

        draw_cards(state, "P1", 1)
        replay_record = build_replay_record(state)

        self.assertTrue(verify_replay_record(state, replay_record))
        self.assertEqual(replay_record["ruleset"]["max_trigger_zone_cards"], ruleset_to_dict()["max_trigger_zone_cards"])
        replay_record["events"][0]["type"] = "changed"
        self.assertFalse(verify_replay_record(state, replay_record))

    def test_replay_record_reexecutes_intents_and_matches_events(self) -> None:
        state = create_game_state(self.catalog, seed=9)
        happaloid = state.create_card_instance("1-0-040", "P1")
        draw_target = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(happaloid.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)
        state.players["P1"].current_cp = 1
        initial_state = snapshot_initial_state(state)
        intents = [{"type": "drive_unit", "player_id": "P1", "card_instance_id": happaloid.instance_id}]

        for intent in intents:
            from tojs_reborn.engine.replay import apply_intent

            apply_intent(state, intent)
        record = build_replay_record(state, initial_state=initial_state, intents=intents)
        replayed = replay_record(self.catalog, record)

        self.assertEqual(replayed.event_store.to_list(), state.event_store.to_list())
        self.assertEqual(replayed.players["P1"].hand.cards, [draw_target.instance_id])

    def test_seeded_random_discard_records_replayable_choice(self) -> None:
        state = create_game_state(self.catalog, seed=3)
        state.turn_player_id = "P1"
        mummy_card = state.create_card_instance("1-0-027", "P1")
        mummy = state.create_unit(mummy_card.instance_id)
        state.players["P1"].battlefield.add(mummy.unit_id)
        hand_cards = [state.create_card_instance("1-0-001", "P2") for _ in range(3)]
        for card in hand_cards:
            state.players["P2"].hand.add(card.instance_id)
        mummy.current_damage = get_unit_bp(state, mummy)

        destroy_lethal_units(state, [mummy], cause_event_no=0)

        random_event = next(event for event in state.event_store.events if event.type == "random_resolved")
        chosen_index = random_event.payload["chosen_index"]
        self.assertEqual(random_event.payload["seed"], 3)
        self.assertEqual(
            random_event.payload["chosen_card_instance_id"],
            random_event.payload["candidate_card_instance_ids"][chosen_index],
        )

    def test_attack_damage_uses_selector_and_can_destroy_target(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        lancer_card = state.create_card_instance("1-0-004", "P1")
        target_card = state.create_card_instance("1-0-001", "P2")
        lancer = state.create_unit(lancer_card.instance_id)
        target = state.create_unit(target_card.instance_id)
        state.players["P1"].battlefield.add(lancer.unit_id)
        state.players["P2"].battlefield.add(target.unit_id)
        target.current_damage = 2000

        attack_player(state, "P1", lancer.unit_id)

        self.assertNotIn(target.unit_id, state.units)
        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("choice_requested", [event.type for event in state.event_store.events])
        self.assertIn("choice_selected", [event.type for event in state.event_store.events])
        damage_events = [event for event in state.event_store.events if event.type == "damage_dealt"]
        self.assertEqual(damage_events[0].payload["reason"], "effect")

    def test_target_required_ability_resolves_and_fizzles_without_target(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        lancer_card = state.create_card_instance("1-0-004", "P1")
        lancer = state.create_unit(lancer_card.instance_id)
        state.players["P1"].battlefield.add(lancer.unit_id)

        attack_player(state, "P1", lancer.unit_id)

        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual([event.source.ability_id for event in ability_events], ["1-0-004:a1"])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        fizzled_event = next(event for event in state.event_store.events if event.type == "effect_fizzled")
        self.assertIn(fizzled_event.payload["reason"], EFFECT_FIZZLED_REASONS)

    def test_grind_beetle_cip_changes_cp(self) -> None:
        state = create_game_state(self.catalog)
        beetle = state.create_card_instance("1-0-043", "P1")
        state.players["P1"].hand.add(beetle.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", beetle.instance_id)

        self.assertEqual(state.players["P1"].current_cp, 10 - self.catalog["1-0-043"].cp + 2)
        self.assertIn("cp_changed", [event.type for event in state.event_store.events])
        self.assertEqual(
            [event.source.ability_id for event in state.event_store.events if event.type == "ability_resolved"],
            ["1-0-043:a1"],
        )

    def test_dartagnan_cip_changes_cp_and_attack_draws_card(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        state.turn_player_id = "P1"
        dartagnan = state.create_card_instance("1-0-047", "P1")
        draw_target = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(dartagnan.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)
        state.players["P1"].current_cp = 10

        unit = drive_unit(state, "P1", dartagnan.instance_id)

        self.assertEqual(state.players["P1"].current_cp, 10 - (self.catalog["1-0-047"].cp or 0) + 2)

        state.turn_no += 2
        declare_attack(state, "P1", unit.unit_id)

        self.assertEqual(state.players["P1"].hand.cards, [draw_target.instance_id])
        self.assertEqual(
            [event.source.ability_id for event in state.event_store.events if event.type == "ability_resolved"],
            ["1-0-047:a1", "1-0-047:a2"],
        )

    def test_trigger_zone_card_can_be_set_and_destroyed_randomly(self) -> None:
        state = create_game_state(self.catalog, seed=1)
        trigger_card = state.create_card_instance("1-0-065", "P2")
        hellhound = state.create_card_instance("1-0-005", "P1")
        state.players["P2"].hand.add(trigger_card.instance_id)
        state.players["P1"].hand.add(hellhound.instance_id)
        state.players["P1"].current_cp = 10

        set_trigger(state, "P2", trigger_card.instance_id)
        drive_unit(state, "P1", hellhound.instance_id)

        self.assertEqual(state.players["P2"].trigger_zone.cards, [])
        self.assertIn(trigger_card.instance_id, state.players["P2"].discard_pile.cards)
        self.assertIn("random_resolved", [event.type for event in state.event_store.events])

    def test_ruleset_controls_trigger_zone_limit_and_turn_cp(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        trigger_cards = [state.create_card_instance("1-0-097", "P1") for _ in range(MAX_TRIGGER_ZONE_CARDS + 1)]
        for card in trigger_cards:
            state.players["P1"].hand.add(card.instance_id)
        for card in trigger_cards[:MAX_TRIGGER_ZONE_CARDS]:
            set_trigger(state, "P1", card.instance_id)

        legal_action_types = [action["type"] for action in list_legal_actions(state, "P1")]

        self.assertNotIn("set_trigger", legal_action_types)
        with self.assertRaisesRegex(ValueError, "trigger zone limit"):
            set_trigger(state, "P1", trigger_cards[-1].instance_id)
        self.assertEqual(turn_cp_for("P1", 99), 7)
        self.assertEqual(turn_cp_for("P2", 1), 3)

    def test_integrity_check_detects_duplicate_card_instance_across_zones(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].hand.add(card.instance_id)

        assert_game_state_integrity(state)

        state.players["P1"].deck.cards.append(card.instance_id)
        with self.assertRaisesRegex(AssertionError, "multiple zones"):
            assert_game_state_integrity(state)

    def test_trigger_intercept_window_lists_public_candidates(self) -> None:
        state = create_game_state(self.catalog)
        trigger_card = state.create_card_instance("1-0-065", "P1")
        state.players["P1"].trigger_zone.add(trigger_card.instance_id)
        state.players["P1"].current_cp = 1

        window = list_trigger_intercept_window(state, "P1", window="attack", cause_event_no=1)

        self.assertEqual(window["pass_action"]["type"], "pass_window")
        self.assertEqual(window["pass_action"]["window"], "attack")
        self.assertIn("display", window["pass_action"])
        self.assertEqual(window["candidates"][0]["card_instance_id"], trigger_card.instance_id)

    def test_colorless_intercept_requires_only_cp_to_be_listed(self) -> None:
        state = create_game_state(self.catalog)
        colorless_intercept = state.create_card_instance("1-0-065", "P1")
        state.players["P1"].trigger_zone.add(colorless_intercept.instance_id)

        state.players["P1"].current_cp = 0
        window = list_trigger_intercept_window(state, "P1", window="attack", cause_event_no=1)
        self.assertEqual(window["candidates"], [])

        state.players["P1"].current_cp = 1
        window = list_trigger_intercept_window(state, "P1", window="attack", cause_event_no=1)
        self.assertEqual(window["candidates"][0]["card_instance_id"], colorless_intercept.instance_id)

    def test_moon_savior_attack_window_opens_for_owner_attack_and_pass_is_logged(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        _attacker_card, attacker = self._add_battlefield_unit(state, "P1", "1-0-027")
        moon_savior = state.create_card_instance("1-0-089", "P1")
        state.players["P1"].trigger_zone.add(moon_savior.instance_id)
        state.players["P1"].current_cp = 1
        cause_event = state.event_store.append(
            "unit_attacked",
            round_no=1,
            turn_no=1,
            actor_player_id="P1",
            source=EventSource(card_no=attacker.card_no, card_instance_id=attacker.card_instance_id, unit_id=attacker.unit_id),
            payload={"attacker_unit_id": attacker.unit_id},
        )

        activated_count = process_intercept_window(state, "attack", cause_event.event_no)

        self.assertEqual(activated_count, 0)
        self.assertIn("intercept_window_opened", [event.type for event in state.event_store.events])
        self.assertEqual([event.type for event in state.event_store.events].count("intercept_passed"), 2)
        self.assertEqual(state.players["P1"].trigger_zone.cards, [moon_savior.instance_id])

    def test_moon_savior_attack_window_ignores_rival_attack(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P2"
        _owner_card, owner_unit = self._add_battlefield_unit(state, "P1", "1-0-027")
        _attacker_card, attacker = self._add_battlefield_unit(state, "P2", "1-0-001")
        moon_savior = state.create_card_instance("1-0-089", "P1")
        state.players["P1"].trigger_zone.add(moon_savior.instance_id)
        state.players["P1"].current_cp = 1
        cause_event = state.event_store.append(
            "unit_attacked",
            round_no=1,
            turn_no=1,
            actor_player_id="P2",
            source=EventSource(card_no=attacker.card_no, card_instance_id=attacker.card_instance_id, unit_id=attacker.unit_id),
            payload={"attacker_unit_id": attacker.unit_id},
        )

        activated_count = process_intercept_window(state, "attack", cause_event.event_no)

        self.assertEqual(activated_count, 0)
        self.assertNotIn("intercept_window_opened", [event.type for event in state.event_store.events])
        self.assertIn(owner_unit.unit_id, state.units)

    def test_moon_savior_destroys_level_two_or_higher_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        _attacker_card, attacker = self._add_battlefield_unit(state, "P1", "1-0-027")
        rival_card, rival = self._add_battlefield_unit(state, "P2", "1-0-004")
        rival.level = 2
        moon_savior = state.create_card_instance("1-0-089", "P1")
        state.players["P1"].trigger_zone.add(moon_savior.instance_id)
        state.players["P1"].current_cp = 1
        cause_event = state.event_store.append(
            "unit_attacked",
            round_no=1,
            turn_no=1,
            actor_player_id="P1",
            source=EventSource(card_no=attacker.card_no, card_instance_id=attacker.card_instance_id, unit_id=attacker.unit_id),
            payload={"attacker_unit_id": attacker.unit_id},
        )

        activated_count = process_intercept_window(
            state,
            "attack",
            cause_event.event_no,
            choose_intercept=lambda _player_id, actions: actions[0],
        )

        self.assertEqual(activated_count, 1)
        self.assertNotIn(rival.unit_id, state.units)
        self.assertIn(rival_card.instance_id, state.players["P2"].discard_pile.cards)
        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].current_cp, 0)

    def test_ectoplasm_destroyed_unit_window_destroys_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        _support_card, support_unit = self._add_battlefield_unit(state, "P1", "1-0-027")
        destroyed_card = state.create_card_instance("1-0-031", "P1")
        destroyed_unit = state.create_unit(destroyed_card.instance_id)
        rival_card, rival_unit = self._add_battlefield_unit(state, "P2", "1-0-040")
        ectoplasm = state.create_card_instance("1-0-092", "P1")
        state.players["P1"].trigger_zone.add(ectoplasm.instance_id)
        state.players["P1"].current_cp = 3
        cause_event = state.event_store.append(
            "unit_destroyed",
            round_no=1,
            turn_no=1,
            actor_player_id="P1",
            source=EventSource(
                card_no=destroyed_unit.card_no,
                card_instance_id=destroyed_unit.card_instance_id,
                unit_id=destroyed_unit.unit_id,
            ),
            payload={"reason": "battle"},
        )

        activated_count = process_intercept_window(
            state,
            "unit_destroyed",
            cause_event.event_no,
            choose_intercept=lambda _player_id, actions: actions[0],
        )

        self.assertEqual(activated_count, 1)
        self.assertIn(support_unit.unit_id, state.units)
        self.assertNotIn(rival_unit.unit_id, state.units)
        self.assertIn(rival_card.instance_id, state.players["P2"].discard_pile.cards)
        self.assertEqual(state.players["P1"].current_cp, 0)
        self.assertEqual(state.players["P1"].trigger_zone.cards, [])

    def test_battle_intercept_window_opens_attacker_side_first(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        _attacker_card, attacker = self._add_battlefield_unit(state, "P1", "1-0-001")
        _blocker_card, blocker = self._add_battlefield_unit(state, "P2", "1-0-045")
        evil_awaken = state.create_card_instance("1-0-081", "P1")
        impervious_wall = state.create_card_instance("1-0-096", "P2")
        state.players["P1"].trigger_zone.add(evil_awaken.instance_id)
        state.players["P2"].trigger_zone.add(impervious_wall.instance_id)
        state.players["P1"].current_cp = 0
        state.players["P2"].current_cp = 0
        cause_event = state.event_store.append(
            "battle_started",
            round_no=1,
            turn_no=1,
            actor_player_id="P1",
            source=EventSource(card_no=attacker.card_no, card_instance_id=attacker.card_instance_id, unit_id=attacker.unit_id),
            payload={"attacker_unit_id": attacker.unit_id, "blocker_unit_id": blocker.unit_id},
        )

        activated_count = process_intercept_window(state, "battle", cause_event.event_no)

        self.assertEqual(activated_count, 0)
        opened = [event for event in state.event_store.events if event.type == "intercept_window_opened"][-1]
        self.assertEqual(opened.payload["start_player_id"], "P1")
        pass_events = [event for event in state.event_store.events if event.type == "intercept_passed"]
        self.assertEqual([event.actor_player_id for event in pass_events], ["P1", "P2"])

    def test_evil_awaken_battle_intercept_modifies_own_attacking_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        _attacker_card, attacker = self._add_battlefield_unit(state, "P1", "1-0-001")
        _blocker_card, blocker = self._add_battlefield_unit(state, "P2", "1-0-045")
        evil_awaken = state.create_card_instance("1-0-081", "P1")
        state.players["P1"].trigger_zone.add(evil_awaken.instance_id)
        state.players["P1"].current_cp = 0
        cause_event = state.event_store.append(
            "battle_started",
            round_no=1,
            turn_no=1,
            actor_player_id="P1",
            source=EventSource(card_no=attacker.card_no, card_instance_id=attacker.card_instance_id, unit_id=attacker.unit_id),
            payload={"attacker_unit_id": attacker.unit_id, "blocker_unit_id": blocker.unit_id},
        )
        before_bp = get_unit_bp(state, attacker)

        activated_count = process_intercept_window(
            state,
            "battle",
            cause_event.event_no,
            choose_intercept=lambda _player_id, actions: actions[0],
        )

        self.assertEqual(activated_count, 1)
        self.assertEqual(get_unit_bp(state, attacker), before_bp + 3000)
        bp_event = [event for event in state.event_store.events if event.type == "bp_modified"][-1]
        self.assertEqual(bp_event.payload["target_unit_id"], attacker.unit_id)
        self.assertEqual(state.players["P1"].trigger_zone.cards, [])

    def test_dark_armor_modifies_owner_battle_unit_and_deals_life_damage(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        _attacker_card, attacker = self._add_battlefield_unit(state, "P1", "1-0-027")
        _blocker_card, blocker = self._add_battlefield_unit(state, "P2", "1-0-001")
        dark_armor = state.create_card_instance("1-0-091", "P1")
        state.players["P1"].trigger_zone.add(dark_armor.instance_id)
        state.players["P1"].current_cp = 1
        cause_event = state.event_store.append(
            "battle_started",
            round_no=1,
            turn_no=1,
            actor_player_id="P1",
            source=EventSource(card_no=attacker.card_no, card_instance_id=attacker.card_instance_id, unit_id=attacker.unit_id),
            payload={"attacker_unit_id": attacker.unit_id, "blocker_unit_id": blocker.unit_id},
        )

        activated_count = process_intercept_window(
            state,
            "battle",
            cause_event.event_no,
            choose_intercept=lambda _player_id, actions: actions[0],
        )

        self.assertEqual(activated_count, 1)
        self.assertEqual(state.players["P1"].current_cp, 0)
        self.assertEqual(state.players["P1"].life, 6)
        bp_event = [event for event in state.event_store.events if event.type == "bp_modified"][-1]
        life_event = [event for event in state.event_store.events if event.type == "life_changed"][-1]
        self.assertEqual(bp_event.payload["target_unit_id"], attacker.unit_id)
        self.assertEqual(bp_event.payload["amount"], 7000)
        self.assertEqual(life_event.payload["player_id"], "P1")
        self.assertEqual(life_event.payload["amount"], -1)

    def test_impervious_wall_can_activate_for_own_blocking_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        _attacker_card, attacker = self._add_battlefield_unit(state, "P1", "1-0-001")
        _blocker_card, blocker = self._add_battlefield_unit(state, "P2", "1-0-045")
        impervious_wall = state.create_card_instance("1-0-096", "P2")
        state.players["P2"].trigger_zone.add(impervious_wall.instance_id)
        state.players["P2"].current_cp = 0
        cause_event = state.event_store.append(
            "battle_started",
            round_no=1,
            turn_no=1,
            actor_player_id="P1",
            source=EventSource(card_no=attacker.card_no, card_instance_id=attacker.card_instance_id, unit_id=attacker.unit_id),
            payload={"attacker_unit_id": attacker.unit_id, "blocker_unit_id": blocker.unit_id},
        )
        before_bp = get_unit_bp(state, blocker)

        activated_count = process_intercept_window(
            state,
            "battle",
            cause_event.event_no,
            choose_intercept=lambda _player_id, actions: actions[0],
        )

        self.assertEqual(activated_count, 1)
        self.assertEqual(get_unit_bp(state, blocker), before_bp + 3000)
        bp_event = [event for event in state.event_store.events if event.type == "bp_modified"][-1]
        self.assertEqual(bp_event.payload["target_unit_id"], blocker.unit_id)

    def test_trigger_window_forces_activation_turn_player_then_opponent(self) -> None:
        catalog = dict(self.catalog)
        catalog["T-TRG-001"] = draw_window_card("T-TRG-001", "trigger", "TRIGGER_ANY")
        state = create_game_state(catalog)
        state.turn_player_id = "P1"
        p1_trigger = state.create_card_instance("T-TRG-001", "P1")
        p1_second_trigger = state.create_card_instance("T-TRG-001", "P1")
        p2_trigger = state.create_card_instance("T-TRG-001", "P2")
        p1_draw_1 = state.create_card_instance("1-0-001", "P1")
        p1_draw_2 = state.create_card_instance("1-0-004", "P1")
        p2_draw = state.create_card_instance("1-0-001", "P2")
        state.players["P1"].trigger_zone.cards.extend([p1_trigger.instance_id, p1_second_trigger.instance_id])
        state.players["P2"].trigger_zone.cards.append(p2_trigger.instance_id)
        state.players["P1"].deck.cards.extend([p1_draw_1.instance_id, p1_draw_2.instance_id])
        state.players["P2"].deck.cards.append(p2_draw.instance_id)
        cause_event = state.event_store.append("unit_entered", round_no=1, turn_no=1, actor_player_id="P1")

        activated_count = process_trigger_window(state, cause_event.event_no)

        self.assertEqual(activated_count, 3)
        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P2"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].hand.cards, [p1_draw_1.instance_id, p1_draw_2.instance_id])
        self.assertEqual(state.players["P2"].hand.cards, [p2_draw.instance_id])
        activation_events = [event for event in state.event_store.events if event.type == "trigger_activated"]
        self.assertEqual([event.actor_player_id for event in activation_events], ["P1", "P2", "P1"])
        self.assertEqual(
            [event.source.card_instance_id for event in activation_events],
            [p1_trigger.instance_id, p2_trigger.instance_id, p1_second_trigger.instance_id],
        )

    def test_display_stand_trigger_draws_after_owner_unit_enters(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        trigger_card = state.create_card_instance("1-0-062", "P1")
        entering = state.create_card_instance("1-0-001", "P1")
        draw_target = state.create_card_instance("1-0-004", "P1")
        state.players["P1"].trigger_zone.add(trigger_card.instance_id)
        state.players["P1"].hand.add(entering.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)
        state.players["P1"].current_cp = 1

        drive_unit(state, "P1", entering.instance_id)
        from tojs_reborn.engine.windows import process_windows_for_events

        process_windows_for_events(state, 1)

        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [trigger_card.instance_id])
        self.assertEqual(state.players["P1"].hand.cards, [draw_target.instance_id])
        self.assertIn("trigger_activated", [event.type for event in state.event_store.events])

    def test_new_armor_trigger_draws_intercept_from_deck_without_reordering_other_cards(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        trigger_card = state.create_card_instance("1-0-061", "P1")
        entering = state.create_card_instance("1-0-001", "P1")
        unit_card = state.create_card_instance("1-0-004", "P1")
        intercept_card = state.create_card_instance("1-0-097", "P1")
        second_intercept = state.create_card_instance("1-0-099", "P1")
        state.players["P1"].trigger_zone.add(trigger_card.instance_id)
        state.players["P1"].hand.add(entering.instance_id)
        state.players["P1"].deck.cards.extend([unit_card.instance_id, intercept_card.instance_id, second_intercept.instance_id])
        state.players["P1"].current_cp = 1

        drive_unit(state, "P1", entering.instance_id)
        from tojs_reborn.engine.windows import process_windows_for_events

        process_windows_for_events(state, 1)

        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [trigger_card.instance_id])
        self.assertEqual(state.players["P1"].hand.cards, [intercept_card.instance_id])
        self.assertEqual(state.players["P1"].deck.cards, [unit_card.instance_id, second_intercept.instance_id])
        cards_drawn = [event for event in state.event_store.events if event.type == "cards_drawn"][-1]
        self.assertEqual(cards_drawn.payload["count"], 1)
        move_events = [
            event for event in state.event_store.events
            if event.type == "card_moved" and event.payload.get("from_zone") == "deck"
        ]
        self.assertEqual(move_events[-1].payload["category"], "intercept")

    def test_adjacent_cip_triggers_continue_after_first_trigger_leaves_zone(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        new_armor = state.create_card_instance("1-0-061", "P1")
        surprise_box = state.create_card_instance("1-0-057", "P1")
        entering = state.create_card_instance("1-0-001", "P1")
        intercept_card = state.create_card_instance("1-0-097", "P1")
        first_trigger_draw = state.create_card_instance("1-0-062", "P1")
        second_trigger_draw = state.create_card_instance("1-0-063", "P1")
        state.players["P1"].trigger_zone.cards.extend([new_armor.instance_id, surprise_box.instance_id])
        state.players["P1"].hand.add(entering.instance_id)
        state.players["P1"].deck.cards.extend([
            intercept_card.instance_id,
            first_trigger_draw.instance_id,
            second_trigger_draw.instance_id,
        ])
        state.players["P1"].current_cp = 1

        drive_unit(state, "P1", entering.instance_id)
        from tojs_reborn.engine.windows import process_windows_for_events

        process_windows_for_events(state, 1)

        activation_events = [event for event in state.event_store.events if event.type == "trigger_activated"]
        self.assertEqual(
            [event.source.card_no for event in activation_events],
            ["1-0-061", "1-0-057"],
        )
        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(
            set(state.players["P1"].discard_pile.cards),
            {new_armor.instance_id, surprise_box.instance_id},
        )
        self.assertEqual(
            state.players["P1"].hand.cards,
            [intercept_card.instance_id, first_trigger_draw.instance_id, second_trigger_draw.instance_id],
        )

    def test_new_armor_trigger_fires_and_draws_zero_when_no_intercept_in_deck(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        trigger_card = state.create_card_instance("1-0-061", "P1")
        entering = state.create_card_instance("1-0-001", "P1")
        non_intercept = state.create_card_instance("1-0-004", "P1")
        state.players["P1"].trigger_zone.add(trigger_card.instance_id)
        state.players["P1"].hand.add(entering.instance_id)
        state.players["P1"].deck.cards.append(non_intercept.instance_id)
        state.players["P1"].current_cp = 1

        drive_unit(state, "P1", entering.instance_id)
        from tojs_reborn.engine.windows import process_windows_for_events

        process_windows_for_events(state, 1)

        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [trigger_card.instance_id])
        self.assertEqual(state.players["P1"].hand.cards, [])
        cards_drawn = [event for event in state.event_store.events if event.type == "cards_drawn"][-1]
        self.assertEqual(cards_drawn.payload["count"], 0)
        self.assertEqual(state.players["P1"].deck.cards, [non_intercept.instance_id])

    def test_intercept_requires_cp_and_same_color_unit_to_activate(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        entering = state.create_card_instance("1-0-041", "P1")
        howling = state.create_card_instance("1-0-099", "P1")
        state.players["P1"].hand.add(entering.instance_id)
        state.players["P1"].trigger_zone.add(howling.instance_id)
        state.players["P1"].current_cp = 1

        drive_unit(state, "P1", entering.instance_id)
        from tojs_reborn.engine.windows import process_windows_for_events

        process_windows_for_events(state, 1)

        self.assertEqual(state.players["P1"].trigger_zone.cards, [howling.instance_id])
        self.assertNotIn("intercept_activated", [event.type for event in state.event_store.events])

    def test_intercept_requires_own_same_color_unit_to_activate(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        entering = state.create_card_instance("1-0-001", "P1")
        howling = state.create_card_instance("1-0-099", "P1")
        state.players["P1"].hand.add(entering.instance_id)
        state.players["P1"].trigger_zone.add(howling.instance_id)
        state.players["P1"].current_cp = 3

        drive_unit(state, "P1", entering.instance_id)
        from tojs_reborn.engine.windows import process_windows_for_events

        process_windows_for_events(state, 1)

        self.assertEqual(state.players["P1"].trigger_zone.cards, [howling.instance_id])
        self.assertNotIn("intercept_activated", [event.type for event in state.event_store.events])

    def test_intercept_window_activates_selected_card_then_closes_after_two_passes(self) -> None:
        catalog = dict(self.catalog)
        catalog["T-INT-001"] = draw_window_card("T-INT-001", "intercept", "INTERCEPT_ATTACK")
        state = create_game_state(catalog)
        state.turn_player_id = "P1"
        intercept_card = state.create_card_instance("T-INT-001", "P1")
        draw_target = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].trigger_zone.add(intercept_card.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)
        cause_event = state.event_store.append("unit_attacked", round_no=1, turn_no=1, actor_player_id="P1")
        used = set()

        def choose(player_id, actions):
            for action in actions:
                if action["type"] == "activate_intercept" and action["card_instance_id"] not in used:
                    used.add(action["card_instance_id"])
                    return action
            return actions[-1]

        activated_count = process_intercept_window(state, "attack", cause_event.event_no, choose)

        self.assertEqual(activated_count, 1)
        self.assertEqual(state.players["P1"].trigger_zone.cards, [])
        self.assertEqual(state.players["P1"].discard_pile.cards, [intercept_card.instance_id])
        self.assertEqual(state.players["P1"].hand.cards, [draw_target.instance_id])
        self.assertEqual(
            [event.type for event in state.event_store.events if event.type.startswith("intercept")],
            ["intercept_window_opened", "intercept_activated", "intercept_passed", "intercept_passed"],
        )

    def test_block_declared_resolves_block_bp_modifier_and_expires_at_turn_end(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        attacker_card = state.create_card_instance("1-0-001", "P1")
        blocker_card = state.create_card_instance("1-0-045", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        blocker = state.create_unit(blocker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(blocker.unit_id)
        before_bp = get_unit_bp(state, blocker)

        attack_unit(state, "P1", attacker.unit_id, blocker.unit_id)

        event_types = [event.type for event in state.event_store.events]
        self.assertIn("block_declared", event_types)
        self.assertIn("bp_modified", event_types)
        if blocker.unit_id in state.units:
            self.assertEqual(blocker.level, 2)
            self.assertEqual(state.card_instances[blocker.card_instance_id].level, 2)
            self.assertEqual(blocker.current_damage, 0)
            self.assertEqual(get_unit_bp(state, blocker), 9000)
            self.assertIn("unit_level_changed", event_types)
            self.assertIn("unit_damage_cleared", event_types)
            end_turn(state, "P1")
            self.assertEqual(get_unit_bp(state, blocker), before_bp + 1000)
            self.assertIn("modifier_expired", [event.type for event in state.event_store.events])

    def test_indomitable_keyword_recovers_exhausted_cat_at_turn_end(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        cat_card = state.create_card_instance("1-0-044", "P1")
        cat = state.create_unit(cat_card.instance_id)
        cat.exhausted = True
        state.players["P1"].battlefield.add(cat.unit_id)

        end_turn(state, "P1")

        self.assertFalse(cat.exhausted)
        self.assertEqual(cat.keywords, ["indomitable"])
        recover_events = [event for event in state.event_store.events if event.type == "unit_action_recovered"]
        self.assertEqual(recover_events[-1].payload["reason"], "keyword")
        self.assertEqual(recover_events[-1].payload["keyword"], "indomitable")

    def test_raimal_indomitable_keyword_recovers_exhausted_source_unit_at_turn_end(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        raimal_card = state.create_card_instance("1-0-021", "P1")
        raimal = state.create_unit(raimal_card.instance_id)
        raimal.exhausted = True
        state.players["P1"].battlefield.add(raimal.unit_id)

        end_turn(state, "P1")

        self.assertFalse(raimal.exhausted)
        self.assertEqual(raimal.keywords, ["indomitable"])
        recover_events = [event for event in state.event_store.events if event.type == "unit_action_recovered"]
        self.assertEqual(recover_events[-1].payload["reason"], "keyword")
        self.assertEqual(recover_events[-1].payload["keyword"], "indomitable")
        self.assertNotIn("1-0-021:a1", [event.source.ability_id for event in state.event_store.events if event.type == "ability_resolved"])

    def test_indomitable_keyword_is_granted_when_unit_enters(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        raimal_card = state.create_card_instance("1-0-021", "P1")
        state.players["P1"].hand.add(raimal_card.instance_id)
        state.players["P1"].current_cp = 10

        raimal = drive_unit(state, "P1", raimal_card.instance_id)

        self.assertEqual(raimal.keywords, ["indomitable"])
        keyword_events = [event for event in state.event_store.events if event.type == "keyword_granted"]
        self.assertEqual(keyword_events[-1].payload["keyword"], "indomitable")

    def test_hand_override_levels_card_and_level3_drive_resolves_self_oc_after_cip(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        target = state.create_card_instance("1-0-007", "P1")
        first_material = state.create_card_instance("1-0-007", "P1")
        second_material = state.create_card_instance("1-0-007", "P1")
        first_override_draw = state.create_card_instance("1-0-004", "P1")
        second_override_draw = state.create_card_instance("1-0-005", "P1")
        state.players["P1"].hand.add(target.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P1"].deck.cards.extend([first_override_draw.instance_id, second_override_draw.instance_id])
        state.players["P1"].current_cp = 10

        override_card(state, "P1", target.instance_id, first_material.instance_id)
        override_card(state, "P1", target.instance_id, second_material.instance_id)
        unit = drive_unit(state, "P1", target.instance_id)

        self.assertEqual(unit.level, 3)
        self.assertEqual(state.card_instances[target.instance_id].level, 3)
        self.assertIn(first_material.instance_id, state.players["P1"].discard_pile.cards)
        self.assertIn(second_material.instance_id, state.players["P1"].discard_pile.cards)
        self.assertEqual(state.players["P2"].life, 6)
        event_types = [event.type for event in state.event_store.events]
        self.assertLess(event_types.index("unit_entered"), event_types.index("unit_overclocked"))

    def test_hand_override_rejects_level_three_target(self) -> None:
        state = create_game_state(self.catalog)
        target = state.create_card_instance("1-0-031", "P1", level=3)
        material = state.create_card_instance("1-0-031", "P1")
        state.players["P1"].hand.add(target.instance_id)
        state.players["P1"].hand.add(material.instance_id)

        with self.assertRaisesRegex(ValueError, "already level 3"):
            override_card(state, "P1", target.instance_id, material.instance_id)

        self.assertEqual(state.players["P1"].hand.cards, [target.instance_id, material.instance_id])
        self.assertEqual(state.players["P1"].discard_pile.cards, [])

    def test_hand_override_draws_one_card_after_leveling(self) -> None:
        state = create_game_state(self.catalog)
        target = state.create_card_instance("1-0-031", "P1")
        material = state.create_card_instance("1-0-031", "P1")
        draw_target = state.create_card_instance("1-0-033", "P1")
        state.players["P1"].hand.add(target.instance_id)
        state.players["P1"].hand.add(material.instance_id)
        state.players["P1"].deck.cards.append(draw_target.instance_id)

        override_card(state, "P1", target.instance_id, material.instance_id)

        self.assertEqual(state.players["P1"].hand.cards, [target.instance_id, draw_target.instance_id])
        self.assertEqual(state.card_instances[target.instance_id].level, 2)
        self.assertEqual(state.players["P1"].discard_pile.cards, [material.instance_id])
        event_types = [event.type for event in state.event_store.events]
        self.assertEqual(event_types[-2:], ["card_moved", "cards_drawn"])
        self.assertLess(event_types.index("card_level_changed"), event_types.index("cards_drawn"))

    def test_hand_override_refreshes_empty_deck_for_reward_draw(self) -> None:
        state = create_game_state(self.catalog, seed=31)
        target = state.create_card_instance("1-0-031", "P1")
        material = state.create_card_instance("1-0-031", "P1")
        state.players["P1"].hand.add(target.instance_id)
        state.players["P1"].hand.add(material.instance_id)
        state.players["P1"].initial_deck_card_nos = ["1-0-033"]

        override_card(state, "P1", target.instance_id, material.instance_id)

        self.assertEqual(state.card_instances[target.instance_id].level, 2)
        self.assertEqual(state.players["P1"].discard_pile.cards, [])
        self.assertEqual(len(state.players["P1"].hand.cards), 2)
        drawn_card_instance_id = state.players["P1"].hand.cards[-1]
        self.assertNotEqual(drawn_card_instance_id, material.instance_id)
        self.assertEqual(state.card_instances[drawn_card_instance_id].card_no, "1-0-033")
        event_types = [event.type for event in state.event_store.events]
        self.assertIn("deck_refreshed", event_types)
        self.assertLess(event_types.index("deck_refreshed"), event_types.index("cards_drawn"))
        refresh_event = next(event for event in state.event_store.events if event.type == "deck_refreshed")
        self.assertEqual(refresh_event.payload["from_discard_card_instance_ids"], [material.instance_id])

    def test_bloodhound_level3_drive_resolves_self_oc_damage_to_rival_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        target = state.create_card_instance("1-0-001", "P1")
        first_material = state.create_card_instance("1-0-001", "P1")
        second_material = state.create_card_instance("1-0-001", "P1")
        rival_card = state.create_card_instance("1-0-004", "P2")
        rival = state.create_unit(rival_card.instance_id)
        state.players["P1"].hand.add(target.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P2"].battlefield.add(rival.unit_id)
        state.players["P1"].current_cp = 10

        override_card(state, "P1", target.instance_id, first_material.instance_id)
        override_card(state, "P1", target.instance_id, second_material.instance_id)
        drive_unit(state, "P1", target.instance_id)

        self.assertNotIn(rival.unit_id, state.units)
        self.assertIn(rival_card.instance_id, state.players["P2"].discard_pile.cards)
        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual(ability_events[-1].source.ability_id, "1-0-001:a1")
        damage_events = [event for event in state.event_store.events if event.type == "damage_dealt"]
        self.assertEqual(damage_events[-1].payload["amount"], 4000)

    def test_goliath_level3_drive_deals_one_life_damage_to_rival_player(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        target = state.create_card_instance("1-0-007", "P1")
        first_material = state.create_card_instance("1-0-007", "P1")
        second_material = state.create_card_instance("1-0-007", "P1")
        state.players["P1"].hand.add(target.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P1"].current_cp = 10

        override_card(state, "P1", target.instance_id, first_material.instance_id)
        override_card(state, "P1", target.instance_id, second_material.instance_id)
        goliath = drive_unit(state, "P1", target.instance_id)

        self.assertEqual(goliath.level, 3)
        self.assertEqual(state.players["P2"].life, 6)
        ability_events = [event for event in state.event_store.events if event.type == "ability_resolved"]
        self.assertEqual(ability_events[-1].source.ability_id, "1-0-007:a1")
        life_events = [event for event in state.event_store.events if event.type == "life_changed"]
        self.assertEqual(life_events[-1].payload["amount"], -1)
        self.assertEqual(life_events[-1].payload["reason"], "effect")

    def test_gigamamuto_indomitable_keyword_recovers_exhausted_source_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        mammoth_card = state.create_card_instance("1-0-048", "P1")
        mammoth = state.create_unit(mammoth_card.instance_id)
        mammoth.exhausted = True
        state.players["P1"].battlefield.add(mammoth.unit_id)

        end_turn(state, "P1")

        self.assertFalse(mammoth.exhausted)
        self.assertEqual(mammoth.keywords, ["indomitable"])
        recover_events = [event for event in state.event_store.events if event.type == "unit_action_recovered"]
        self.assertEqual(recover_events[-1].payload["reason"], "keyword")
        self.assertEqual(recover_events[-1].payload["keyword"], "indomitable")

    def test_legal_actions_include_drive_attack_set_trigger_and_override(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        state.turn_player_id = "P1"
        state.players["P1"].current_cp = 10
        unit_card = state.create_card_instance("1-0-001", "P1")
        same_card = state.create_card_instance("1-0-001", "P1")
        same_card_material = state.create_card_instance("1-0-001", "P1")
        trigger_card = state.create_card_instance("1-0-065", "P1")
        unit = state.create_unit(unit_card.instance_id)
        state.players["P1"].battlefield.add(unit.unit_id)
        state.players["P1"].hand.add(same_card.instance_id)
        state.players["P1"].hand.add(same_card_material.instance_id)
        state.players["P1"].hand.add(trigger_card.instance_id)

        action_types = {action["type"] for action in list_legal_actions(state, "P1")}

        self.assertIn("drive_unit", action_types)
        self.assertIn("attack", action_types)
        self.assertIn("set_trigger", action_types)
        self.assertIn("override_card", action_types)
        self.assertNotIn("overclock_unit", action_types)
        self.assertIn("pass", action_types)

    def test_legal_actions_include_evolve_drive_only_for_same_color_target(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        state.turn_player_id = "P1"
        state.players["P1"].current_cp = 10
        _yellow_card, yellow_unit = self._add_battlefield_unit(state, "P1", "1-0-021")
        _green_card, green_unit = self._add_battlefield_unit(state, "P1", "1-0-040")
        evolve_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(evolve_card.instance_id)

        actions = [
            action
            for action in list_legal_actions(state, "P1")
            if action["type"] == "drive_unit" and action["card_instance_id"] == evolve_card.instance_id
        ]

        self.assertEqual([action["evolve_target_unit_id"] for action in actions], [yellow_unit.unit_id])
        self.assertNotIn(green_unit.unit_id, [action.get("evolve_target_unit_id") for action in actions])

    def test_first_player_cannot_attack_on_first_turn(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 1
        state.turn_player_id = "P1"
        attacker_card = state.create_card_instance("1-0-001", "P1")
        attacker = state.create_unit(attacker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)

        actions = list_legal_actions(state, "P1")

        self.assertNotIn("attack", [action["type"] for action in actions])

    def test_attack_is_legal_after_first_player_first_turn(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 3
        state.turn_player_id = "P1"
        attacker_card = state.create_card_instance("1-0-001", "P1")
        attacker = state.create_unit(attacker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)

        actions = list_legal_actions(state, "P1")

        self.assertIn("attack", [action["type"] for action in actions])

    def test_second_player_can_attack_on_their_first_turn(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_no = 2
        state.turn_player_id = "P2"
        attacker_card = state.create_card_instance("1-0-001", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        state.players["P2"].battlefield.add(attacker.unit_id)

        actions = list_legal_actions(state, "P2")

        self.assertIn("attack", [action["type"] for action in actions])

    def test_block_actions_include_no_block_and_ready_blocker(self) -> None:
        state = create_game_state(self.catalog)
        attacker_card = state.create_card_instance("1-0-001", "P1")
        blocker_card = state.create_card_instance("1-0-001", "P2")
        attacker = state.create_unit(attacker_card.instance_id)
        blocker = state.create_unit(blocker_card.instance_id)
        state.players["P1"].battlefield.add(attacker.unit_id)
        state.players["P2"].battlefield.add(blocker.unit_id)

        actions = list_block_actions(state, "P2", attacker.unit_id)

        self.assertEqual(actions[0]["type"], "no_block")
        self.assertEqual(actions[0]["attacker_unit_id"], attacker.unit_id)
        self.assertIn("display", actions[0])
        block_actions = [action for action in actions if action["type"] == "block"]
        self.assertEqual(block_actions[0]["attacker_unit_id"], attacker.unit_id)
        self.assertEqual(block_actions[0]["blocker_unit_id"], blocker.unit_id)
        self.assertIn("unit", block_actions[0])


if __name__ == "__main__":
    unittest.main()
