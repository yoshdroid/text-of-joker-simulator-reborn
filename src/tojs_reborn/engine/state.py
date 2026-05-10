from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .events import EventStore
from .zones import BattleField, Deck, DiscardPile, Hand, TriggerZone


@dataclass(frozen=True)
class AbilityDefinition:
    ability_id: str
    name: str
    status: str
    timing: str
    optional: bool
    effect_steps: tuple[dict[str, Any], ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class CardDefinition:
    card_no: str
    category: str
    color: str
    name: str
    cp: int | None
    bp_by_level: tuple[int, ...]
    abilities: tuple[AbilityDefinition, ...]


@dataclass(frozen=True)
class CardInstance:
    instance_id: str
    card_no: str
    owner_player_id: str
    level: int = 1


@dataclass
class UnitState:
    unit_id: str
    card_instance_id: str
    card_no: str
    owner_player_id: str
    level: int = 1
    exhausted: bool = False
    current_damage: int = 0
    bp_modifiers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentInfo:
    player_id: str
    life: int = 7
    current_cp: int = 0
    deck: Deck = field(default_factory=Deck)
    hand: Hand = field(default_factory=Hand)
    battlefield: BattleField = field(default_factory=BattleField)
    trigger_zone: TriggerZone = field(default_factory=TriggerZone)
    discard_pile: DiscardPile = field(default_factory=DiscardPile)


@dataclass
class GameState:
    card_catalog: dict[str, CardDefinition]
    players: dict[str, AgentInfo]
    event_store: EventStore = field(default_factory=EventStore)
    card_instances: dict[str, CardInstance] = field(default_factory=dict)
    units: dict[str, UnitState] = field(default_factory=dict)
    round_no: int = 1
    turn_no: int = 1
    turn_player_id: str = "P1"
    next_card_instance_no: int = 1
    next_unit_no: int = 1
    seed: int = 0
    rng: random.Random = field(default_factory=lambda: random.Random(0))

    def create_card_instance(self, card_no: str, owner_player_id: str, level: int = 1) -> CardInstance:
        instance = CardInstance(
            instance_id=f"c{self.next_card_instance_no:04d}",
            card_no=card_no,
            owner_player_id=owner_player_id,
            level=level,
        )
        self.next_card_instance_no += 1
        self.card_instances[instance.instance_id] = instance
        return instance

    def create_unit(self, card_instance_id: str) -> UnitState:
        instance = self.card_instances[card_instance_id]
        unit = UnitState(
            unit_id=f"u{self.next_unit_no:04d}",
            card_instance_id=card_instance_id,
            card_no=instance.card_no,
            owner_player_id=instance.owner_player_id,
            level=instance.level,
        )
        self.next_unit_no += 1
        self.units[unit.unit_id] = unit
        return unit


def load_card_catalog(path: str | Path) -> dict[str, CardDefinition]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    cards: dict[str, CardDefinition] = {}
    for item in data.get("cards", []):
        abilities = tuple(
            AbilityDefinition(
                ability_id=ability["ability_key"],
                name=ability["ability_name"],
                status=ability["status"],
                timing=ability["timing"],
                optional=bool(ability["optional"]),
                effect_steps=tuple(ability.get("effect_steps", [])),
                raw=ability,
            )
            for ability in item.get("abilities", [])
        )
        cards[item["card_no"]] = CardDefinition(
            card_no=item["card_no"],
            category=item["category"],
            color=item["color"],
            name=item["name"],
            cp=item.get("cp"),
            bp_by_level=tuple(item.get("bp_by_level", [])),
            abilities=abilities,
        )
    return cards


def create_game_state(card_catalog: dict[str, CardDefinition], *, seed: int = 0) -> GameState:
    state = GameState(
        card_catalog=card_catalog,
        players={
            "P1": AgentInfo(player_id="P1"),
            "P2": AgentInfo(player_id="P2"),
        },
        seed=seed,
        rng=random.Random(seed),
    )
    return state
