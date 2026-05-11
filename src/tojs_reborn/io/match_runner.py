from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tojs_reborn.engine.actions import drive_unit, overclock_unit, override_card, set_trigger
from tojs_reborn.engine.combat import declare_attack, declare_block, resolve_unblocked_attack
from tojs_reborn.engine.legal_actions import list_block_actions, list_legal_actions
from tojs_reborn.engine.replay import build_replay_record, snapshot_initial_state, state_from_snapshot
from tojs_reborn.engine.state import GameState
from tojs_reborn.engine.turn import end_turn
from tojs_reborn.engine.windows import process_windows_for_events


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
    record_intents: bool = True
    intents: list[dict] = field(default_factory=list)
    _active_intent: dict | None = field(default=None, init=False, repr=False)

    def run_turn_action(self, player_id: str) -> dict:
        if self.record_intents:
            self._active_intent = {"type": "match_turn_action", "player_id": player_id, "choices": []}
        legal_actions = list_legal_actions(self.state, player_id)
        selected = self._choose_action(player_id, legal_actions, role="turn_action")
        try:
            self.apply_action(player_id, selected)
            return selected
        finally:
            if self.record_intents and self._active_intent is not None:
                self.intents.append(self._active_intent)
                self._active_intent = None

    def apply_action(self, player_id: str, action: dict) -> None:
        first_event_no = len(self.state.event_store.events) + 1
        action_type = action["type"]
        if action_type == "drive_unit":
            drive_unit(self.state, player_id, action["card_instance_id"])
            self._process_windows_from(first_event_no)
        elif action_type == "set_trigger":
            set_trigger(self.state, player_id, action["card_instance_id"])
            self._process_windows_from(first_event_no)
        elif action_type == "override_card":
            override_card(self.state, player_id, action["target_card_instance_id"], action["material_card_instance_id"])
            self._process_windows_from(first_event_no)
        elif action_type == "overclock_unit":
            overclock_unit(self.state, player_id, action["card_instance_id"], action["target_unit_id"])
            self._process_windows_from(first_event_no)
        elif action_type == "attack":
            attack_event = declare_attack(self.state, player_id, action["attacker_unit_id"])
            self._process_windows_from(attack_event.event_no)
            defender_player_id = action["defender_player_id"]
            block_actions = list_block_actions(self.state, defender_player_id, action["attacker_unit_id"])
            selected_block = self._choose_action(defender_player_id, block_actions, role="block_action")
            if selected_block["type"] == "block":
                block_first_event_no = len(self.state.event_store.events) + 1
                declare_block(
                    self.state,
                    defender_player_id,
                    selected_block["blocker_unit_id"],
                    selected_block["attacker_unit_id"],
                    attack_event.event_no,
                )
                self._process_windows_from(block_first_event_no)
            else:
                damage_first_event_no = len(self.state.event_store.events) + 1
                resolve_unblocked_attack(self.state, attack_event.event_no)
                self._process_windows_from(damage_first_event_no)
        elif action_type == "pass":
            end_turn(self.state, player_id)
            self._process_windows_from(first_event_no)
        else:
            raise ValueError(f"unknown action type: {action_type}")

    def _process_windows_from(self, first_event_no: int) -> None:
        process_windows_for_events(self.state, first_event_no, self._choose_window_action)

    def _choose_window_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        return self._choose_action(player_id, legal_actions, role="window_action")

    def _choose_action(self, player_id: str, legal_actions: list[dict], *, role: str) -> dict:
        response = self.players[player_id].choose_action(player_id, legal_actions)
        if self._active_intent is not None:
            self._active_intent["choices"].append(
                {
                    "player_id": player_id,
                    "role": role,
                    "response": response,
                }
            )
        if response not in legal_actions:
            self.state.event_store.append(
                "invalid_response",
                round_no=self.state.round_no,
                turn_no=self.state.turn_no,
                actor_player_id=player_id,
                payload={"selected": response, "fallback": legal_actions[0]},
            )
            return legal_actions[0]
        return response

    def build_replay_record(self, initial_state: dict | None = None) -> dict:
        return build_replay_record(
            self.state,
            initial_state=initial_state,
            intents=list(self.intents),
        )


@dataclass
class ScriptedChoicePlayer:
    choices: list[dict]
    index: int = 0

    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        if self.index >= len(self.choices):
            return legal_actions[0]
        choice = self.choices[self.index]
        self.index += 1
        return choice["response"]


def replay_match_record(card_catalog, replay_record_data: dict) -> GameState:
    state = state_from_snapshot(
        card_catalog,
        replay_record_data["initial_state"],
        seed=int(replay_record_data.get("seed", 0)),
    )
    for intent in replay_record_data.get("intents", []):
        if intent["type"] != "match_turn_action":
            raise ValueError(f"unknown match intent type: {intent['type']}")
        scripted_player = ScriptedChoicePlayer(list(intent.get("choices", [])))
        runner = MatchRunner(
            state,
            players={"P1": scripted_player, "P2": scripted_player},
            record_intents=False,
        )
        runner.run_turn_action(intent["player_id"])
    if state.event_store.to_list() != replay_record_data["events"]:
        raise AssertionError("match replay event log mismatch")
    return state


def snapshot_match_initial_state(state: GameState) -> dict:
    return snapshot_initial_state(state)
