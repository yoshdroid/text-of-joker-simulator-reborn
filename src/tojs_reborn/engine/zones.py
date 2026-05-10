from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Deck:
    cards: list[str] = field(default_factory=list)

    def draw_top(self) -> str | None:
        if not self.cards:
            return None
        return self.cards.pop(0)


@dataclass
class Hand:
    cards: list[str] = field(default_factory=list)

    def remove(self, card_instance_id: str) -> None:
        self.cards.remove(card_instance_id)

    def add(self, card_instance_id: str) -> None:
        self.cards.append(card_instance_id)


@dataclass
class BattleField:
    units: list[str] = field(default_factory=list)

    def add(self, unit_id: str) -> None:
        self.units.append(unit_id)

    def remove(self, unit_id: str) -> None:
        self.units.remove(unit_id)


@dataclass
class TriggerZone:
    cards: list[str] = field(default_factory=list)

    def add(self, card_instance_id: str) -> None:
        self.cards.append(card_instance_id)

    def remove(self, card_instance_id: str) -> None:
        self.cards.remove(card_instance_id)


@dataclass
class DiscardPile:
    cards: list[str] = field(default_factory=list)

    def add(self, card_instance_id: str) -> None:
        self.cards.insert(0, card_instance_id)
