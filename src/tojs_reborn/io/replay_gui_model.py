from __future__ import annotations

from pathlib import Path
from typing import Any

from tojs_reborn.engine.rules import card_bp_to_game_bp
from tojs_reborn.engine.state import CardDefinition

from .gui_view_model import find_card_image
from .replay_viewer import (
    ReplayViewerState,
    _collect_card_instances,
    _format_action_summary,
    _format_replay_action_choice,
    format_event_line,
    format_replay_actions,
)


EVENT_LINE_TAGS_BY_TYPE = {
    "ability_resolved": "action",
}

ABILITY_EVENT_TAG_BY_CARD_COLOR = {
    "赤": "ability_red",
    "青": "ability_blue",
    "緑": "ability_green",
    "黄": "ability_yellow",
    "白": "ability_white",
    "無": "ability_white",
}


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
    event_line_tags = [_event_line_tag(event, catalog, instance_card_nos) for event in events]
    action_lines = format_replay_actions(replay_record, card_catalog=catalog, instance_card_nos=instance_card_nos)
    action_lines_by_event_index = _action_lines_by_event_index(
        replay_record,
        events,
        card_catalog=catalog,
        instance_card_nos=instance_card_nos,
    )
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
                image_root=image_root,
            )
        )
    return {
        "schema_version": 1,
        "seed": replay_record.get("seed"),
        "match_result": replay_record.get("match_result") or _match_result_from_events(events),
        "event_lines": event_lines,
        "event_line_tags": event_line_tags,
        "action_lines": action_lines,
        "action_lines_by_event_index": action_lines_by_event_index,
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
    image_root: Path | None,
) -> dict[str, Any]:
    highlights = _event_highlights(current_event, viewer_state)
    return {
        "event_index": event_index,
        "event_count": len(event_lines),
        "action_count": len(action_lines),
        "current_event": _event_summary(current_event),
        "highlights": {
            "card_instance_ids": sorted(highlights["card_instance_ids"]),
            "unit_ids": sorted(highlights["unit_ids"]),
        },
        "round_no": _current_number(replay_record, current_event, "round_no"),
        "turn_no": _current_number(replay_record, current_event, "turn_no"),
        "turn_player_id": viewer_state.turn_player_id,
        "players": [
            _player_model(
                player_id,
                viewer_state,
                card_catalog=card_catalog,
                instance_card_nos=instance_card_nos,
                image_root=image_root,
                highlights=highlights,
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
    image_root: Path | None,
    highlights: dict[str, set[str]],
) -> dict[str, Any]:
    player = viewer_state.players[player_id]
    instance_levels = viewer_state.card_instance_levels
    unit_trigger_colors = _unit_trigger_colors(player.trigger_zone, card_catalog, instance_card_nos)
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
                image_root=image_root,
                highlights=highlights,
            )
            for unit_id in player.battlefield
        ],
        "hand": [
            _hand_card_tile(
                card_instance_id,
                card_catalog=card_catalog,
                instance_card_nos=instance_card_nos,
                instance_levels=instance_levels,
                image_root=image_root,
                highlights=highlights,
                unit_trigger_colors=unit_trigger_colors,
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
                highlights=highlights,
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
                highlights=highlights,
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
                highlights=highlights,
            )
            for card_instance_id in player.deck
        ],
    }


