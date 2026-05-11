from __future__ import annotations

from collections.abc import Callable

from .events import EventSource, FactEvent
from .state import AbilityDefinition, GameState, UnitState


EffectHandler = Callable[
    [GameState, UnitState, AbilityDefinition, FactEvent, dict],
    None,
]
OptionalAbilityChoice = Callable[
    [GameState, UnitState, AbilityDefinition, FactEvent],
    bool,
]
AbilityCostChoice = Callable[
    [GameState, UnitState, AbilityDefinition, FactEvent, dict, list[dict]],
    dict,
]


def resolve_unit_entered(
    state: GameState,
    entering_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        entering_unit,
        "SELF_CIP",
        cause_event,
        effect_handlers,
        optional_ability_choice,
        ability_cost_choice,
    )

    owner = state.players[entering_unit.owner_player_id]
    for unit_id in owner.battlefield.units:
        if unit_id == entering_unit.unit_id:
            continue
        _resolve_supported_abilities(
            state,
            state.units[unit_id],
            "YOUR_CIP",
            cause_event,
            effect_handlers,
            optional_ability_choice,
            ability_cost_choice,
        )

    opponent_id = _opponent_id(entering_unit.owner_player_id)
    opponent = state.players[opponent_id]
    for unit_id in opponent.battlefield.units:
        _resolve_supported_abilities(
            state,
            state.units[unit_id],
            "RIVAL_CIP",
            cause_event,
            effect_handlers,
            optional_ability_choice,
            ability_cost_choice,
        )


def resolve_unit_destroyed(
    state: GameState,
    destroyed_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        destroyed_unit,
        "SELF_PIG",
        cause_event,
        effect_handlers,
        optional_ability_choice,
        ability_cost_choice,
    )


def resolve_unit_attacked(
    state: GameState,
    attacking_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        attacking_unit,
        "SELF_ATK",
        cause_event,
        effect_handlers,
        optional_ability_choice,
        ability_cost_choice,
    )


def resolve_unit_blocked(
    state: GameState,
    blocking_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        blocking_unit,
        "SELF_BLOCK",
        cause_event,
        effect_handlers,
        optional_ability_choice,
        ability_cost_choice,
    )


