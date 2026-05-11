from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from tojs_reborn.engine.state import CardDefinition, load_card_catalog


def run_replay_viewer_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print replay events as one-line logs.")
    parser.add_argument("--replay", required=True)
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    parser.add_argument("--no-payload", action="store_true")
    args = parser.parse_args(argv)

    try:
        replay_record = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        card_catalog = _load_optional_card_catalog(args.cards)
        for line in format_replay_events(replay_record, card_catalog=card_catalog, include_payload=not args.no_payload):
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
) -> list[str]:
    events = replay_record.get("events")
    if not isinstance(events, list):
        raise ValueError("replay record must contain an events list")
    instance_card_nos = _collect_card_instances(replay_record)
    return [
        format_event_line(
            event,
            card_catalog=card_catalog or {},
            instance_card_nos=instance_card_nos,
            include_payload=include_payload,
        )
        for event in events
    ]


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
