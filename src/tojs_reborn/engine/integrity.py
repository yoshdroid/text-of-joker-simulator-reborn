from __future__ import annotations

from collections import Counter

from .rules import MAX_BATTLEFIELD_UNITS, MAX_HAND_SIZE, MAX_TRIGGER_ZONE_CARDS
from .state import GameState


def assert_game_state_integrity(state: GameState) -> None:
    errors: list[str] = []
    zone_locations: list[tuple[str, str, str]] = []
    for player_id, player in state.players.items():
        if len(player.hand.cards) > MAX_HAND_SIZE:
            errors.append(f"{player_id}.hand exceeds limit: {len(player.hand.cards)} > {MAX_HAND_SIZE}")
        if len(player.battlefield.units) > MAX_BATTLEFIELD_UNITS:
            errors.append(f"{player_id}.battlefield exceeds limit: {len(player.battlefield.units)} > {MAX_BATTLEFIELD_UNITS}")
        if len(player.trigger_zone.cards) > MAX_TRIGGER_ZONE_CARDS:
            errors.append(f"{player_id}.trigger_zone exceeds limit: {len(player.trigger_zone.cards)} > {MAX_TRIGGER_ZONE_CARDS}")
        for zone_name, items in (
            ("deck", player.deck.cards),
            ("hand", player.hand.cards),
            ("trigger_zone", player.trigger_zone.cards),
            ("discard_pile", player.discard_pile.cards),
        ):
            for card_instance_id in items:
                if card_instance_id not in state.card_instances:
                    errors.append(f"{player_id}.{zone_name} references missing card instance: {card_instance_id}")
                zone_locations.append((card_instance_id, player_id, zone_name))
        for unit_id in player.battlefield.units:
            unit = state.units.get(unit_id)
            if unit is None:
                errors.append(f"{player_id}.battlefield references missing unit: {unit_id}")
                continue
            if unit.owner_player_id != player_id:
                errors.append(f"{player_id}.battlefield contains unit owned by {unit.owner_player_id}: {unit_id}")
            if unit.card_instance_id not in state.card_instances:
                errors.append(f"{unit_id} references missing card instance: {unit.card_instance_id}")
            else:
                zone_locations.append((unit.card_instance_id, player_id, "battlefield"))
                instance = state.card_instances[unit.card_instance_id]
                if instance.card_no != unit.card_no:
                    errors.append(f"{unit_id} card_no mismatch: unit={unit.card_no} instance={instance.card_no}")
                if instance.owner_player_id != unit.owner_player_id:
                    errors.append(
                        f"{unit_id} owner mismatch: unit={unit.owner_player_id} instance={instance.owner_player_id}"
                    )

    for unit_id, unit in state.units.items():
        owner = state.players.get(unit.owner_player_id)
        if owner is None:
            errors.append(f"{unit_id} has unknown owner: {unit.owner_player_id}")
        elif unit_id not in owner.battlefield.units:
            errors.append(f"{unit_id} exists in state.units but not in owner battlefield")

    duplicate_zones = [
        card_instance_id
        for card_instance_id, count in Counter(card_instance_id for card_instance_id, _player_id, _zone in zone_locations).items()
        if count > 1
    ]
    for card_instance_id in duplicate_zones:
        locations = [f"{player_id}.{zone_name}" for item, player_id, zone_name in zone_locations if item == card_instance_id]
        errors.append(f"{card_instance_id} appears in multiple zones: {', '.join(locations)}")

    if errors:
        raise AssertionError("game state integrity violation: " + "; ".join(errors))
