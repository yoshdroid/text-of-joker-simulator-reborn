from __future__ import annotations

from pathlib import Path
from typing import Any

from tojs_reborn.engine.state import CardDefinition

from .gui_view_model import find_card_image
from .replay_viewer import ReplayViewerState, _collect_card_instances, format_event_line, format_replay_actions


def build_replay_gui_model(
    replay_record: dict[str, Any],
    *,
    card_catalog: dict[str, CardDefinition] | None = None,
    images_dir: str | Path | None = None,
) -> dict[str, Any]:
    events = replay_record.get("events")
    if not isinstance(events, list):
        raise ValueError("replay record must contain an events list")
    catalog = card_catalog or {}
    instance_card_nos = _collect_card_instances(replay_record)
    instance_levels = _collect_card_instance_levels(replay_record)
    image_root = Path(images_dir) if images_dir is not None else None
    viewer_state = ReplayViewerState.from_replay_record(replay_record)
    event_lines = [
        format_event_line(
            event,
            card_catalog=catalog,
            instance_card_nos=instance_card_nos,
            include_payload=False,
        )
        for event in events
    ]
    action_lines = format_replay_actions(replay_record, card_catalog=catalog, instance_card_nos=instance_card_nos)
    frames = [
        _frame(
            replay_record,
            viewer_state,
            current_event=None,
            event_index=-1,
            event_lines=event_lines,
            action_lines=action_lines,
            card_catalog=catalog,
            instance_card_nos=instance_card_nos,
            instance_levels=instance_levels,
            image_root=image_root,
        )
    ]
    for index, event in enumerate(events):
        viewer_state.apply_event(event)
        frames.append(
            _frame(
                replay_record,
                viewer_state,
                current_event=event,
                event_index=index,
                event_lines=event_lines,
                action_lines=action_lines,
                card_catalog=catalog,
                instance_card_nos=instance_card_nos,
                instance_levels=instance_levels,
                image_root=image_root,
            )
        )
    return {
        "schema_version": 1,
        "seed": replay_record.get("seed"),
        "match_result": replay_record.get("match_result") or _match_result_from_events(events),
        "event_lines": event_lines,
        "action_lines": action_lines,
        "frames": frames,
    }


def _frame(
    replay_record: dict[str, Any],
    viewer_state: ReplayViewerState,
    *,
    current_event: dict[str, Any] | None,
    event_index: int,
    event_lines: list[str],
    action_lines: list[str],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
    instance_levels: dict[str, int],
    image_root: Path | None,
) -> dict[str, Any]:
    return {
        "event_index": event_index,
        "event_count": len(event_lines),
        "action_count": len(action_lines),
        "current_event": _event_summary(current_event),
        "round_no": _current_number(replay_record, current_event, "round_no"),
        "turn_no": _current_number(replay_record, current_event, "turn_no"),
        "turn_player_id": _current_value(replay_record, current_event, "turn_player_id"),
        "players": [
            _player_model(
                player_id,
                viewer_state,
                card_catalog=card_catalog,
                instance_card_nos=instance_card_nos,
                instance_levels=instance_levels,
                image_root=image_root,
            )
            for player_id in sorted(viewer_state.players)
        ],
    }


def _player_model(
    player_id: str,
    viewer_state: ReplayViewerState,
    *,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
    instance_levels: dict[str, int],
    image_root: Path | None,
) -> dict[str, Any]:
    player = viewer_state.players[player_id]
    return {
        "player_id": player_id,
        "status": {
            "life": player.life,
            "current_cp": player.current_cp,
            "hand_count": len(player.hand),
            "deck_count": len(player.deck),
            "discard_count": len(player.discard_pile),
            "trigger_zone_count": len(player.trigger_zone),
            "battlefield_count": len(player.battlefield),
        },
        "battlefield": [
            _unit_tile(
                unit_id,
                viewer_state,
                card_catalog=card_catalog,
                instance_card_nos=instance_card_nos,
                instance_levels=instance_levels,
                image_root=image_root,
            )
            for unit_id in player.battlefield
        ],
        "hand": [
            _card_tile(
                card_instance_id,
                card_catalog=card_catalog,
                instance_card_nos=instance_card_nos,
                instance_levels=instance_levels,
                image_root=image_root,
            )
            for card_instance_id in player.hand
        ],
        "trigger_zone": [
            _card_tile(
                card_instance_id,
                card_catalog=card_catalog,
                instance_card_nos=instance_card_nos,
                instance_levels=instance_levels,
                image_root=image_root,
            )
            for card_instance_id in player.trigger_zone
        ],
        "discard_pile": [
            _card_tile(
                card_instance_id,
                card_catalog=card_catalog,
                instance_card_nos=instance_card_nos,
                instance_levels=instance_levels,
                image_root=image_root,
            )
            for card_instance_id in player.discard_pile
        ],
        "deck": [
            _card_tile(
                card_instance_id,
                card_catalog=card_catalog,
                instance_card_nos=instance_card_nos,
                instance_levels=instance_levels,
                image_root=image_root,
            )
            for card_instance_id in player.deck
        ],
    }


