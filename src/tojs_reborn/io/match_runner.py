from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tojs_reborn.engine.actions import drive_unit, overclock_unit, override_card, set_trigger
from tojs_reborn.engine.combat import declare_attack, declare_block, resolve_unblocked_attack
from tojs_reborn.engine.legal_actions import list_block_actions, list_legal_actions
from tojs_reborn.engine.state import GameState
from tojs_reborn.engine.turn import end_turn


class ActionPlayer(Protocol):
    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        ...


@dataclass
class FirstLegalPlayer:
    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        for action in legal_actions:
            if action["type"] != "pass":
                return action
        return {"type": "pass"}


@dataclass
class MatchRunner:
    state: GameState
    players: dict[str, ActionPlayer]

    def run_turn_action(self, player_id: str) -> dict:
        legal_actions = list_legal_actions(self.state, player_id)
        selected = self.players[player_id].choose_action(player_id, legal_actions)
        if selected not in legal_actions:
            self.state.event_store.append(
                "invalid_response",
                round_no=self.state.round_no,
                turn_no=self.state.turn_no,
                actor_player_id=player_id,
                payload={"selected": selected, "fallback": legal_actions[0]},
            )
            selected = legal_actions[0]
        self.apply_action(player_id, selected)
        return selected

    def apply_action(self, player_id: str, action: dict) -> None:
        action_type = action["type"]
        if action_type == "drive_unit":
            drive_unit(self.state, player_id, action["card_instance_id"])
        elif action_type == "set_trigger":
            set_trigger(self.state, player_id, action["card_instance_id"])
        elif action_type == "override_card":
            override_card(self.state, player_id, action["target_card_instance_id"], action["material_card_instance_id"])
        elif action_type == "overclock_unit":
            overclock_unit(self.state, player_id, action["card_instance_id"], action["target_unit_id"])
        elif action_type == "attack":
            attack_event = declare_attack(self.state, player_id, action["attacker_unit_id"])
            defender_player_id = action["defender_player_id"]
            block_actions = list_block_actions(self.state, defender_player_id, action["attacker_unit_id"])
            selected_block = self.players[defender_player_id].choose_action(defender_player_id, block_actions)
            if selected_block not in block_actions:
                self.state.event_store.append(
                    "invalid_response",
                    round_no=self.state.round_no,
                    turn_no=self.state.turn_no,
                    actor_player_id=defender_player_id,
                    payload={"selected": selected_block, "fallback": block_actions[0]},
                )
                selected_block = block_actions[0]
            if selected_block["type"] == "block":
                declare_block(
                    self.state,
                    defender_player_id,
                    selected_block["blocker_unit_id"],
                    selected_block["attacker_unit_id"],
                    attack_event.event_no,
                )
            else:
                resolve_unblocked_attack(self.state, attack_event.event_no)
        elif action_type == "pass":
            end_turn(self.state, player_id)
        else:
            raise ValueError(f"unknown action type: {action_type}")
