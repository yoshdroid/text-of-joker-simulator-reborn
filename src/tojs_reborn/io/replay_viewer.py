from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from tojs_reborn.engine.state import CardDefinition, load_card_catalog


def run_replay_viewer_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print replay events as one-line logs.")
    parser.add_argument("--replay", required=True)
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    parser.add_argument("--no-payload", action="store_true")
    parser.add_argument("--event-type", action="append", dest="event_types")
    parser.add_argument("--only-state", action="store_true")
    parser.add_argument("--show-actions", action="store_true")
    args = parser.parse_args(argv)

    try:
        replay_record = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        card_catalog = _load_optional_card_catalog(args.cards)
        for line in format_replay_events(
            replay_record,
            card_catalog=card_catalog,
            include_payload=not args.no_payload,
            event_types=set(args.event_types) if args.event_types else None,
            only_state=args.only_state,
            include_actions=args.show_actions,
        ):
            print(line)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"replay viewer failed: {exc}", file=sys.stderr)
        return 1
    return 0


def format_replay_events(
    replay_record: dict[str, Any],
    *,
    card_catalog: dict[str, CardDefinition] | None = None,
    include_payload: bool = True,
    event_types: set[str] | None = None,
    only_state: bool = False,
    include_actions: bool = False,
) -> list[str]:
    events = replay_record.get("events")
    if not isinstance(events, list):
        raise ValueError("replay record must contain an events list")
    instance_card_nos = _collect_card_instances(replay_record)
    viewer_state = ReplayViewerState.from_replay_record(replay_record)
    lines: list[str] = []
    if include_actions:
        lines.extend(format_replay_actions(replay_record, card_catalog=card_catalog or {}, instance_card_nos=instance_card_nos))
    for event in events:
        viewer_state.apply_event(event)
        event_type = event.get("type")
        should_show_event = event_types is None or event_type in event_types
        if should_show_event and not only_state:
            lines.append(
                format_event_line(
                    event,
                    card_catalog=card_catalog or {},
                    instance_card_nos=instance_card_nos,
                    include_payload=include_payload,
                )
            )
        if event_type in {"turn_ended", "match_ended"} and should_show_event:
            lines.extend(viewer_state.format_state_lines(card_catalog=card_catalog or {}, instance_card_nos=instance_card_nos))
    return lines


def format_replay_actions(
    replay_record: dict[str, Any],
    *,
    card_catalog: dict[str, CardDefinition] | None = None,
    instance_card_nos: dict[str, str] | None = None,
) -> list[str]:
    catalog = card_catalog or {}
    instance_lookup = instance_card_nos or _collect_card_instances(replay_record)
    lines: list[str] = []
    for intent_index, intent in enumerate(replay_record.get("intents") or []):
        for choice_index, choice in enumerate(intent.get("choices") or []):
            legal_actions = choice.get("legal_actions")
            response = choice.get("response")
            if not isinstance(legal_actions, list) or not isinstance(response, dict):
                continue
            lines.append(_format_replay_action_choice(intent_index, choice_index, choice, catalog, instance_lookup))
    return lines


def format_event_line(
    event: dict[str, Any],
    *,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
    include_payload: bool = True,
) -> str:
    event_no = int(event["event_no"])
    round_no = int(event["round_no"])
    turn_no = int(event["turn_no"])
    actor = event.get("actor_player_id") or "-"
    cause = event.get("cause_event_no") or "-"
    event_type = event["type"]
    source = _format_source(event.get("source") or {}, card_catalog, instance_card_nos)
    parts = [
        f"{event_no:04d}",
        f"R{round_no}",
        f"T{turn_no}",
        f"actor={actor}",
        f"cause={cause}",
        event_type,
    ]
    if source:
        parts.append(f"source={source}")
    if include_payload:
        payload = event.get("payload") or {}
        if payload:
            parts.append(f"payload={_format_payload(payload, card_catalog, instance_card_nos)}")
    return " ".join(parts)


def _load_optional_card_catalog(path: str) -> dict[str, CardDefinition]:
    card_path = Path(path)
    if not card_path.exists():
        return {}
    return load_card_catalog(card_path)


