from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Protocol

from tojs_reborn.engine.actions import drive_unit, override_card, set_trigger
from tojs_reborn.engine.combat import attack_bypasses_block, declare_attack, declare_block, resolve_unblocked_attack
from tojs_reborn.engine.integrity import assert_game_state_integrity
from tojs_reborn.engine.joker import play_joker, try_grant_joker
from tojs_reborn.engine.legal_actions import list_block_actions, list_legal_actions
from tojs_reborn.engine.replay import build_replay_record, snapshot_initial_state, state_from_snapshot
from tojs_reborn.engine.rules import opponent_id, turn_cp_for
from tojs_reborn.engine.state import AbilityDefinition, GameState, UnitState
from tojs_reborn.engine.turn import end_turn, start_turn
from tojs_reborn.engine.windows import process_intercept_window, process_windows_for_events


class ActionPlayer(Protocol):
    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        ...


@dataclass
class FirstLegalPlayer:
    def choose_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        for action in legal_actions:
            if action["type"] != "pass":
                return action
        return legal_actions[0]


@dataclass(frozen=True)
class MatchResult:
    winner_player_id: str | None
    reason: str
    turn_count: int
    error_player_id: str | None = None


@dataclass
class MatchRunner:
    state: GameState
    players: dict[str, ActionPlayer]
    record_intents: bool = True
    check_integrity: bool = False
    intents: list[dict] = field(default_factory=list)
    _active_intent: dict | None = field(default=None, init=False, repr=False)
    _fallback_counts: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _max_fallbacks_per_player: int = field(default=3, init=False, repr=False)
    _player_error_player_id: str | None = field(default=None, init=False, repr=False)
    _published_event_count: int = field(default=0, init=False, repr=False)

    def run_match(
        self,
        *,
        max_turns: int = 20,
        max_actions_per_turn: int = 20,
        max_mulligans: int = 5,
        max_fallbacks_per_player: int = 3,
        event_delay_seconds: float = 0.0,
    ) -> MatchResult:
        self._max_fallbacks_per_player = max_fallbacks_per_player
        self.state.event_store.append(
            "match_started",
            round_no=self.state.round_no,
            turn_no=self.state.turn_no,
            actor_player_id=None,
            payload={
                "seed": self.state.seed,
                "max_turns": max_turns,
                "max_actions_per_turn": max_actions_per_turn,
                "max_mulligans": max_mulligans,
                "max_fallbacks_per_player": max_fallbacks_per_player,
            },
        )
        self._assert_integrity()
        self._publish_event_updates(event_delay_seconds=event_delay_seconds)
        if self.record_intents:
            self.intents.append(
                {
                    "type": "match_started",
                    "seed": self.state.seed,
                    "max_turns": max_turns,
                    "max_actions_per_turn": max_actions_per_turn,
                    "max_mulligans": max_mulligans,
                    "max_fallbacks_per_player": max_fallbacks_per_player,
                }
            )
        self.run_mulligan_phase(max_mulligans=max_mulligans)
        self._assert_integrity()
        self._publish_event_updates(event_delay_seconds=event_delay_seconds)
        result = self._player_error_result(0)
        if result is not None:
            return self._finish_match(result, event_delay_seconds=event_delay_seconds)

        player_turn_counts = {player_id: 0 for player_id in self.state.players}
        turns_started = 0
        while turns_started < max_turns:
            player_id = self.state.turn_player_id
            player_turn_counts[player_id] += 1
            turns_started += 1
            draw_count = _turn_draw_count(player_id, player_turn_counts[player_id])
            cp = _turn_cp(player_id, player_turn_counts[player_id])
            start_turn(self.state, player_id, draw_count=draw_count, cp=cp)
            self._assert_integrity()
            self._publish_event_updates(event_delay_seconds=event_delay_seconds)
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
                return self._finish_match(result, event_delay_seconds=event_delay_seconds)

            actions_taken = 0
            while self.state.turn_player_id == player_id:
                if actions_taken >= max_actions_per_turn:
                    return self._finish_match(
                        MatchResult(
                            winner_player_id=_winner_by_life(self.state),
                            reason="max_actions_per_turn",
                            turn_count=turns_started,
                        ),
                        event_delay_seconds=event_delay_seconds,
                    )
                self.run_turn_action(player_id)
                self._assert_integrity()
                self._publish_event_updates(event_delay_seconds=event_delay_seconds)
                actions_taken += 1
                result = self._player_error_result(turns_started)
                if result is not None:
                    return self._finish_match(result, event_delay_seconds=event_delay_seconds)
                result = self._life_zero_result(turns_started)
                if result is not None:
                    return self._finish_match(result, event_delay_seconds=event_delay_seconds)

        self._restore_final_turn_end_time_if_needed()
        return self._finish_match(
            MatchResult(
                winner_player_id=_winner_by_life(self.state),
                reason="max_turns",
                turn_count=turns_started,
            ),
            event_delay_seconds=event_delay_seconds,
        )

    def run_turn_action(self, player_id: str) -> dict:
        if self.record_intents:
            self._active_intent = {"type": "match_turn_action", "player_id": player_id, "choices": []}
        try_grant_joker(self.state, player_id)
        legal_actions = list_legal_actions(self.state, player_id)
        selected = self._choose_action(player_id, legal_actions, role="turn_action")
        try:
            self.apply_action(player_id, selected)
            return selected
        finally:
            if self.record_intents and self._active_intent is not None:
                self.intents.append(self._active_intent)
                self._active_intent = None

    def run_mulligan_phase(self, *, max_mulligans: int = 5) -> None:
        for player_id in ("P1", "P2"):
            for attempt in range(1, max_mulligans + 1):
                do_mulligan = self._choose_mulligan(player_id, attempt)
                if not do_mulligan:
                    break
                payload = _perform_mulligan_on_state(self.state, player_id, attempt)
                if self.record_intents and self.intents and self.intents[-1].get("type") == "mulligan":
                    self.intents[-1]["result"] = payload

    def _choose_mulligan(self, player_id: str, attempt: int) -> bool:
        player = self.players[player_id]
        self.state.event_store.append(
            "mulligan_requested",
            round_no=self.state.round_no,
            turn_no=self.state.turn_no,
            actor_player_id=player_id,
            payload={"attempt": attempt},
        )
        choose_with_state = getattr(player, "choose_mulligan_with_state", None)
        if callable(choose_with_state):
            do_mulligan = bool(choose_with_state(player_id, state=self.state))
        else:
            choose = getattr(player, "choose_mulligan", None)
            do_mulligan = bool(choose(player_id)) if callable(choose) else False
        fallback_reason = getattr(player, "last_fallback_reason", None)
        if fallback_reason is not None:
            self._record_player_response_fallback(
                player_id,
                role="mulligan",
                reason=fallback_reason,
                fallback=False,
            )
            try:
                setattr(player, "last_fallback_reason", None)
            except AttributeError:
                pass
        self.state.event_store.append(
            "mulligan_selected",
            round_no=self.state.round_no,
            turn_no=self.state.turn_no,
            actor_player_id=player_id,
            payload={"attempt": attempt, "do_mulligan": do_mulligan},
        )
        if self.record_intents:
            self.intents.append(
                {
                    "type": "mulligan",
                    "player_id": player_id,
                    "attempt": attempt,
                    "do_mulligan": do_mulligan,
                }
            )
        return do_mulligan

    def apply_action(self, player_id: str, action: dict) -> None:
        first_event_no = len(self.state.event_store.events) + 1
        action_type = action["type"]
        if action_type == "drive_unit":
            drive_unit(
                self.state,
                player_id,
                action["card_instance_id"],
                self._choose_optional_ability,
                self._choose_ability_cost,
                evolve_target_unit_id=action.get("evolve_target_unit_id"),
            )
            self._process_windows_from(first_event_no)
        elif action_type == "set_trigger":
            set_trigger(self.state, player_id, action["card_instance_id"])
            self._process_windows_from(first_event_no)
        elif action_type == "override_card":
            override_card(self.state, player_id, action["target_card_instance_id"], action["material_card_instance_id"])
            self._process_windows_from(first_event_no)
        elif action_type == "play_joker":
            play_joker(self.state, player_id, action["card_instance_id"])
            self._process_windows_from(first_event_no)
        elif action_type == "attack":
            attack_event = declare_attack(
                self.state,
                player_id,
                action["attacker_unit_id"],
                self._choose_optional_ability,
                self._choose_ability_cost,
            )
            self._process_windows_from(attack_event.event_no)
            if attack_bypasses_block(self.state, action["attacker_unit_id"]):
                damage_first_event_no = len(self.state.event_store.events) + 1
                resolve_unblocked_attack(self.state, attack_event.event_no)
                self._process_windows_from(damage_first_event_no)
                return
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
                    self._choose_optional_ability,
                    self._choose_ability_cost,
                    self._process_battle_window,
                )
                self._process_windows_from(block_first_event_no)
            else:
                damage_first_event_no = len(self.state.event_store.events) + 1
                resolve_unblocked_attack(self.state, attack_event.event_no)
                self._process_windows_from(damage_first_event_no)
        elif action_type == "pass":
            end_turn(self.state, player_id, self._choose_optional_ability, self._choose_ability_cost)
            self._process_windows_from(first_event_no)
        else:
            raise ValueError(f"unknown action type: {action_type}")

    def _process_windows_from(self, first_event_no: int) -> None:
        process_windows_for_events(self.state, first_event_no, self._choose_window_action)

    def _process_battle_window(self, state: GameState, battle_event_no: int) -> None:
        process_intercept_window(state, "battle", battle_event_no, self._choose_window_action)

    def _choose_window_action(self, player_id: str, legal_actions: list[dict]) -> dict:
        return self._choose_action(player_id, legal_actions, role="window_action")

    def _choose_optional_ability(
        self,
        state: GameState,
        source_unit: UnitState,
        ability: AbilityDefinition,
        request_event,
    ) -> bool:
        legal_choices = [
            {"type": "pass_ability", "ability_id": ability.ability_id},
            {"type": "use_ability", "ability_id": ability.ability_id},
        ]
        selected = self._choose_choice(
            source_unit.owner_player_id,
            request_id=f"optional:{request_event.event_no}:{ability.ability_id}",
            choice={
                "type": "optional_ability",
                "ability_id": ability.ability_id,
                "source_unit_id": source_unit.unit_id or None,
                "source_card_instance_id": source_unit.card_instance_id,
            },
            legal_choices=legal_choices,
            role="optional_ability",
        )
        return selected["type"] == "use_ability"

    def _choose_ability_cost(
        self,
        state: GameState,
        source_unit: UnitState,
        ability: AbilityDefinition,
        request_event,
        step: dict,
        legal_choices: list[dict],
    ) -> dict:
        selected = self._choose_choice(
            source_unit.owner_player_id,
            request_id=f"cost:{request_event.event_no}:{ability.ability_id}",
            choice={
                "type": "cost_payment",
                "effect": step.get("effect"),
                "ability_id": ability.ability_id,
                "source_unit_id": source_unit.unit_id or None,
                "source_card_instance_id": source_unit.card_instance_id,
                "count": int(step.get("count", 1)),
            },
            legal_choices=legal_choices,
            role="cost_payment",
        )
        return selected

    def _choose_action(self, player_id: str, legal_actions: list[dict], *, role: str) -> dict:
        player = self.players[player_id]
        choose_with_state = getattr(player, "choose_action_with_state", None)
        if callable(choose_with_state):
            request_context = _request_context_from_role(role, legal_actions)
            if _accepts_request_context(choose_with_state):
                response = choose_with_state(
                    player_id,
                    legal_actions,
                    state=self.state,
                    request_context=request_context,
                )
            else:
                response = choose_with_state(player_id, legal_actions, state=self.state)
        else:
            response = player.choose_action(player_id, legal_actions)
        fallback_reason = getattr(player, "last_fallback_reason", None)
        if fallback_reason is not None:
            self._record_player_response_fallback(
                player_id,
                role=role,
                reason=fallback_reason,
                fallback=legal_actions[0],
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
                    "legal_actions": list(legal_actions),
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

    def _choose_choice(
        self,
        player_id: str,
        *,
        request_id: str,
        choice: dict,
        legal_choices: list[dict],
        role: str,
    ) -> dict:
        player = self.players[player_id]
        choose_with_state = getattr(player, "choose_choice_with_state", None)
        if callable(choose_with_state):
            response = choose_with_state(
                player_id,
                request_id=request_id,
                choice=choice,
                legal_choices=legal_choices,
                state=self.state,
            )
        else:
            choose = getattr(player, "choose_choice", None)
            if callable(choose):
                response = choose(player_id, request_id=request_id, choice=choice, legal_choices=legal_choices)
            else:
                response = legal_choices[0]
        fallback_reason = getattr(player, "last_fallback_reason", None)
        if fallback_reason is not None:
            self._record_player_response_fallback(
                player_id,
                role=role,
                reason=fallback_reason,
                fallback=legal_choices[0],
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
        if response not in legal_choices:
            if choice.get("type") == "cost_payment" and _is_cost_payment_response_valid(response, legal_choices):
                return response
            self.state.event_store.append(
                "invalid_response",
                round_no=self.state.round_no,
                turn_no=self.state.turn_no,
                actor_player_id=player_id,
                payload={"selected": response, "fallback": legal_choices[0], "role": role},
            )
            return legal_choices[0]
        return response

    def _record_player_response_fallback(self, player_id: str, *, role: str, reason: str, fallback) -> None:
        count = self._fallback_counts.get(player_id, 0) + 1
        self._fallback_counts[player_id] = count
        self.state.event_store.append(
            "player_response_fallback",
            round_no=self.state.round_no,
            turn_no=self.state.turn_no,
            actor_player_id=player_id,
            payload={
                "role": role,
                "reason": reason,
                "fallback": fallback,
                "fallback_count": count,
                "max_fallbacks_per_player": self._max_fallbacks_per_player,
            },
        )
        if count >= self._max_fallbacks_per_player and self._player_error_player_id is None:
            self._player_error_player_id = player_id

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

    def _finish_match(self, result: MatchResult, *, event_delay_seconds: float = 0.0) -> MatchResult:
        self.state.event_store.append(
            "match_ended",
            round_no=self.state.round_no,
            turn_no=self.state.turn_no,
            actor_player_id=None,
            payload={
                "winner_player_id": result.winner_player_id,
                "reason": result.reason,
                "turn_count": result.turn_count,
                "error_player_id": result.error_player_id,
            },
        )
        if self.record_intents:
            self.intents.append(
                {
                    "type": "match_ended",
                    "winner_player_id": result.winner_player_id,
                    "reason": result.reason,
                    "turn_count": result.turn_count,
                    "error_player_id": result.error_player_id,
                }
            )
        self._assert_integrity()
        self._publish_event_updates(event_delay_seconds=event_delay_seconds)
        return result

    def _player_error_result(self, turn_count: int) -> MatchResult | None:
        if self._player_error_player_id is None:
            return None
        return MatchResult(
            winner_player_id=opponent_id(self._player_error_player_id),
            reason="player_error",
            turn_count=turn_count,
            error_player_id=self._player_error_player_id,
        )

    def _publish_event_updates(self, *, event_delay_seconds: float) -> None:
        while self._published_event_count < len(self.state.event_store.events):
            event = self.state.event_store.events[self._published_event_count]
            event_data = event.to_dict()
            for player_id, player in self.players.items():
                send_state_update = getattr(player, "send_state_update", None)
                if callable(send_state_update):
                    send_state_update(
                        player_id,
                        state=self.state,
                        request_id=f"{player_id}:event:{event.event_no}",
                        event=event_data,
                    )
            self._published_event_count += 1
            if event_delay_seconds > 0:
                time.sleep(event_delay_seconds)

    def _assert_integrity(self) -> None:
        if self.check_integrity:
            assert_game_state_integrity(self.state)

    def _restore_final_turn_end_time_if_needed(self) -> None:
        if not self.state.event_store.events:
            return
        last_event = next((event for event in reversed(self.state.event_store.events) if event.type == "turn_ended"), None)
        if last_event is None:
            return
        if last_event.type != "turn_ended" or last_event.actor_player_id != "P2":
            return
        self.state.round_no = last_event.round_no
        self.state.turn_no = last_event.turn_no
        self.state.turn_player_id = last_event.actor_player_id


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

    def choose_choice(
        self,
        player_id: str,
        *,
        request_id: str,
        choice: dict,
        legal_choices: list[dict],
    ) -> dict:
        if self.index >= len(self.choices):
            return legal_choices[0]
        scripted_choice = self.choices[self.index]
        self.index += 1
        return scripted_choice["response"]


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
                    "max_mulligans": intent.get("max_mulligans"),
                    "max_fallbacks_per_player": intent.get("max_fallbacks_per_player"),
                },
            )
        elif intent["type"] == "mulligan":
            state.event_store.append(
                "mulligan_requested",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=intent["player_id"],
                payload={"attempt": intent["attempt"]},
            )
            state.event_store.append(
                "mulligan_selected",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=intent["player_id"],
                payload={"attempt": intent["attempt"], "do_mulligan": bool(intent.get("do_mulligan", False))},
            )
            if intent.get("do_mulligan", False):
                _apply_recorded_mulligan_result(state, intent["player_id"], intent["result"])
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
            expected_event_index = len(state.event_store.events)
            expected_events = replay_record_data.get("events", [])
            if expected_event_index < len(expected_events):
                expected_event = expected_events[expected_event_index]
                if expected_event.get("type") == "match_ended":
                    state.round_no = int(expected_event.get("round_no", state.round_no))
                    state.turn_no = int(expected_event.get("turn_no", state.turn_no))
                    final_state = replay_record_data.get("final_state") or {}
                    final_turn_player_id = final_state.get("turn_player_id")
                    if isinstance(final_turn_player_id, str):
                        state.turn_player_id = final_turn_player_id
            state.event_store.append(
                "match_ended",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=None,
                payload={
                    "winner_player_id": intent.get("winner_player_id"),
                    "reason": intent.get("reason"),
                    "turn_count": intent.get("turn_count"),
                    "error_player_id": intent.get("error_player_id"),
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
    return turn_cp_for(player_id, player_turn_count)


def _turn_draw_count(player_id: str, player_turn_count: int) -> int:
    if player_id == "P1" and player_turn_count == 1:
        return 0
    return 2


def _accepts_request_context(callable_object) -> bool:
    try:
        parameters = inspect.signature(callable_object).parameters
    except (TypeError, ValueError):
        return False
    return "request_context" in parameters


def _request_context_from_role(role: str, legal_actions: list[dict]) -> dict:
    if role == "block_action":
        return {"kind": "block_action", "cause_event_no": _first_value(legal_actions, "cause_event_no"), "window": None}
    if role == "window_action":
        window = _first_value(legal_actions, "window")
        cause_event_no = _first_value(legal_actions, "cause_event_no")
        action_types = {action.get("type") for action in legal_actions}
        if "activate_intercept" in action_types or "pass_window" in action_types:
            return {"kind": "intercept_window", "cause_event_no": cause_event_no, "window": window}
        if "activate_trigger" in action_types:
            return {"kind": "trigger_window", "cause_event_no": cause_event_no, "window": window}
        return {"kind": "window_action", "cause_event_no": cause_event_no, "window": window}
    return {"kind": "turn_action", "cause_event_no": None, "window": None}


def _first_value(actions: list[dict], key: str):
    for action in actions:
        if key in action:
            return action[key]
    return None


def _is_cost_payment_response_valid(response: dict, legal_choices: list[dict]) -> bool:
    legal_ids = {choice.get("card_instance_id") for choice in legal_choices}
    if isinstance(response.get("card_instance_id"), str):
        selected_ids = [response["card_instance_id"]]
    elif isinstance(response.get("card_instance_ids"), list):
        selected_ids = [card_id for card_id in response["card_instance_ids"] if isinstance(card_id, str)]
    else:
        return False
    return bool(selected_ids) and len(selected_ids) == len(set(selected_ids)) and all(card_id in legal_ids for card_id in selected_ids)


def _perform_mulligan_on_state(state: GameState, player_id: str, attempt: int) -> dict:
    player = state.players[player_id]
    hand_size = len(player.hand.cards)
    returned_card_instance_ids = list(player.hand.cards)
    player.hand.cards.clear()
    player.deck.cards.extend(returned_card_instance_ids)
    state.rng.shuffle(player.deck.cards)
    deck_card_instance_ids_after_shuffle = list(player.deck.cards)
    drawn_card_instance_ids = []
    for _ in range(hand_size):
        card_instance_id = player.deck.draw_top()
        if card_instance_id is None:
            break
        player.hand.add(card_instance_id)
        drawn_card_instance_ids.append(card_instance_id)
    payload = {
        "attempt": attempt,
        "returned_card_instance_ids": returned_card_instance_ids,
        "deck_card_instance_ids_after_shuffle": deck_card_instance_ids_after_shuffle,
        "drawn_card_instance_ids": drawn_card_instance_ids,
        "hand_card_instance_ids": list(player.hand.cards),
        "deck_card_instance_ids": list(player.deck.cards),
    }
    state.event_store.append(
        "deck_shuffled",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        payload={
            "reason": "mulligan",
            "attempt": attempt,
            "deck_card_instance_ids": deck_card_instance_ids_after_shuffle,
        },
    )
    state.event_store.append(
        "mulligan_performed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        payload=payload,
    )
    return payload


def _apply_recorded_mulligan_result(state: GameState, player_id: str, payload: dict) -> None:
    player = state.players[player_id]
    player.hand.cards = list(payload["hand_card_instance_ids"])
    player.deck.cards = list(payload["deck_card_instance_ids"])
    state.event_store.append(
        "deck_shuffled",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        payload={
            "reason": "mulligan",
            "attempt": payload["attempt"],
            "deck_card_instance_ids": list(payload["deck_card_instance_ids_after_shuffle"]),
        },
    )
    state.event_store.append(
        "mulligan_performed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        payload=dict(payload),
    )


def _winner_by_life(state: GameState) -> str | None:
    p1_life = state.players["P1"].life
    p2_life = state.players["P2"].life
    if p1_life == p2_life:
        return "P2"
    return "P1" if p1_life > p2_life else "P2"
