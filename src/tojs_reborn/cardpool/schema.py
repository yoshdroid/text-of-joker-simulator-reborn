from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExcelAbility:
    name: str
    text: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExcelCard:
    card_no: str
    category: str
    rarity: str
    color: str
    name: str
    race: str
    cp: int | None
    bp_by_level: tuple[int, ...]
    abilities: tuple[ExcelAbility, ...]


@dataclass(frozen=True)
class ExcelJoker:
    joker_no: str
    name: str
    cp: int
    speed: int
    ability_text: str


@dataclass(frozen=True)
class NormalizationIssue:
    severity: str
    code: str
    message: str
    card_no: str | None = None
    ability_key: str | None = None
