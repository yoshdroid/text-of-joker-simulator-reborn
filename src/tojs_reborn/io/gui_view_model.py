from __future__ import annotations

from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


def build_gui_view_model(
    public_state: dict[str, Any],
    private_view: dict[str, Any],
    *,
    images_dir: str | Path | None = None,
) -> dict[str, Any]:
    player_id = str(private_view["player_id"])
    players = public_state.get("players") or {}
    opponent_id = _first_opponent_id(players, player_id)
    image_root = Path(images_dir) if images_dir is not None else None
    return {
        "player_id": player_id,
        "round_no": public_state.get("round_no"),
        "turn_no": public_state.get("turn_no"),
        "turn_player_id": public_state.get("turn_player_id"),
        "own": {
            "status": _player_status(players.get(player_id) or {}),
            "battlefield": [_unit_tile(unit, image_root) for unit in (players.get(player_id) or {}).get("battlefield", [])],
            "hand": [_card_tile(card, image_root) for card in private_view.get("hand", [])],
            "trigger_zone": [_card_tile(card, image_root) for card in private_view.get("trigger_zone", [])],
        },
        "opponent": {
            "player_id": opponent_id,
            "status": _player_status(players.get(opponent_id) or {}),
            "battlefield": [_unit_tile(unit, image_root) for unit in (players.get(opponent_id) or {}).get("battlefield", [])],
        },
    }


def find_card_image(images_dir: str | Path, card_no: str) -> str | None:
    root = Path(images_dir)
    if not root.exists():
        return None
    for suffix in IMAGE_SUFFIXES:
        matches = sorted(root.glob(f"{card_no}*{suffix}"))
        if matches:
            return str(matches[0])
    return None


def _player_status(player: dict[str, Any]) -> dict[str, Any]:
    return {
        "life": player.get("life", 0),
        "current_cp": player.get("current_cp", 0),
        "hand_count": player.get("hand_count", 0),
        "deck_count": player.get("deck_count", 0),
        "discard_count": len(player.get("discard_pile") or []),
    }


def _unit_tile(unit: dict[str, Any], images_dir: Path | None) -> dict[str, Any]:
    card_no = str(unit.get("card_no") or "")
    return {
        "kind": "unit",
        "unit_id": unit.get("unit_id"),
        "card_instance_id": unit.get("card_instance_id"),
        "card_no": card_no,
        "name": unit.get("name"),
        "level": unit.get("level"),
        "current_bp": unit.get("current_bp"),
        "damage": unit.get("current_damage"),
        "exhausted": unit.get("exhausted", False),
        "image_path": find_card_image(images_dir, card_no) if images_dir is not None and card_no else None,
    }


def _card_tile(card: dict[str, Any], images_dir: Path | None) -> dict[str, Any]:
    card_no = str(card.get("card_no") or "")
    return {
        "kind": "card",
        "card_instance_id": card.get("card_instance_id"),
        "card_no": card_no,
        "name": card.get("name"),
        "category": card.get("category"),
        "color": card.get("color"),
        "cp": card.get("cp"),
        "level": card.get("level"),
        "image_path": find_card_image(images_dir, card_no) if images_dir is not None and card_no else None,
    }


def _first_opponent_id(players: dict[str, Any], player_id: str) -> str | None:
    for candidate in sorted(players):
        if candidate != player_id:
            return candidate
    return None