def resolve_turn_ended(
    state: GameState,
    player_id: str,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    for unit_id in list(state.players[player_id].battlefield.units):
        if unit_id in state.units:
            _resolve_supported_abilities(
                state,
                state.units[unit_id],
                "SELF_TURN_END",
                cause_event,
                effect_handlers,
                optional_ability_choice,
                ability_cost_choice,
            )


def resolve_unit_overclocked(
    state: GameState,
    unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        unit,
        "SELF_OC",
        cause_event,
        effect_handlers,
        optional_ability_choice,
        ability_cost_choice,
    )


def _resolve_supported_abilities(
    state: GameState,
    ability_source_unit: UnitState,
    timing: str,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    card = state.card_catalog[ability_source_unit.card_no]
    for ability in card.abilities:
        if ability.status != "supported" or ability.timing != timing:
            continue
        if not _condition_matches(state, ability_source_unit, ability):
            continue
        if ability.optional and not _choose_optional_ability(
            state,
            ability_source_unit,
            ability,
            cause_event,
            optional_ability_choice,
        ):
            continue
        cost_event_nos = _pay_cost_steps(state, ability_source_unit, ability, cause_event, ability_cost_choice)
        if cost_event_nos is None:
            continue
        ability_event = state.event_store.append(
            "ability_resolved",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=ability_source_unit.owner_player_id,
            cause_event_no=cause_event.event_no,
            source=EventSource(
                card_no=ability_source_unit.card_no,
                card_instance_id=ability_source_unit.card_instance_id,
                unit_id=ability_source_unit.unit_id,
                ability_id=ability.ability_id,
            ),
            payload={
                "ability_name": ability.name,
                "timing": ability.timing,
                "optional": ability.optional,
                "cost_event_nos": cost_event_nos,
            },
        )
        for step in ability.effect_steps:
            handler = effect_handlers.get(str(step.get("effect")))
            if handler is not None:
                handler(state, ability_source_unit, ability, ability_event, step)


def _choose_optional_ability(
    state: GameState,
    ability_source_unit: UnitState,
    ability: AbilityDefinition,
    cause_event: FactEvent,
    optional_ability_choice: OptionalAbilityChoice | None,
) -> bool:
    request_event = state.event_store.append(
        "choice_requested",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=ability_source_unit.owner_player_id,
        cause_event_no=cause_event.event_no,
        source=EventSource(
            card_no=ability_source_unit.card_no,
            card_instance_id=ability_source_unit.card_instance_id,
            unit_id=ability_source_unit.unit_id,
            ability_id=ability.ability_id,
        ),
        payload={
            "type": "optional_ability",
            "ability_id": ability.ability_id,
            "ability_name": ability.name,
            "legal_choices": [
                {"type": "pass_ability", "ability_id": ability.ability_id},
                {"type": "use_ability", "ability_id": ability.ability_id},
            ],
        },
    )
    use_ability = bool(optional_ability_choice(state, ability_source_unit, ability, request_event)) if optional_ability_choice else False
    state.event_store.append(
        "choice_selected",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=ability_source_unit.owner_player_id,
        cause_event_no=request_event.event_no,
        source=EventSource(
            card_no=ability_source_unit.card_no,
            card_instance_id=ability_source_unit.card_instance_id,
            unit_id=ability_source_unit.unit_id,
            ability_id=ability.ability_id,
        ),
        payload={
            "type": "optional_ability",
            "ability_id": ability.ability_id,
            "choice": "use_ability" if use_ability else "pass_ability",
            "fallback": "pass_ability" if optional_ability_choice is None else None,
        },
    )
    return use_ability


def _pay_cost_steps(
    state: GameState,
    ability_source_unit: UnitState,
    ability: AbilityDefinition,
    cause_event: FactEvent,
    ability_cost_choice: AbilityCostChoice | None,
) -> list[int] | None:
    paid_event_nos: list[int] = []
    for step in ability.raw.get("cost_steps", []):
        if not isinstance(step, dict):
            return None
        effect = step.get("effect")
        if effect != "discard_from_hand":
            return None
        event_no = _pay_discard_from_hand_cost(state, ability_source_unit, ability, cause_event, step, ability_cost_choice)
        if event_no is None:
            state.event_store.append(
                "ability_cost_failed",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=ability_source_unit.owner_player_id,
                cause_event_no=cause_event.event_no,
                source=EventSource(
                    card_no=ability_source_unit.card_no,
                    card_instance_id=ability_source_unit.card_instance_id,
                    unit_id=ability_source_unit.unit_id,
                    ability_id=ability.ability_id,
                ),
                payload={"effect": effect, "reason": "cost_unpayable"},
            )
            return None
        paid_event_nos.append(event_no)
    return paid_event_nos


def _pay_discard_from_hand_cost(
    state: GameState,
    ability_source_unit: UnitState,
    ability: AbilityDefinition,
    cause_event: FactEvent,
    step: dict,
    ability_cost_choice: AbilityCostChoice | None,
) -> int | None:
    player_id = ability_source_unit.owner_player_id if step.get("player", "owner") == "owner" else _opponent_id(ability_source_unit.owner_player_id)
    player = state.players[player_id]
    count = int(step.get("count", 1))
    if count <= 0:
        return None
    legal_choices = [{"card_instance_id": card_instance_id} for card_instance_id in player.hand.cards]
    if len(legal_choices) < count:
        return None
    request_event = state.event_store.append(
        "choice_requested",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=ability_source_unit.owner_player_id,
        cause_event_no=cause_event.event_no,
        source=EventSource(
            card_no=ability_source_unit.card_no,
            card_instance_id=ability_source_unit.card_instance_id,
            unit_id=ability_source_unit.unit_id,
            ability_id=ability.ability_id,
        ),
        payload={
            "type": "cost_payment",
            "effect": "discard_from_hand",
            "player_id": player_id,
            "count": count,
            "legal_choices": legal_choices,
        },
    )
    selected = (
        ability_cost_choice(state, ability_source_unit, ability, request_event, step, legal_choices)
        if ability_cost_choice
        else _fallback_cost_choice(legal_choices, count)
    )
    selected_ids = _selected_cost_card_instance_ids(selected)
    if len(selected_ids) != count or len(set(selected_ids)) != count or any(card_id not in player.hand.cards for card_id in selected_ids):
        selected = _fallback_cost_choice(legal_choices, count)
        selected_ids = _selected_cost_card_instance_ids(selected)
    state.event_store.append(
        "choice_selected",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=ability_source_unit.owner_player_id,
        cause_event_no=request_event.event_no,
        source=EventSource(
            card_no=ability_source_unit.card_no,
            card_instance_id=ability_source_unit.card_instance_id,
            unit_id=ability_source_unit.unit_id,
            ability_id=ability.ability_id,
        ),
        payload={
            "type": "cost_payment",
            "effect": "discard_from_hand",
            "choice": selected,
        },
    )
    moved_ids = []
    for card_instance_id in selected_ids:
        player.hand.remove(card_instance_id)
        player.discard_pile.add(card_instance_id)
        moved_ids.append(card_instance_id)
        instance = state.card_instances[card_instance_id]
        state.event_store.append(
            "card_moved",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=player_id,
            cause_event_no=request_event.event_no,
            source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
            payload={
                "from_zone": "hand",
                "to_zone": "discard_pile",
                "owner_player_id": player_id,
                "reason": "ability_cost",
            },
        )
    paid_event = state.event_store.append(
        "ability_cost_paid",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=ability_source_unit.owner_player_id,
        cause_event_no=request_event.event_no,
        source=EventSource(
            card_no=ability_source_unit.card_no,
            card_instance_id=ability_source_unit.card_instance_id,
            unit_id=ability_source_unit.unit_id,
            ability_id=ability.ability_id,
        ),
        payload={"effect": "discard_from_hand", "card_instance_ids": moved_ids},
    )
    return paid_event.event_no


def _fallback_cost_choice(legal_choices: list[dict], count: int) -> dict:
    selected_ids = [choice["card_instance_id"] for choice in legal_choices[:count]]
    if count == 1:
        return {"card_instance_id": selected_ids[0]}
    return {"card_instance_ids": selected_ids}


def _selected_cost_card_instance_ids(selected: dict) -> list[str]:
    if isinstance(selected.get("card_instance_id"), str):
        return [selected["card_instance_id"]]
    if isinstance(selected.get("card_instance_ids"), list):
        return [card_id for card_id in selected["card_instance_ids"] if isinstance(card_id, str)]
    return []


def _condition_matches(state: GameState, ability_source_unit: UnitState, ability: AbilityDefinition) -> bool:
    condition = ability.raw.get("condition")
    if condition is None:
        return True
    if not isinstance(condition, dict):
        return False
    if condition.get("type") != "used_other_card_this_turn":
        return False
    min_cp = int(condition.get("min_cp", 0))
    color = condition.get("color")
    for event in state.event_store.events:
        if event.turn_no != state.turn_no or event.type != "action_declared":
            continue
        if event.payload.get("action") != "drive_unit":
            continue
        if event.actor_player_id != ability_source_unit.owner_player_id:
            continue
        if condition.get("exclude_source") and event.source.card_instance_id == ability_source_unit.card_instance_id:
            continue
        if event.source.card_no is None:
            continue
        card = state.card_catalog[event.source.card_no]
        if (card.cp or 0) >= min_cp and (color is None or card.color == color):
            return True
    return False


def _opponent_id(player_id: str) -> str:
    return "P2" if player_id == "P1" else "P1"
