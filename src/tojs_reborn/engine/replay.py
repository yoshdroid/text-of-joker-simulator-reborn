from __future__ import annotations

from typing import Any

from .state import GameState


def build_replay_record(state: GameState) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "engine_version": "reborn-v1-minimal",
        "seed": state.seed,
        "round_no": state.round_no,
        "turn_no": state.turn_no,
        "turn_player_id": state.turn_player_id,
        "events": state.event_store.to_list(),
        "final_state": state_digest(state),
    }


def verify_replay_record(state: GameState, replay_record: dict[str, Any]) -> bool:
    return state.event_store.to_list() == replay_record["events"] and state_digest(state) == replay_record["final_state"]


def state_digest(state: GameState) -> dict[str, Any]:
    players = {}
    for player_id, player in state.players.items():
        players[player_id] = {
            "life": player.life,
            "current_cp": player.current_cp,
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
            "bp_modifiers": list(unit.bp_modifiers),
        }
        for unit_id, unit in sorted(state.units.items())
    }
    return {
        "round_no": state.round_no,
        "turn_no": state.turn_no,
        "turn_player_id": state.turn_player_id,
        "players": players,
        "units": units,
    }
