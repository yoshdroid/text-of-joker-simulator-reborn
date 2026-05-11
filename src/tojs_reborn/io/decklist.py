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
    for index, item in enumerate(raw_cards):
        if not isinstance(item, dict):
            raise DecklistError(f"cards[{index}] must be an object")
        card_no = item.get("card_no")
        if not isinstance(card_no, str) or not card_no:
            raise DecklistError(f"cards[{index}].card_no must be a non-empty string")
        if card_no not in card_catalog:
            raise DecklistError(f"unknown card_no: {card_no}")
        count = item.get("count")
        if not isinstance(count, int) or count < 1:
            raise DecklistError(f"cards[{index}].count must be an integer greater than or equal to 1")
        entries.append(DecklistEntry(card_no=card_no, count=count))
        card_counts[card_no] = card_counts.get(card_no, 0) + count

    decklist = Decklist(deck_name=deck_name, entries=tuple(entries))
    expanded = decklist.expanded_card_nos()
    if not expanded:
        raise DecklistError("deck must contain at least one card")
    if strict_deck_rule:
        _validate_strict_deck_rule(expanded, card_counts)
    return decklist


def _validate_strict_deck_rule(expanded_card_nos: list[str], card_counts: dict[str, int]) -> None:
    if len(expanded_card_nos) != 40:
        raise DecklistError(f"strict deck rule requires exactly 40 cards: actual={len(expanded_card_nos)}")
    over_limit = {card_no: count for card_no, count in card_counts.items() if count > 3}
    if over_limit:
        detail = ", ".join(f"{card_no}={count}" for card_no, count in sorted(over_limit.items()))
        raise DecklistError(f"strict deck rule allows at most 3 copies per card: {detail}")