def _unit_trigger_colors(
    trigger_zone_card_instance_ids: list[str],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> set[str]:
    colors: set[str] = set()
    for card_instance_id in trigger_zone_card_instance_ids:
        card = card_catalog.get(instance_card_nos.get(card_instance_id, ""))
        if card is not None and card.category == "unit":
            colors.add(card.color)
    return colors


def _unit_tile(
    unit_id: str,
    viewer_state: ReplayViewerState,
    *,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
    image_root: Path | None,
    highlights: dict[str, set[str]],
) -> dict[str, Any]:
    card_instance_id = viewer_state.unit_card_instance_ids.get(unit_id, "")
    tile = _card_tile(
        card_instance_id,
        card_catalog=card_catalog,
        instance_card_nos=instance_card_nos,
        instance_levels=viewer_state.card_instance_levels,
        image_root=image_root,
        highlights=highlights,
    )
    card_no = tile.get("card_no")
    level = viewer_state.unit_levels.get(unit_id, tile.get("level", 1))
    damage = viewer_state.unit_damage.get(unit_id, 0)
    full_bp = viewer_state.unit_bp.get(
        unit_id,
        _printed_bp(card_catalog.get(str(card_no)), level),
    )
    tile.update(
        {
            "kind": "unit",
            "unit_id": unit_id,
            "highlight": unit_id in highlights["unit_ids"] or card_instance_id in highlights["card_instance_ids"],
            "level": level,
            "exhausted": viewer_state.unit_exhausted.get(unit_id, False),
            "damage": damage,
            "current_bp": max(0, full_bp - damage) if full_bp is not None else None,
        }
    )
    return tile


def _hand_card_tile(
    card_instance_id: str,
    *,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
    instance_levels: dict[str, int],
    image_root: Path | None,
    highlights: dict[str, set[str]],
    unit_trigger_colors: set[str],
) -> dict[str, Any]:
    tile = _card_tile(
        card_instance_id,
        card_catalog=card_catalog,
        instance_card_nos=instance_card_nos,
        instance_levels=instance_levels,
        image_root=image_root,
        highlights=highlights,
    )
    cp = tile.get("cp")
    if tile.get("category") == "unit" and tile.get("color") in unit_trigger_colors and isinstance(cp, int):
        tile["display_cp"] = max(0, cp - 1)
        tile["cp_reduced"] = True
    return tile


def _card_tile(
    card_instance_id: str,
    *,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
    instance_levels: dict[str, int],
    image_root: Path | None,
    highlights: dict[str, set[str]],
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
        "highlight": card_instance_id in highlights["card_instance_ids"],
        "image_path": find_card_image(image_root, card_no) if image_root is not None and card_no else None,
    }


def _event_highlights(
    event: dict[str, Any] | None,
    viewer_state: ReplayViewerState,
) -> dict[str, set[str]]:
    unit_ids: set[str] = set()
    card_instance_ids: set[str] = set()
    if event is None:
        return {"unit_ids": unit_ids, "card_instance_ids": card_instance_ids}
    source = event.get("source")
    if isinstance(source, dict):
        _collect_highlight_ids(source, unit_ids=unit_ids, card_instance_ids=card_instance_ids)
    payload = event.get("payload")
    if isinstance(payload, dict):
        _collect_highlight_ids(payload, unit_ids=unit_ids, card_instance_ids=card_instance_ids)
        for key in ("choice", "selected", "target", "card", "attacker", "blocker", "unit"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                _collect_highlight_ids(nested, unit_ids=unit_ids, card_instance_ids=card_instance_ids)
    for unit_id in list(unit_ids):
        card_instance_id = viewer_state.unit_card_instance_ids.get(unit_id)
        if card_instance_id:
            card_instance_ids.add(card_instance_id)
    return {"unit_ids": unit_ids, "card_instance_ids": card_instance_ids}


def _collect_highlight_ids(
    value: dict[str, Any],
    *,
    unit_ids: set[str],
    card_instance_ids: set[str],
) -> None:
    for key in (
        "unit_id",
        "source_unit_id",
        "target_unit_id",
        "attacker_unit_id",
        "blocker_unit_id",
        "evolve_target_unit_id",
        "chosen_unit_id",
    ):
        item = value.get(key)
        if isinstance(item, str):
            unit_ids.add(item)
    for key in (
        "card_instance_id",
        "source_card_instance_id",
        "target_card_instance_id",
        "material_card_instance_id",
        "chosen_card_instance_id",
    ):
        item = value.get(key)
        if isinstance(item, str):
            card_instance_ids.add(item)
    for key in ("card_instance_ids", "drawn_card_instance_ids", "returned_card_instance_ids"):
        items = value.get(key)
        if isinstance(items, list):
            card_instance_ids.update(item for item in items if isinstance(item, str))


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


def _event_line_tag(
    event: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str | None:
    if event.get("type") == "ability_resolved":
        return _ability_event_line_tag(event, card_catalog, instance_card_nos)
    return EVENT_LINE_TAGS_BY_TYPE.get(str(event.get("type")))


def _ability_event_line_tag(
    event: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str:
    source = event.get("source") or {}
    card_no = source.get("card_no")
    if not isinstance(card_no, str):
        card_instance_id = source.get("card_instance_id")
        if isinstance(card_instance_id, str):
            card_no = instance_card_nos.get(card_instance_id)
    if isinstance(card_no, str):
        card = card_catalog.get(card_no)
        if card is not None:
            return ABILITY_EVENT_TAG_BY_CARD_COLOR.get(card.color, "action")
    return "action"


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


def _action_lines_by_event_index(
    replay_record: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> list[list[str]]:
    result: list[list[str]] = [[] for _ in events]
    choices = _recorded_choices(replay_record)
    used_choice_indexes: set[int] = set()
    for event_index, event in enumerate(events):
        if event.get("type") == "choice_selected":
            choice_index = _find_matching_recorded_choice_index(event, choices, used_choice_indexes)
            if choice_index is not None:
                used_choice_indexes.add(choice_index)
                intent_index, inner_choice_index, choice = choices[choice_index]
                result[event_index].append(
                    _format_recorded_choice_line(intent_index, inner_choice_index, choice, card_catalog, instance_card_nos)
                )
            else:
                result[event_index].append(_format_event_choice_selected_line(event, card_catalog, instance_card_nos))
            continue
        expected_action = _event_selected_action_type(event)
        if expected_action is None:
            continue
        choice_index = _find_matching_choice_index(event, expected_action, choices, used_choice_indexes)
        if choice_index is None:
            continue
        used_choice_indexes.add(choice_index)
        intent_index, inner_choice_index, choice = choices[choice_index]
        result[event_index].append(
            _format_replay_action_choice(intent_index, inner_choice_index, choice, card_catalog, instance_card_nos)
        )
    return result


def _recorded_choices(replay_record: dict[str, Any]) -> list[tuple[int, int, dict[str, Any]]]:
    result: list[tuple[int, int, dict[str, Any]]] = []
    for intent_index, intent in enumerate(replay_record.get("intents") or []):
        for choice_index, choice in enumerate(intent.get("choices") or []):
            if isinstance(choice, dict) and isinstance(choice.get("response"), dict):
                result.append((intent_index, choice_index, choice))
    return result


def _format_recorded_choice_line(
    intent_index: int,
    choice_index: int,
    choice: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str:
    if isinstance(choice.get("legal_actions"), list):
        return _format_replay_action_choice(intent_index, choice_index, choice, card_catalog, instance_card_nos)
    selected_summary = _format_choice_value(choice.get("response"), card_catalog, instance_card_nos)
    return (
        "     "
        f"choice intent={intent_index} choice={choice_index} player={choice.get('player_id')} "
        f"role={choice.get('role')} selected={selected_summary}"
    )


def _format_event_choice_selected_line(
    event: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str:
    payload = event.get("payload") or {}
    selected = payload.get("choice")
    if selected is None:
        selected = _selected_choice_from_event_payload(payload)
    choice_type = payload.get("type") or payload.get("choice_id") or "choice"
    return (
        "     "
        f"choice event={event.get('event_no')} player={event.get('actor_player_id')} "
        f"role={choice_type} selected={_format_choice_value(selected, card_catalog, instance_card_nos)}"
    )


def _event_selected_action_type(event: dict[str, Any]) -> str | None:
    payload = event.get("payload") or {}
    event_type = event.get("type")
    if event_type == "action_declared":
        action_type = payload.get("action")
        return str(action_type) if action_type is not None else None
    if event_type == "block_declared":
        return "block"
    if event_type == "intercept_activated":
        return "activate_intercept"
    if event_type == "intercept_passed":
        return "pass_window"
    return None


def _find_matching_choice_index(
    event: dict[str, Any],
    expected_action: str,
    choices: list[tuple[int, int, dict[str, Any]]],
    used_choice_indexes: set[int],
) -> int | None:
    actor = event.get("actor_player_id")
    payload = event.get("payload") or {}
    source = event.get("source") or {}
    for require_actor in (True, False):
        for index, (_intent_index, _choice_index, choice) in enumerate(choices):
            if index in used_choice_indexes:
                continue
            if require_actor and actor is not None and choice.get("player_id") != actor:
                continue
            response = choice.get("response")
            if not isinstance(response, dict) or response.get("type") != expected_action:
                continue
            if _action_response_matches_event(response, payload, source):
                return index
    return None


def _find_matching_recorded_choice_index(
    event: dict[str, Any],
    choices: list[tuple[int, int, dict[str, Any]]],
    used_choice_indexes: set[int],
) -> int | None:
    actor = event.get("actor_player_id")
    payload = event.get("payload") or {}
    for require_actor in (True, False):
        for index, (_intent_index, _choice_index, choice) in enumerate(choices):
            if index in used_choice_indexes:
                continue
            if isinstance(choice.get("legal_actions"), list):
                continue
            if require_actor and actor is not None and choice.get("player_id") != actor:
                continue
            response = choice.get("response")
            if isinstance(response, dict) and _choice_response_matches_event(response, payload):
                return index
    return None


def _action_response_matches_event(response: dict[str, Any], payload: dict[str, Any], source: dict[str, Any]) -> bool:
    for key in (
        "card_instance_id",
        "target_card_instance_id",
        "material_card_instance_id",
        "attacker_unit_id",
        "blocker_unit_id",
        "evolve_target_unit_id",
    ):
        expected = response.get(key)
        if expected is None:
            continue
        if payload.get(key) == expected or source.get(key) == expected:
            continue
        return False
    return True


def _choice_response_matches_event(response: dict[str, Any], payload: dict[str, Any]) -> bool:
    selected = payload.get("choice")
    if isinstance(selected, dict):
        return _normalized_choice(response) == _normalized_choice(selected)
    if isinstance(selected, str):
        return response.get("type") == selected
    payload_selected = _selected_choice_from_event_payload(payload)
    if isinstance(payload_selected, dict):
        return _normalized_choice(response) == _normalized_choice(payload_selected)
    return False


def _selected_choice_from_event_payload(payload: dict[str, Any]) -> Any:
    if isinstance(payload.get("chosen_card_instance_id"), str):
        return {"card_instance_id": payload["chosen_card_instance_id"]}
    if isinstance(payload.get("chosen_unit_id"), str):
        return {"unit_id": payload["chosen_unit_id"]}
    return None


def _normalized_choice(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in {"display", "target", "card"}}


def _format_choice_value(
    value: Any,
    card_catalog: dict[str, CardDefinition],
    instance_card_nos: dict[str, str],
) -> str:
    if isinstance(value, dict) and isinstance(value.get("type"), str):
        return _format_action_summary(value, card_catalog, instance_card_nos)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if key in {"display", "target", "card"}:
                continue
            parts.append(f"{key}={_format_choice_value(item, card_catalog, instance_card_nos)}")
        return " ".join(parts) if parts else "{}"
    if isinstance(value, list):
        return "[" + ", ".join(_format_choice_value(item, card_catalog, instance_card_nos) for item in value) + "]"
    if isinstance(value, str) and value in instance_card_nos:
        card_no = instance_card_nos[value]
        card = card_catalog.get(card_no)
        card_label = f"{card.name}({card_no})" if card is not None else card_no
        return f"{value}:{card_label}"
    return str(value)


def _printed_bp(card: CardDefinition | None, level: int) -> int | None:
    if card is None or not card.bp_by_level:
        return None
    index = max(0, min(level, len(card.bp_by_level)) - 1)
    return card_bp_to_game_bp(int(card.bp_by_level[index]))
