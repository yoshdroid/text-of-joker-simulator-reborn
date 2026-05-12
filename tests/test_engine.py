import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from tojs_reborn.cardpool.normalizer import normalize_cardpool
from tojs_reborn.engine.actions import draw_cards, drive_unit, overclock_unit, override_card, set_trigger
from tojs_reborn.engine.combat import attack_player, attack_unit, declare_attack, destroy_lethal_units
from tojs_reborn.engine.events import EventStore
from tojs_reborn.engine.legal_actions import list_block_actions, list_legal_actions
from tojs_reborn.engine.replay import (
    build_replay_record,
    replay_record,
    snapshot_initial_state,
    verify_replay_record,
)
from tojs_reborn.engine.rules import get_unit_base_bp, get_unit_bp
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

    def test_draw_card_by_category_after_refresh_can_draw_zero_cards(self) -> None:
        state = create_game_state(self.catalog, seed=1)
        state.players["P1"].initial_deck_card_nos = ["1-0-001"]
        crow_card = state.create_card_instance("1-0-029", "P1")
        crow = state.create_unit(crow_card.instance_id)
        state.players["P1"].battlefield.add(crow.unit_id)
        state.turn_player_id = "P1"
        crow.current_damage = 1

        destroy_lethal_units(state, [crow], cause_event_no=0)

        cards_drawn = [event for event in state.event_store.events if event.type == "cards_drawn"][-1]
        self.assertEqual(cards_drawn.payload["count"], 0)
        self.assertIn("deck_refreshed", [event.type for event in state.event_store.events])

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

        drive_unit(state, "P1", entering_card.instance_id)

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
        ready_card = state.create_card_instance("1-0-040", "P2")
        ready_unit = state.create_unit(ready_card.instance_id)
        state.players["P2"].battlefield.add(ready_unit.unit_id)
        entering_card = state.create_card_instance("1-0-024", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        drive_unit(state, "P1", entering_card.instance_id)

        self.assertIn("ability_resolved", [event.type for event in state.event_store.events])
        self.assertIn("effect_fizzled", [event.type for event in state.event_store.events])
        self.assertNotIn("damage_dealt", [event.type for event in state.event_store.events])

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

        bishamon = drive_unit(state, "P1", entering_card.instance_id)

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
        entering_card = state.create_card_instance("1-0-026", "P1")
        state.players["P1"].hand.add(entering_card.instance_id)
        state.players["P1"].current_cp = 10

        bishamon = drive_unit(state, "P1", entering_card.instance_id)

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
        draw_one = state.create_card_instance("1-0-004", "P1")
        draw_two = state.create_card_instance("1-0-005", "P1")
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(target_card.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)
        state.players["P1"].hand.add(first_cost.instance_id)
        state.players["P1"].hand.add(second_cost.instance_id)
        state.players["P1"].deck.cards.extend([draw_one.instance_id, draw_two.instance_id])

        def choose_cost(_state, _source_unit, _ability, _request_event, _step, _legal_choices):
            return {"card_instance_ids": [first_cost.instance_id, second_cost.instance_id]}

        override_card(state, "P1", target_card.instance_id, first_material.instance_id)
        override_card(state, "P1", target_card.instance_id, second_material.instance_id)
        drive_unit(state, "P1", target_card.instance_id, ability_cost_choice=choose_cost)

        self.assertEqual(
            set(state.players["P1"].discard_pile.cards),
            {first_material.instance_id, second_material.instance_id, first_cost.instance_id, second_cost.instance_id},
        )
        self.assertEqual(state.players["P1"].hand.cards, [draw_one.instance_id, draw_two.instance_id])
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

        self.assertEqual(get_unit_base_bp(state, rival_target), before_base_bp - 3)
        self.assertEqual(get_unit_bp(state, rival_target), before_base_bp - 3)
        self.assertEqual(rival_target.base_bp_modifiers[-1]["duration"], "permanent")
        self.assertIn("base_bp_modified", [event.type for event in state.event_store.events])

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
        state.players["P1"].current_cp = 10
        state.players["P1"].hand.add(lina.instance_id)
        state.players["P1"].hand.add(first_material.instance_id)
        state.players["P1"].hand.add(second_material.instance_id)

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

    def test_replay_record_verifies_event_log_and_final_state(self) -> None:
        state = create_game_state(self.catalog)
        card = state.create_card_instance("1-0-001", "P1")
        state.players["P1"].deck.cards.append(card.instance_id)

        draw_cards(state, "P1", 1)
        replay_record = build_replay_record(state)

        self.assertTrue(verify_replay_record(state, replay_record))
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
        mummy.current_damage = 1

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

    def test_trigger_intercept_window_lists_public_candidates(self) -> None:
        state = create_game_state(self.catalog)
        trigger_card = state.create_card_instance("1-0-065", "P1")
        state.players["P1"].trigger_zone.add(trigger_card.instance_id)

        window = list_trigger_intercept_window(state, "P1", window="attack", cause_event_no=1)

        self.assertEqual(window["pass_action"]["type"], "pass_window")
        self.assertEqual(window["pass_action"]["window"], "attack")
        self.assertIn("display", window["pass_action"])
        self.assertEqual(window["candidates"][0]["card_instance_id"], trigger_card.instance_id)

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
            self.assertEqual(get_unit_bp(state, blocker), before_bp + 2000)
            end_turn(state, "P1")
            self.assertEqual(get_unit_bp(state, blocker), before_bp)
            self.assertIn("modifier_expired", [event.type for event in state.event_store.events])

    def test_turn_end_ability_recovers_exhausted_source_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        cat_card = state.create_card_instance("1-0-044", "P1")
        cat = state.create_unit(cat_card.instance_id)
        cat.exhausted = True
        state.players["P1"].battlefield.add(cat.unit_id)

        end_turn(state, "P1")

        self.assertFalse(cat.exhausted)
        self.assertEqual(
            [event.source.ability_id for event in state.event_store.events if event.type == "ability_resolved"],
            ["1-0-044:a1"],
        )

    def test_hand_override_levels_card_and_level3_drive_resolves_self_oc_after_cip(self) -> None:
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
        unit = drive_unit(state, "P1", target.instance_id)

        self.assertEqual(unit.level, 3)
        self.assertEqual(state.card_instances[target.instance_id].level, 3)
        self.assertIn(first_material.instance_id, state.players["P1"].discard_pile.cards)
        self.assertIn(second_material.instance_id, state.players["P1"].discard_pile.cards)
        self.assertEqual(state.players["P2"].life, 6)
        event_types = [event.type for event in state.event_store.events]
        self.assertLess(event_types.index("unit_entered"), event_types.index("unit_overclocked"))

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

    def test_gigamamuto_turn_end_ability_recovers_exhausted_source_unit(self) -> None:
        state = create_game_state(self.catalog)
        state.turn_player_id = "P1"
        mammoth_card = state.create_card_instance("1-0-048", "P1")
        mammoth = state.create_unit(mammoth_card.instance_id)
        mammoth.exhausted = True
        state.players["P1"].battlefield.add(mammoth.unit_id)

        end_turn(state, "P1")

        self.assertFalse(mammoth.exhausted)
        self.assertEqual(
            [event.source.ability_id for event in state.event_store.events if event.type == "ability_resolved"],
            ["1-0-048:a1"],
        )

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
