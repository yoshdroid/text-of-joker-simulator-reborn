from __future__ import annotations

from typing import Any

from .actions import drive_unit, override_card, set_trigger
from .combat import attack_player, attack_unit
from .state import CardDefinition, GameState, create_game_state
from .turn import end_turn, start_turn


def build_replay_record(
    state: GameState,
    *,
    initial_state: dict[str, Any] | None = None,
    intents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "engine_version": "reborn-v1-minimal",
        "seed": state.seed,
        "initial_state": initial_state,
        "intents": intents or [],
        "round_no": state.round_no,
        "turn_no": state.turn_no,
        "turn_player_id": state.turn_player_id,
        "events": state.event_store.to_list(),
        "final_state": state_digest(state),
    }


def verify_replay_record(state: GameState, replay_record: dict[str, Any]) -> bool:
    return state.event_store.to_list() == replay_record["events"] and state_digest(state) == replay_record["final_state"]


def replay_record(card_catalog: dict[str, CardDefinition], replay_record_data: dict[str, Any]) -> GameState:
    state = state_from_snapshot(
        card_catalog,
        replay_record_data["initial_state"],
        seed=int(replay_record_data.get("seed", 0)),
    )
    for intent in replay_record_data.get("intents", []):
        apply_intent(state, intent)
    if state.event_store.to_list() != replay_record_data["events"]:
        raise AssertionError("replay event log mismatch")
    if state_digest(state) != replay_record_data["final_state"]:
        raise AssertionError("replay final state mismatch")
    return state


def apply_intent(state: GameState, intent: dict[str, Any]) -> None:
    intent_type = intent["type"]
    player_id = intent.get("player_id")
    if intent_type == "start_turn":
        start_turn(state, player_id, draw_count=int(intent.get("draw_count", 1)), cp=int(intent.get("cp", 2)))
    elif intent_type == "end_turn":
        end_turn(state, player_id)
    elif intent_type == "drive_unit":
        drive_unit(state, player_id, intent["card_instance_id"])
    elif intent_type == "set_trigger":
        set_trigger(state, player_id, intent["card_instance_id"])
    elif intent_type == "override_card":
        override_card(state, player_id, intent["target_card_instance_id"], intent["material_card_instance_id"])
    elif intent_type == "overclock_unit":
        raise ValueError("overclock_unit intent is deprecated; use override_card in hand and drive_unit")
    elif intent_type == "attack_player":
        attack_player(state, player_id, intent["attacker_unit_id"])
    elif intent_type == "attack_unit":
        attack_unit(state, player_id, intent["attacker_unit_id"], intent["blocker_unit_id"])
    elif intent_type == "pass":
        return
    else:
        raise ValueError(f"unknown intent type: {intent_type}")


def snapshot_initial_state(state: GameState) -> dict[str, Any]:
    return {
        "round_no": state.round_no,
        "turn_no": state.turn_no,
        "turn_player_id": state.turn_player_id,
        "next_card_instance_no": state.next_card_instance_no,
        "next_unit_no": state.next_unit_no,
        "card_instances": {
            instance_id: {
                "card_no": instance.card_no,
                "owner_player_id": instance.owner_player_id,
                "level": instance.level,
            }
            for instance_id, instance in sorted(state.card_instances.items())
        },
        "players": {
            player_id: {
                "life": player.life,
                "current_cp": player.current_cp,
                "initial_deck_card_nos": list(player.initial_deck_card_nos),
                "deck": list(player.deck.cards),
                "hand": list(player.hand.cards),
                "battlefield": list(player.battlefield.units),
                "trigger_zone": list(player.trigger_zone.cards),
                "discard_pile": list(player.discard_pile.cards),
            }
            for player_id, player in state.players.items()
        },
        "units": {
            unit_id: {
                "card_instance_id": unit.card_instance_id,
                "card_no": unit.card_no,
                "owner_player_id": unit.owner_player_id,
                "level": unit.level,
                "exhausted": unit.exhausted,
                "current_damage": unit.current_damage,
                "base_bp_modifiers": list(unit.base_bp_modifiers),
                "bp_modifiers": list(unit.bp_modifiers),
                "stacked_card_instance_ids": list(unit.stacked_card_instance_ids),
            }
            for unit_id, unit in sorted(state.units.items())
        },
    }


