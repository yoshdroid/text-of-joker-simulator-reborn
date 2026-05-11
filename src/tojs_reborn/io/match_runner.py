from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tojs_reborn.engine.actions import drive_unit, overclock_unit, override_card, set_trigger
from tojs_reborn.engine.combat import declare_attack, declare_block, resolve_unblocked_attack
from tojs_reborn.engine.legal_actions import list_block_actions, list_legal_actions
from tojs_reborn.engine.replay import build_replay_record, snapshot_initial_state, state_from_snapshot
from tojs_reborn.engine.rules import opponent_id
from tojs_reborn.engine.state import GameState
from tojs_reborn.engine.turn import end_turn, start_turn
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


@dataclass(frozen=True)
class MatchResult:
    winner_player_id: str | None
    reason: str
    turn_count: int


@dataclass
class MatchRunner:
    state: GameState
    players: dict[str, ActionPlayer]
    record_intents: bool = True
    intents: list[dict] = field(default_factory=list)
    _active_intent: dict | None = field(default=None, init=False, repr=False)

    def run_match(self, *, max_turns: int = 20, max_actions_per_turn: int = 20) -> MatchResult:
        self.state.event_store.append(
            "match_started",
            round_no=self.state.round_no,
            turn_no=self.state.turn_no,
            actor_player_id=None,
            payload={"seed": self.state.seed, "max_turns": max_turns, "max_actions_per_turn": max_actions_per_turn},
        )
        if self.record_intents:
            self.intents.append(
                {
                    "type": "match_started",
                    "seed": self.state.seed,
                    "max_turns": max_turns,
                    "max_actions_per_turn": max_actions_per_turn,
                }
            )

        player_turn_counts = {player_id: 0 for player_id in self.state.players}
        turns_started = 0
        while turns_started < max_turns:
            player_id = self.state.turn_player_id
            player_turn_counts[player_id] += 1
            turns_started += 1
            draw_count = _turn_draw_count(player_id, player_turn_counts[player_id])
            cp = _turn_cp(player_id, player_turn_counts[player_id])
            start_turn(self.state, player_id, draw_count=draw_count, cp=cp)
            if self.record_intents:
                self.intents.append(
                    {
                        "type": "start_turn",
                        "player_id": player_id,
                        "draw_count": draw_count,
                        "cp": cp,
                    }
                )

            result = self._life_zero_result(turns_started)
            if result is not None:
                return self._finish_match(result)

            actions_taken = 0
            while self.state.turn_player_id == player_id:
                if actions_taken >= max_actions_per_turn:
                    return self._finish_match(
                        MatchResult(
                            winner_player_id=_winner_by_life(self.state),
                            reason="max_actions_per_turn",
                            turn_count=turns_started,
                        )
                    )
                self.run_turn_action(player_id)
                actions_taken += 1
                result = self._life_zero_result(turns_started)
                if result is not None:
                    return self._finish_match(result)

        return self._finish_match(
            MatchResult(
                winner_player_id=_winner_by_life(self.state),
                reason="max_turns",
                turn_count=turns_started,
            )
        )

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
        player = self.players[player_id]
        response = player.choose_action(player_id, legal_actions)
        fallback_reason = getattr(player, "last_fallback_reason", None)
        if fallback_reason is not None:
            self.state.event_store.append(
                "player_response_fallback",
                round_no=self.state.round_no,
                turn_no=self.state.turn_no,
                actor_player_id=player_id,
                payload={"role": role, "reason": fallback_reason, "fallback": legal_actions[0]},
            )
            try:
                setattr(player, "last_fallback_reason", None)
            except AttributeError:
                pass
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

    def _life_zero_result(self, turn_count: int) -> MatchResult | None:
        defeated = [player_id for player_id, player in self.state.players.items() if player.life <= 0]
        if not defeated:
            return None
        if len(defeated) == len(self.state.players):
            return MatchResult(winner_player_id=None, reason="life_zero", turn_count=turn_count)
        return MatchResult(winner_player_id=opponent_id(defeated[0]), reason="life_zero", turn_count=turn_count)

    def _finish_match(self, result: MatchResult) -> MatchResult:
        self.state.event_store.append(
            "match_ended",
            round_no=self.state.round_no,
            turn_no=self.state.turn_no,
            actor_player_id=None,
            payload={
                "winner_player_id": result.winner_player_id,
                "reason": result.reason,
                "turn_count": result.turn_count,
            },
        )
        if self.record_intents:
            self.intents.append(
                {
                    "type": "match_ended",
                    "winner_player_id": result.winner_player_id,
                    "reason": result.reason,
                    "turn_count": result.turn_count,
                }
            )
        return result


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
        if intent["type"] == "match_started":
            state.event_store.append(
                "match_started",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=None,
                payload={
                    "seed": intent.get("seed", state.seed),
                    "max_turns": intent.get("max_turns"),
                    "max_actions_per_turn": intent.get("max_actions_per_turn"),
                },
            )
        elif intent["type"] == "start_turn":
            start_turn(
                state,
                intent["player_id"],
                draw_count=int(intent.get("draw_count", 1)),
                cp=int(intent.get("cp", 2)),
            )
        elif intent["type"] == "match_turn_action":
            scripted_player = ScriptedChoicePlayer(list(intent.get("choices", [])))
            runner = MatchRunner(
                state,
                players={"P1": scripted_player, "P2": scripted_player},
                record_intents=False,
            )
            runner.run_turn_action(intent["player_id"])
        elif intent["type"] == "match_ended":
            state.event_store.append(
                "match_ended",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=None,
                payload={
                    "winner_player_id": intent.get("winner_player_id"),
                    "reason": intent.get("reason"),
                    "turn_count": intent.get("turn_count"),
                },
            )
        else:
            raise ValueError(f"unknown match intent type: {intent['type']}")
    if state.event_store.to_list() != replay_record_data["events"]:
        raise AssertionError("match replay event log mismatch")
    return state


def snapshot_match_initial_state(state: GameState) -> dict:
    return snapshot_initial_state(state)


def _turn_cp(player_id: str, player_turn_count: int) -> int:
    if player_id == "P1":
        schedule = [2, 3, 4, 5, 6, 7]
    else:
        schedule = [3, 3, 4, 5, 6, 7]
    index = min(player_turn_count, len(schedule)) - 1
    return schedule[index]


def _turn_draw_count(player_id: str, player_turn_count: int) -> int:
    if player_id == "P1" and player_turn_count == 1:
        return 0
    return 2


def _winner_by_life(state: GameState) -> str | None:
    p1_life = state.players["P1"].life
    p2_life = state.players["P2"].life
    if p1_life == p2_life:
        return "P2"
    return "P1" if p1_life > p2_life else "P2"