@dataclass
class ReplayViewerPlayerState:
    life: int = 0
    current_cp: int = 0
    deck: list[str] = field(default_factory=list)
    hand: list[str] = field(default_factory=list)
    battlefield: list[str] = field(default_factory=list)
    trigger_zone: list[str] = field(default_factory=list)
    discard_pile: list[str] = field(default_factory=list)


@dataclass
class ReplayViewerState:
    players: dict[str, ReplayViewerPlayerState]
    unit_card_instance_ids: dict[str, str] = field(default_factory=dict)
    unit_levels: dict[str, int] = field(default_factory=dict)
    unit_exhausted: dict[str, bool] = field(default_factory=dict)
    unit_damage: dict[str, int] = field(default_factory=dict)
    unit_bp: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_replay_record(cls, replay_record: dict[str, Any]) -> "ReplayViewerState":
        initial_state = replay_record.get("initial_state")
        if not isinstance(initial_state, dict):
            return cls(players={})
        players: dict[str, ReplayViewerPlayerState] = {}
        for player_id, item in (initial_state.get("players") or {}).items():
            if not isinstance(item, dict):
                continue
            players[player_id] = ReplayViewerPlayerState(
                life=int(item.get("life", 0)),
                current_cp=int(item.get("current_cp", 0)),
                deck=list(item.get("deck") or []),
                hand=list(item.get("hand") or []),
                battlefield=list(item.get("battlefield") or []),
                trigger_zone=list(item.get("trigger_zone") or []),
                discard_pile=list(item.get("discard_pile") or []),
            )
        unit_card_instance_ids: dict[str, str] = {}
        unit_levels: dict[str, int] = {}
        unit_exhausted: dict[str, bool] = {}
        unit_damage: dict[str, int] = {}
        for unit_id, item in (initial_state.get("units") or {}).items():
            if not isinstance(item, dict):
                continue
            card_instance_id = item.get("card_instance_id")
            if isinstance(card_instance_id, str):
                unit_card_instance_ids[unit_id] = card_instance_id
            unit_levels[unit_id] = int(item.get("level", 1))
            unit_exhausted[unit_id] = bool(item.get("exhausted", False))
            unit_damage[unit_id] = int(item.get("current_damage", 0))
        return cls(
            players=players,
            unit_card_instance_ids=unit_card_instance_ids,
            unit_levels=unit_levels,
            unit_exhausted=unit_exhausted,
            unit_damage=unit_damage,
        )

    def apply_event(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        event_type = event.get("type")
        actor = event.get("actor_player_id")
        if event_type == "cp_set" and isinstance(actor, str):
            self._player(actor).current_cp = int(payload.get("after_cp", self._player(actor).current_cp))
        elif event_type == "cp_changed" and isinstance(actor, str):
            self._player(actor).current_cp = int(payload.get("after_cp", self._player(actor).current_cp))
        elif event_type == "life_changed":
            player_id = payload.get("player_id")
            if isinstance(player_id, str):
                self._player(player_id).life = int(payload.get("after_life", self._player(player_id).life))
        elif event_type == "card_moved":
            self._apply_card_moved(event)
        elif event_type == "unit_level_changed":
            unit_id = (event.get("source") or {}).get("unit_id")
            if isinstance(unit_id, str):
                self.unit_levels[unit_id] = int(payload.get("after_level", self.unit_levels.get(unit_id, 1)))
        elif event_type == "unit_attacked":
            unit_id = payload.get("attacker_unit_id")
            if isinstance(unit_id, str):
                self.unit_exhausted[unit_id] = True
        elif event_type == "unit_action_consumed":
            unit_id = payload.get("unit_id")
            if isinstance(unit_id, str):
                self.unit_exhausted[unit_id] = True
        elif event_type == "unit_action_recovered":
            unit_id = payload.get("unit_id")
            if isinstance(unit_id, str):
                self.unit_exhausted[unit_id] = False
        elif event_type == "damage_dealt":
            unit_id = payload.get("target_unit_id")
            if isinstance(unit_id, str):
                self.unit_damage[unit_id] = int(payload.get("after_damage", self.unit_damage.get(unit_id, 0)))
        elif event_type == "unit_damage_cleared":
            unit_id = payload.get("unit_id")
            if isinstance(unit_id, str):
                self.unit_damage[unit_id] = int(payload.get("after_damage", 0))
        elif event_type in {"bp_modified", "base_bp_modified"}:
            unit_id = payload.get("target_unit_id")
            if isinstance(unit_id, str):
                after_bp = payload.get("after_bp", payload.get("after_base_bp"))
                if after_bp is not None:
                    self.unit_bp[unit_id] = int(after_bp)
        elif event_type == "mulligan_performed" and isinstance(actor, str):
            player = self._player(actor)
            player.hand = list(payload.get("hand_card_instance_ids") or [])
            player.deck = list(payload.get("deck_card_instance_ids") or [])

    def format_state_lines(
        self,
        *,
        card_catalog: dict[str, CardDefinition],
        instance_card_nos: dict[str, str],
    ) -> list[str]:
        lines = ["     state:"]
        for player_id in sorted(self.players):
            player = self.players[player_id]
            battlefield = [
                self._format_unit(unit_id, card_catalog=card_catalog, instance_card_nos=instance_card_nos)
                for unit_id in player.battlefield
            ]
            trigger_zone = [
                self._format_card_instance(card_instance_id, card_catalog=card_catalog, instance_card_nos=instance_card_nos)
                for card_instance_id in player.trigger_zone
            ]
            lines.append(
                "     "
                f"{player_id} life={player.life} cp={player.current_cp} "
                f"hand={len(player.hand)} deck={len(player.deck)} discard={len(player.discard_pile)} "
                f"battlefield=[{', '.join(battlefield)}] "
                f"trigger=[{', '.join(trigger_zone)}]"
            )
        return lines

    def _apply_card_moved(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        source = event.get("source") or {}
        owner = payload.get("owner_player_id") or event.get("actor_player_id")
        card_instance_id = source.get("card_instance_id")
        if not isinstance(owner, str) or not isinstance(card_instance_id, str):
            return
        player = self._player(owner)
        from_zone = payload.get("from_zone")
        to_zone = payload.get("to_zone")
        unit_id = source.get("unit_id")
        if isinstance(unit_id, str):
            self.unit_card_instance_ids.setdefault(unit_id, card_instance_id)
            self.unit_exhausted.setdefault(unit_id, False)
            self.unit_damage.setdefault(unit_id, 0)
        self._remove_from_zone(player, from_zone, card_instance_id, unit_id)
        self._add_to_zone(player, to_zone, card_instance_id, unit_id)

    def _remove_from_zone(
        self,
        player: ReplayViewerPlayerState,
        zone: Any,
        card_instance_id: str,
        unit_id: Any,
    ) -> None:
        if zone == "deck":
            _remove_if_present(player.deck, card_instance_id)
        elif zone == "hand":
            _remove_if_present(player.hand, card_instance_id)
        elif zone == "battlefield" and isinstance(unit_id, str):
            _remove_if_present(player.battlefield, unit_id)
        elif zone == "trigger_zone":
            _remove_if_present(player.trigger_zone, card_instance_id)
        elif zone == "discard_pile":
            _remove_if_present(player.discard_pile, card_instance_id)

    def _add_to_zone(
        self,
        player: ReplayViewerPlayerState,
        zone: Any,
        card_instance_id: str,
        unit_id: Any,
    ) -> None:
        if zone == "deck":
            player.deck.append(card_instance_id)
        elif zone == "hand":
            player.hand.append(card_instance_id)
        elif zone == "battlefield" and isinstance(unit_id, str):
            player.battlefield.append(unit_id)
        elif zone == "trigger_zone":
            player.trigger_zone.append(card_instance_id)
        elif zone == "discard_pile":
            player.discard_pile.insert(0, card_instance_id)

    def _format_unit(
        self,
        unit_id: str,
        *,
        card_catalog: dict[str, CardDefinition],
        instance_card_nos: dict[str, str],
    ) -> str:
        card_instance_id = self.unit_card_instance_ids.get(unit_id)
        if card_instance_id is None:
            return unit_id
        card = self._format_card_instance(card_instance_id, card_catalog=card_catalog, instance_card_nos=instance_card_nos)
        level = self.unit_levels.get(unit_id, 1)
        return f"{unit_id}:{card}:LV{level}"

    def _format_card_instance(
        self,
        card_instance_id: str,
        *,
        card_catalog: dict[str, CardDefinition],
        instance_card_nos: dict[str, str],
    ) -> str:
        card_no = instance_card_nos.get(card_instance_id)
        if card_no is None:
            return card_instance_id
        return f"{card_instance_id}:{_format_card(card_no, card_catalog)}"

    def _player(self, player_id: str) -> ReplayViewerPlayerState:
        if player_id not in self.players:
            self.players[player_id] = ReplayViewerPlayerState()
        return self.players[player_id]


def _remove_if_present(items: list[str], item: str) -> None:
    try:
        items.remove(item)
    except ValueError:
        pass


def _collect_card_instances(replay_record: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for state_key in ("initial_state", "final_state"):
        state = replay_record.get(state_key)
        if not isinstance(state, dict):
            continue
        card_instances = state.get("card_instances")
        if not isinstance(card_instances, dict):
            continue
        for instance_id, item in card_instances.items():
            if isinstance(item, dict) and isinstance(item.get("card_no"), str):
                result[instance_id] = item["card_no"]
    return result


def _format_source(
    source: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str:
    card_no = source.get("card_no")
    card_instance_id = source.get("card_instance_id")
    if card_no is None and isinstance(card_instance_id, str):
        card_no = instance_card_nos.get(card_instance_id)
    parts: list[str] = []
    if isinstance(card_no, str):
        parts.append(_format_card(card_no, card_catalog))
    if isinstance(card_instance_id, str):
        parts.append(card_instance_id)
    if isinstance(source.get("unit_id"), str):
        parts.append(source["unit_id"])
    if isinstance(source.get("ability_id"), str):
        parts.append(source["ability_id"])
    return "/".join(parts)


def _format_payload(
    payload: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str:
    visible_payload = _replace_card_instance_ids(payload, card_catalog, instance_card_nos)
    return json.dumps(visible_payload, ensure_ascii=False, separators=(",", ":"))


def _format_action_summary(
    action: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str:
    action_type = str(action.get("type"))
    parts = [action_type]
    for key in ("card_instance_id", "target_card_instance_id", "material_card_instance_id"):
        value = action.get(key)
        if isinstance(value, str):
            card_no = instance_card_nos.get(value)
            if card_no is not None:
                parts.append(f"{key}={value}:{_format_card(card_no, card_catalog)}")
            else:
                parts.append(f"{key}={value}")
    for key in ("attacker_unit_id", "blocker_unit_id", "evolve_target_unit_id"):
        value = action.get(key)
        if isinstance(value, str):
            parts.append(f"{key}={value}")
    return " ".join(parts)


def _format_replay_action_choice(
    intent_index: int,
    choice_index: int,
    choice: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str:
    legal_actions = choice.get("legal_actions") or []
    response = choice.get("response") or {}
    legal_summary = [
        _format_action_summary(action, card_catalog, instance_card_nos)
        for action in legal_actions
        if isinstance(action, dict)
    ]
    selected_summary = _format_action_summary(response, card_catalog, instance_card_nos)
    return (
        "     "
        f"action intent={intent_index} choice={choice_index} player={choice.get('player_id')} "
        f"role={choice.get('role')} selected={selected_summary} legal=[{', '.join(legal_summary)}]"
    )


def _replace_card_instance_ids(
    value: Any,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> Any:
    if isinstance(value, dict):
        replaced = {key: _replace_card_instance_ids(item, card_catalog, instance_card_nos) for key, item in value.items()}
        for key, item in list(replaced.items()):
            if key.endswith("card_instance_id") and isinstance(item, str):
                card_no = instance_card_nos.get(item)
                if card_no is not None:
                    replaced[f"{key}_card"] = _format_card(card_no, card_catalog)
            elif key.endswith("card_instance_ids") and isinstance(item, list):
                cards = []
                for instance_id in item:
                    if isinstance(instance_id, str) and instance_id in instance_card_nos:
                        cards.append(_format_card(instance_card_nos[instance_id], card_catalog))
                if cards:
                    replaced[f"{key}_cards"] = cards
        return replaced
    if isinstance(value, list):
        return [_replace_card_instance_ids(item, card_catalog, instance_card_nos) for item in value]
    return value


def _format_card(card_no: str, card_catalog: dict[str, CardDefinition]) -> str:
    card = card_catalog.get(card_no)
    if card is None:
        return card_no
    return f"{card.name}({card_no})"


def main() -> None:
    raise SystemExit(run_replay_viewer_cli())


if __name__ == "__main__":
    main()