def _unit_tile(
    unit_id: str,
    viewer_state: ReplayViewerState,
    *,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
    instance_levels: dict[str, int],
    image_root: Path | None,
) -> dict[str, Any]:
    card_instance_id = viewer_state.unit_card_instance_ids.get(unit_id, "")
    tile = _card_tile(
        card_instance_id,
        card_catalog=card_catalog,
        instance_card_nos=instance_card_nos,
        instance_levels=instance_levels,
        image_root=image_root,
    )
    card_no = tile.get("card_no")
    tile.update(
        {
            "kind": "unit",
            "unit_id": unit_id,
            "level": viewer_state.unit_levels.get(unit_id, tile.get("level", 1)),
            "exhausted": viewer_state.unit_exhausted.get(unit_id, False),
            "damage": viewer_state.unit_damage.get(unit_id, 0),
            "current_bp": viewer_state.unit_bp.get(
                unit_id,
                _printed_bp(card_catalog.get(str(card_no)), viewer_state.unit_levels.get(unit_id, 1)),
            ),
        }
    )
    return tile


def _card_tile(
    card_instance_id: str,
    *,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
    instance_levels: dict[str, int],
    image_root: Path | None,
) -> dict[str, Any]:
    card_no = instance_card_nos.get(card_instance_id, "")
    card = card_catalog.get(card_no)
    return {
        "kind": "card",
        "card_instance_id": card_instance_id,
        "card_no": card_no,
        "name": card.name if card is not None else card_no,
        "category": card.category if card is not None else None,
        "color": card.color if card is not None else None,
        "cp": card.cp if card is not None else None,
        "level": instance_levels.get(card_instance_id, 1),
        "image_path": find_card_image(image_root, card_no) if image_root is not None and card_no else None,
    }


def _event_summary(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "event_no": event.get("event_no"),
        "type": event.get("type"),
        "actor_player_id": event.get("actor_player_id"),
        "cause_event_no": event.get("cause_event_no"),
        "description": _event_description(event),
    }


def _event_description(event: dict[str, Any]) -> str:
    event_no = event.get("event_no")
    event_type = event.get("type")
    actor = event.get("actor_player_id") or "-"
    return f"#{event_no} {event_type} actor={actor}"


def _current_number(replay_record: dict[str, Any], current_event: dict[str, Any] | None, key: str) -> int | None:
    value = _current_value(replay_record, current_event, key)
    return int(value) if value is not None else None


def _current_value(replay_record: dict[str, Any], current_event: dict[str, Any] | None, key: str) -> Any:
    if current_event is not None and key in current_event:
        return current_event.get(key)
    initial_state = replay_record.get("initial_state")
    if isinstance(initial_state, dict):
        return initial_state.get(key)
    return replay_record.get(key)


def _match_result_from_events(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("type") == "match_ended":
            return event.get("payload") or {}
    return None


def _collect_card_instance_levels(replay_record: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for state_key in ("initial_state", "final_state"):
        state = replay_record.get(state_key)
        if not isinstance(state, dict):
            continue
        card_instances = state.get("card_instances")
        if not isinstance(card_instances, dict):
            continue
        for instance_id, item in card_instances.items():
            if isinstance(item, dict):
                result[instance_id] = int(item.get("level", 1))
    return result


def _printed_bp(card: CardDefinition | None, level: int) -> int | None:
    if card is None or not card.bp_by_level:
        return None
    index = max(0, min(level, len(card.bp_by_level)) - 1)
    return int(card.bp_by_level[index])
