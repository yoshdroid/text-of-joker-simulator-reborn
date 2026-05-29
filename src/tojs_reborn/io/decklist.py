from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tojs_reborn.engine.state import CardDefinition


class DecklistError(ValueError):
    pass


@dataclass(frozen=True)
class DecklistEntry:
    card_no: str
    count: int


@dataclass(frozen=True)
class Decklist:
    deck_name: str
    entries: tuple[DecklistEntry, ...]
    joker_no: str = "JK-01"

    def expanded_card_nos(self) -> list[str]:
        card_nos: list[str] = []
        for entry in self.entries:
            card_nos.extend([entry.card_no] * entry.count)
        return card_nos


def load_decklist(
    path: str | Path,
    card_catalog: dict[str, CardDefinition],
    *,
    strict_deck_rule: bool = False,
) -> Decklist:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return parse_decklist(data, card_catalog, strict_deck_rule=strict_deck_rule)


def parse_decklist(
    data: dict[str, Any],
    card_catalog: dict[str, CardDefinition],
    *,
    strict_deck_rule: bool = False,
) -> Decklist:
    if not isinstance(data, dict):
        raise DecklistError("decklist must be a JSON object")
    deck_name = data.get("deck_name") or "unnamed"
    if not isinstance(deck_name, str):
        raise DecklistError("deck_name must be a string")
    raw_cards = data.get("cards")
    if not isinstance(raw_cards, list):
        raise DecklistError("cards must be a list")

    entries: list[DecklistEntry] = []
    card_counts: dict[str, int] = {}
    card_no_by_name, duplicate_card_names = _build_card_name_index(card_catalog)
    for index, item in enumerate(raw_cards):
        if not isinstance(item, dict):
            raise DecklistError(f"cards[{index}] must be an object")
        card_no = _resolve_card_no(item, index, card_catalog, card_no_by_name, duplicate_card_names)
        count = item.get("count")
        if not isinstance(count, int) or count < 1:
            raise DecklistError(f"cards[{index}].count must be an integer greater than or equal to 1")
        entries.append(DecklistEntry(card_no=card_no, count=count))
        card_counts[card_no] = card_counts.get(card_no, 0) + count

    joker_no = data.get("joker", "JK-01")
    if not isinstance(joker_no, str) or not joker_no:
        raise DecklistError("joker must be a non-empty string")
    decklist = Decklist(deck_name=deck_name, entries=tuple(entries), joker_no=joker_no)
    expanded = decklist.expanded_card_nos()
    if not expanded:
        raise DecklistError("deck must contain at least one card")
    if strict_deck_rule:
        _validate_strict_deck_rule(expanded, card_counts)
    return decklist


def _resolve_card_no(
    item: dict[str, Any],
    index: int,
    card_catalog: dict[str, CardDefinition],
    card_no_by_name: dict[str, str],
    duplicate_card_names: set[str],
) -> str:
    card_no = item.get("card_no")
    card_name = item.get("card_name", item.get("name"))
    has_card_no = isinstance(card_no, str) and bool(card_no)
    has_card_name = isinstance(card_name, str) and bool(card_name)
    if has_card_no and has_card_name:
        raise DecklistError(f"cards[{index}] must specify either card_no or card_name, not both")
    if has_card_no:
        if card_no not in card_catalog:
            raise DecklistError(f"unknown card_no: {card_no}")
        return card_no
    if has_card_name:
        if card_name in duplicate_card_names:
            raise DecklistError(f"ambiguous card_name: {card_name}")
        resolved = card_no_by_name.get(card_name)
        if resolved is None:
            raise DecklistError(f"unknown card_name: {card_name}")
        return resolved
    raise DecklistError(f"cards[{index}] must specify card_name or card_no")


def _build_card_name_index(card_catalog: dict[str, CardDefinition]) -> tuple[dict[str, str], set[str]]:
    card_no_by_name: dict[str, str] = {}
    duplicate_names: set[str] = set()
    for card_no, card in card_catalog.items():
        if card.name in card_no_by_name:
            duplicate_names.add(card.name)
            continue
        card_no_by_name[card.name] = card_no
    for name in duplicate_names:
        del card_no_by_name[name]
    return card_no_by_name, duplicate_names


def _validate_strict_deck_rule(expanded_card_nos: list[str], card_counts: dict[str, int]) -> None:
    if len(expanded_card_nos) != 40:
        raise DecklistError(f"strict deck rule requires exactly 40 cards: actual={len(expanded_card_nos)}")
    over_limit = {card_no: count for card_no, count in card_counts.items() if count > 3}
    if over_limit:
        detail = ", ".join(f"{card_no}={count}" for card_no, count in sorted(over_limit.items()))
        raise DecklistError(f"strict deck rule allows at most 3 copies per card: {detail}")
