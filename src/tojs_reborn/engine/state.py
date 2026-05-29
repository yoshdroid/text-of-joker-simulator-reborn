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
    race: str = ""


@dataclass(frozen=True)
class JokerDefinition:
    joker_no: str
    name: str
    cp: int
    speed: int
    ability_text: str


DEFAULT_JOKER_NO = "JK-01"


@dataclass
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
    attack_restricted_turn_no: int | None = None
    current_damage: int = 0
    base_bp_modifiers: list[dict[str, Any]] = field(default_factory=list)
    bp_modifiers: list[dict[str, Any]] = field(default_factory=list)
    stacked_card_instance_ids: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class AgentInfo:
    player_id: str
    life: int = 7
    current_cp: int = 0
    joker_no: str = DEFAULT_JOKER_NO
    joker_gauge: int = 0
    joker_granted: bool = False
    initial_deck_card_nos: list[str] = field(default_factory=list)
    deck: Deck = field(default_factory=Deck)
    hand: Hand = field(default_factory=Hand)
    battlefield: BattleField = field(default_factory=BattleField)
    trigger_zone: TriggerZone = field(default_factory=TriggerZone)
    discard_pile: DiscardPile = field(default_factory=DiscardPile)


@dataclass
class GameState:
    card_catalog: dict[str, CardDefinition]
    joker_catalog: dict[str, JokerDefinition]
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
    pending_destroyed_units: dict[str, dict[str, Any]] = field(default_factory=dict)
    suppressed_battle_event_nos: set[int] = field(default_factory=set)

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
            stacked_card_instance_ids=[card_instance_id],
            keywords=_printed_keywords(self.card_catalog[instance.card_no]),
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
            race=item.get("race", ""),
        )
    return cards


def load_joker_catalog(path: str | Path) -> dict[str, JokerDefinition]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    jokers: dict[str, JokerDefinition] = {}
    for item in data.get("jokers", []):
        jokers[item["joker_no"]] = JokerDefinition(
            joker_no=item["joker_no"],
            name=item["name"],
            cp=int(item["cp"]),
            speed=int(item["speed"]),
            ability_text=item.get("ability_text", ""),
        )
    if DEFAULT_JOKER_NO not in jokers:
        jokers[DEFAULT_JOKER_NO] = default_joker_definition()
    return jokers


def default_joker_definition() -> JokerDefinition:
    return JokerDefinition(
        joker_no=DEFAULT_JOKER_NO,
        name="\u30af\u30ea\u30e0\u30be\u30f3\u30d6\u30ec\u30a4\u30af",
        cp=5,
        speed=3,
        ability_text="\u5bfe\u6226\u76f8\u624b\u306e\u5168\u3066\u306e\u30e6\u30cb\u30c3\u30c8\u306b5000\u30c0\u30e1\u30fc\u30b8\u3092\u4e0e\u3048\u308b",
    )


def create_game_state(
    card_catalog: dict[str, CardDefinition],
    *,
    joker_catalog: dict[str, JokerDefinition] | None = None,
    seed: int = 0,
) -> GameState:
    active_joker_catalog = dict(joker_catalog or {})
    if DEFAULT_JOKER_NO not in active_joker_catalog:
        active_joker_catalog[DEFAULT_JOKER_NO] = default_joker_definition()
    state = GameState(
        card_catalog=card_catalog,
        joker_catalog=active_joker_catalog,
        players={
            "P1": AgentInfo(player_id="P1"),
            "P2": AgentInfo(player_id="P2"),
        },
        seed=seed,
        rng=random.Random(seed),
    )
    return state


def _printed_keywords(card: CardDefinition) -> list[str]:
    keywords = []
    for ability in card.abilities:
        if ability.name == "\u4e0d\u5c48" and "indomitable" not in keywords:
            keywords.append("indomitable")
        if ability.timing != "PASSIVE":
            continue
        if ability.name == "\u4e0d\u5c48" and "indomitable" not in keywords:
            keywords.append("indomitable")
        for step in ability.effect_steps:
            if step.get("effect") == "grant_keyword":
                keyword = str(step.get("keyword", ""))
                if keyword and keyword not in keywords:
                    keywords.append(keyword)
    return keywords