def state_from_snapshot(
    card_catalog: dict[str, CardDefinition],
    snapshot: dict[str, Any],
    *,
    seed: int = 0,
) -> GameState:
    state = create_game_state(card_catalog, seed=seed)
    state.round_no = int(snapshot["round_no"])
    state.turn_no = int(snapshot["turn_no"])
    state.turn_player_id = snapshot["turn_player_id"]
    state.next_card_instance_no = int(snapshot["next_card_instance_no"])
    state.next_unit_no = int(snapshot["next_unit_no"])
    for instance_id, item in snapshot["card_instances"].items():
        instance = state.create_card_instance(item["card_no"], item["owner_player_id"], int(item.get("level", 1)))
        del state.card_instances[instance.instance_id]
        state.card_instances[instance_id] = instance.__class__(
            instance_id=instance_id,
            card_no=item["card_no"],
            owner_player_id=item["owner_player_id"],
            level=int(item.get("level", 1)),
        )
    state.next_card_instance_no = int(snapshot["next_card_instance_no"])
    for player_id, item in snapshot["players"].items():
        player = state.players[player_id]
        player.life = int(item["life"])
        player.current_cp = int(item["current_cp"])
        player.initial_deck_card_nos = list(item.get("initial_deck_card_nos", []))
        player.deck.cards = list(item["deck"])
        player.hand.cards = list(item["hand"])
        player.battlefield.units = list(item["battlefield"])
        player.trigger_zone.cards = list(item["trigger_zone"])
        player.discard_pile.cards = list(item["discard_pile"])
    for unit_id, item in snapshot["units"].items():
        unit = state.create_unit(item["card_instance_id"])
        del state.units[unit.unit_id]
        unit.unit_id = unit_id
        unit.level = int(item["level"])
        unit.exhausted = bool(item["exhausted"])
        unit.current_damage = int(item["current_damage"])
        unit.base_bp_modifiers = list(item.get("base_bp_modifiers", []))
        unit.bp_modifiers = list(item.get("bp_modifiers", []))
        unit.stacked_card_instance_ids = list(item.get("stacked_card_instance_ids", [item["card_instance_id"]]))
        state.units[unit_id] = unit
    state.next_unit_no = int(snapshot["next_unit_no"])
    return state


def state_digest(state: GameState) -> dict[str, Any]:
    players = {}
    for player_id, player in state.players.items():
        players[player_id] = {
            "life": player.life,
            "current_cp": player.current_cp,
            "initial_deck_card_nos": list(player.initial_deck_card_nos),
            "deck": list(player.deck.cards),
            "hand": list(player.hand.cards),
            "battlefield": list(player.battlefield.units),
            "trigger_zone": list(player.trigger_zone.cards),
            "discard_pile": list(player.discard_pile.cards),
        }
    units = {
        unit_id: {
            "card_instance_id": unit.card_instance_id,
            "card_no": unit.card_no,
            "owner_player_id": unit.owner_player_id,
            "level": unit.level,
            "exhausted": unit.exhausted,
            "current_damage": unit.current_damage,
            "base_bp_modifiers": list(unit.base_bp_modifiers),
            "bp_modifiers": list(unit.bp_modifiers),
            "stacked_card_instance_ids": list(unit.stacked_card_instance_ids),
        }
        for unit_id, unit in sorted(state.units.items())
    }
    return {
        "round_no": state.round_no,
        "turn_no": state.turn_no,
        "turn_player_id": state.turn_player_id,
        "card_catalog": {
            card_no: {
                "category": card.category,
                "color": card.color,
                "name": card.name,
                "cp": card.cp,
            }
            for card_no, card in sorted(state.card_catalog.items())
        },
        "card_instances": {
            instance_id: {
                "card_no": instance.card_no,
                "owner_player_id": instance.owner_player_id,
                "level": instance.level,
            }
            for instance_id, instance in sorted(state.card_instances.items())
        },
        "players": players,
        "units": units,
    }
