from __future__ import annotations

from .events import EventSource, FactEvent
from .rules import MAX_HAND_SIZE, get_unit_base_bp, get_unit_bp, opponent_id
from .resolver import AbilityCostChoice, OptionalAbilityChoice, resolve_unit_entered, resolve_unit_overclocked
from .state import AbilityDefinition, GameState, UnitState


def get_effect_handlers():
    return {
        "change_cp": _handle_change_cp,
        "deal_damage_to_unit": _handle_deal_damage_to_unit,
        "deal_damage_to_units": _handle_deal_damage_to_units,
        "deal_life_damage": _handle_deal_life_damage,
        "discard_from_hand": _handle_discard_from_hand,
        "destroy_trigger_zone_card": _handle_destroy_trigger_zone_card,
        "destroy_unit": _handle_destroy_unit,
        "draw_card_by_category": _handle_draw_card_by_category,
        "draw_cards": _handle_draw_cards,
        "modify_base_bp": _handle_modify_base_bp,
        "modify_bp": _handle_modify_bp,
        "move_discard_to_hand": _handle_move_discard_to_hand,
        "move_random_discard_to_hand": _handle_move_random_discard_to_hand,
        "recover_action": _handle_recover_action,
        "return_unit_to_hand": _handle_return_unit_to_hand,
    }


def draw_cards(
    state: GameState,
    player_id: str,
    count: int,
    *,
    cause_event_no: int | None = None,
    source: EventSource | None = None,
) -> list[str]:
    player = state.players[player_id]
    drawn: list[str] = []
    for _ in range(count):
        if not player.deck.cards:
            _refresh_deck(state, player_id, cause_event_no=cause_event_no, source=source)
        card_instance_id = player.deck.draw_top()
        if card_instance_id is None:
            break
        player.hand.add(card_instance_id)
        drawn.append(card_instance_id)
        instance = state.card_instances[card_instance_id]
        state.event_store.append(
            "card_moved",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=player_id,
            cause_event_no=cause_event_no,
            source=EventSource(
                card_no=instance.card_no,
                card_instance_id=card_instance_id,
            ),
            payload={
                "from_zone": "deck",
                "to_zone": "hand",
                "owner_player_id": player_id,
            },
        )
    state.event_store.append(
        "cards_drawn",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=source or EventSource(),
        payload={
            "count": len(drawn),
            "card_instance_ids": drawn,
        },
    )
    return drawn


def _refresh_deck(
    state: GameState,
    player_id: str,
    *,
    cause_event_no: int | None,
    source: EventSource | None,
) -> None:
    player = state.players[player_id]
    if player.deck.cards:
        return
    before_discard = list(player.discard_pile.cards)
    refreshed_cards: list[str] = []
    if player.initial_deck_card_nos:
        card_nos = list(player.initial_deck_card_nos)
        state.rng.shuffle(card_nos)
        for card_no in card_nos:
            refreshed_cards.append(state.create_card_instance(card_no, player_id).instance_id)
    elif player.discard_pile.cards:
        refreshed_cards = list(player.discard_pile.cards)
        state.rng.shuffle(refreshed_cards)
    else:
        return
    player.discard_pile.cards = []
    player.deck.cards = refreshed_cards
    state.event_store.append(
        "deck_refreshed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=source or EventSource(),
        payload={
            "from_discard_card_instance_ids": before_discard,
            "initial_deck_card_nos": list(player.initial_deck_card_nos),
            "deck_card_instance_ids": list(refreshed_cards),
        },
    )


def drive_unit(
    state: GameState,
    player_id: str,
    card_instance_id: str,
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> UnitState:
    player = state.players[player_id]
    instance = state.card_instances[card_instance_id]
    card = state.card_catalog[instance.card_no]
    if card.category != "unit":
        raise ValueError(f"cannot drive non-unit card: {instance.card_no}")
    if state.turn_player_id != player_id:
        raise ValueError(f"not turn player: {player_id}")
    cost = card.cp or 0
    if player.current_cp < cost:
        raise ValueError(f"not enough CP: required={cost} current={player.current_cp}")

    action_event = state.event_store.append(
        "action_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
        payload={"action": "drive_unit", "card_instance_id": card_instance_id},
    )
    if cost > 0:
        before_cp = player.current_cp
        player.current_cp -= cost
        state.event_store.append(
            "cp_changed",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=player_id,
            cause_event_no=action_event.event_no,
            source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
            payload={
                "before_cp": before_cp,
                "after_cp": player.current_cp,
                "amount": -cost,
                "reason": "drive_unit",
            },
        )
    player.hand.remove(card_instance_id)
    unit = state.create_unit(card_instance_id)
    player.battlefield.add(unit.unit_id)
    move_event = state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=EventSource(
            card_no=unit.card_no,
            card_instance_id=card_instance_id,
            unit_id=unit.unit_id,
        ),
        payload={
            "from_zone": "hand",
            "to_zone": "battlefield",
            "owner_player_id": player_id,
        },
    )
    enter_event = state.event_store.append(
        "unit_entered",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=move_event.event_no,
        source=EventSource(
            card_no=unit.card_no,
            card_instance_id=card_instance_id,
            unit_id=unit.unit_id,
        ),
        payload={"owner_player_id": player_id},
    )
    resolve_unit_entered(state, unit, enter_event, get_effect_handlers(), optional_ability_choice, ability_cost_choice)
    if unit.level >= 3:
        _resolve_drive_overclock(state, unit, enter_event.event_no, optional_ability_choice, ability_cost_choice)
    return unit


def override_card(
    state: GameState,
    player_id: str,
    target_card_instance_id: str,
    material_card_instance_id: str,
) -> None:
    player = state.players[player_id]
    target = state.card_instances[target_card_instance_id]
    material = state.card_instances[material_card_instance_id]
    if target_card_instance_id not in player.hand.cards:
        raise ValueError(f"target card is not in hand: {target_card_instance_id}")
    if material_card_instance_id not in player.hand.cards:
        raise ValueError(f"material card is not in hand: {material_card_instance_id}")
    if target.card_no != material.card_no:
        raise ValueError("override requires the same card number")
    if target.level >= 3:
        raise ValueError("target card is already level 3")
    action_event = state.event_store.append(
        "action_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        source=EventSource(card_no=target.card_no, card_instance_id=target_card_instance_id),
        payload={
            "action": "override_card",
            "target_card_instance_id": target_card_instance_id,
            "material_card_instance_id": material_card_instance_id,
        },
    )
    player.hand.remove(material_card_instance_id)
    material.level = 1
    player.discard_pile.add(material_card_instance_id)
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=EventSource(card_no=material.card_no, card_instance_id=material_card_instance_id),
        payload={
            "from_zone": "hand",
            "to_zone": "discard_pile",
            "owner_player_id": player_id,
            "reason": "override_material",
        },
    )
    before_level = target.level
    target.level += 1
    state.event_store.append(
        "card_level_changed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=EventSource(card_no=target.card_no, card_instance_id=target_card_instance_id),
        payload={"before_level": before_level, "after_level": target.level, "zone": "hand"},
    )


def set_trigger(state: GameState, player_id: str, card_instance_id: str) -> None:
    player = state.players[player_id]
    instance = state.card_instances[card_instance_id]
    action_event = state.event_store.append(
        "action_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
        payload={"action": "set_trigger", "card_instance_id": card_instance_id},
    )
    player.hand.remove(card_instance_id)
    player.trigger_zone.add(card_instance_id)
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
        payload={
            "from_zone": "hand",
            "to_zone": "trigger_zone",
            "owner_player_id": player_id,
            "public_color": state.card_catalog[instance.card_no].color,
        },
    )


def overclock_unit(
    state: GameState,
    player_id: str,
    card_instance_id: str,
    target_unit_id: str,
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> UnitState:
    raise ValueError(
        "battlefield unit override is not supported; use override_card on cards in hand, then drive a level 3 card"
    )


def _resolve_drive_overclock(
    state: GameState,
    unit: UnitState,
    cause_event_no: int,
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
) -> None:
    overclock_event = state.event_store.append(
        "unit_overclocked",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=cause_event_no,
        source=EventSource(card_no=unit.card_no, card_instance_id=unit.card_instance_id, unit_id=unit.unit_id),
        payload={"level": unit.level, "reason": "drive_level_3"},
    )
    if unit.exhausted:
        unit.exhausted = False
        state.event_store.append(
            "unit_action_recovered",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=unit.owner_player_id,
            cause_event_no=overclock_event.event_no,
            source=EventSource(card_no=unit.card_no, card_instance_id=unit.card_instance_id, unit_id=unit.unit_id),
            payload={"unit_id": unit.unit_id, "reason": "overclock"},
        )
    resolve_unit_overclocked(state, unit, overclock_event, get_effect_handlers(), optional_ability_choice, ability_cost_choice)


def deal_damage_to_unit(
    state: GameState,
    source_unit: UnitState,
    target_unit: UnitState,
    amount: int,
    *,
    cause_event_no: int,
    source: EventSource,
    reason: str = "effect",
) -> None:
    before_damage = target_unit.current_damage
    target_unit.current_damage += amount
    damage_event = state.event_store.append(
        "damage_dealt",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=source_unit.owner_player_id,
        cause_event_no=cause_event_no,
        source=source,
        payload={
            "target_unit_id": target_unit.unit_id,
            "before_damage": before_damage,
            "after_damage": target_unit.current_damage,
            "amount": amount,
            "reason": reason,
        },
    )
    if target_unit.current_damage >= get_unit_bp(state, target_unit):
        from .combat import destroy_lethal_units

        destroy_lethal_units(state, [target_unit], damage_event.event_no)


def change_cp(
    state: GameState,
    player_id: str,
    amount: int,
    *,
    cause_event_no: int,
    source: EventSource,
    reason: str = "effect",
) -> None:
    player = state.players[player_id]
    before_cp = player.current_cp
    player.current_cp += amount
    state.event_store.append(
        "cp_changed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=source,
        payload={
            "before_cp": before_cp,
            "after_cp": player.current_cp,
            "amount": amount,
            "reason": reason,
        },
    )


def _handle_draw_cards(
    state: GameState,
    unit: UnitState,
    _ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    draw_cards(
        state,
        unit.owner_player_id,
        int(step.get("count", 0)),
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
    )


def _handle_discard_from_hand(
    state: GameState,
    unit: UnitState,
    _ability: AbilityDefinition,
    ability_event: FactEvent,
    _step: dict,
) -> None:
    target_player_id = opponent_id(unit.owner_player_id)
    target_player = state.players[target_player_id]
    if not target_player.hand.cards:
        return
    candidates = list(target_player.hand.cards)
    chosen_index = state.rng.randrange(len(candidates))
    chosen_card_instance_id = target_player.hand.cards.pop(chosen_index)
    chosen_instance = state.card_instances[chosen_card_instance_id]
    random_event = state.event_store.append(
        "random_resolved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "kind": "hand_card",
            "seed": state.seed,
            "player_id": target_player_id,
            "candidate_card_instance_ids": candidates,
            "chosen_index": chosen_index,
            "chosen_card_instance_id": chosen_card_instance_id,
        },
    )
    target_player.discard_pile.add(chosen_card_instance_id)
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=target_player_id,
        cause_event_no=random_event.event_no,
        source=EventSource(
            card_no=chosen_instance.card_no,
            card_instance_id=chosen_card_instance_id,
        ),
        payload={
            "from_zone": "hand",
            "to_zone": "discard_pile",
            "owner_player_id": target_player_id,
            "reason": "effect",
        },
    )


def _handle_deal_damage_to_unit(
    state: GameState,
    unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    target = _resolve_unit_target_for_effect(state, unit, ability, ability_event, step.get("target"))
    if target is None:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    deal_damage_to_unit(
        state,
        unit,
        target,
        int(step.get("amount", 0)),
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
    )


def _handle_deal_damage_to_units(
    state: GameState,
    unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    targets = _resolve_unit_targets_for_effect(state, unit, ability, ability_event, step.get("target"))
    if not targets:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    for target in list(targets):
        if target.unit_id not in state.units:
            continue
        deal_damage_to_unit(
            state,
            unit,
            target,
            int(step.get("amount", 0)),
            cause_event_no=ability_event.event_no,
            source=ability_event.source,
        )


def _handle_deal_life_damage(
    state: GameState,
    unit: UnitState,
    _ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    target_player_id = _resolve_player_id(unit.owner_player_id, step.get("player"))
    player = state.players[target_player_id]
    amount = int(step.get("amount", 0))
    before_life = player.life
    player.life -= amount
    state.event_store.append(
        "life_changed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "player_id": target_player_id,
            "before_life": before_life,
            "after_life": player.life,
            "amount": -amount,
            "reason": "effect",
        },
    )


def _handle_change_cp(
    state: GameState,
    unit: UnitState,
    _ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    change_cp(
        state,
        _resolve_player_id(unit.owner_player_id, step.get("player")),
        int(step.get("amount", 0)),
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
    )


def _handle_modify_bp(
    state: GameState,
    unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    target = _resolve_unit_target_for_effect(state, unit, ability, ability_event, step.get("target"))
    if target is None:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    amount = int(step.get("amount", 0))
    before_bp = get_unit_bp(state, target)
    target.bp_modifiers.append(
        {
            "amount": amount,
            "duration": step.get("duration", "turn"),
            "source_event_no": ability_event.event_no,
        }
    )
    state.event_store.append(
        "bp_modified",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "target_unit_id": target.unit_id,
            "before_bp": before_bp,
            "after_bp": get_unit_bp(state, target),
            "amount": amount,
            "duration": step.get("duration", "turn"),
        },
    )


def _handle_modify_base_bp(
    state: GameState,
    unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    target = _resolve_unit_target_for_effect(state, unit, ability, ability_event, step.get("target"))
    if target is None:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    amount = int(step.get("amount", 0))
    before_bp = get_unit_base_bp(state, target)
    target.base_bp_modifiers.append(
        {
            "amount": amount,
            "duration": step.get("duration", "permanent"),
            "source_event_no": ability_event.event_no,
        }
    )
    state.event_store.append(
        "base_bp_modified",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "target_unit_id": target.unit_id,
            "before_base_bp": before_bp,
            "after_base_bp": get_unit_base_bp(state, target),
            "amount": amount,
            "duration": step.get("duration", "permanent"),
        },
    )


def _handle_recover_action(
    state: GameState,
    unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    target = _resolve_unit_target_for_effect(state, unit, ability, ability_event, step.get("target"))
    if target is None:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    if not target.exhausted:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "target_not_exhausted")
        return
    target.exhausted = False
    state.event_store.append(
        "unit_action_recovered",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={"unit_id": target.unit_id, "reason": "effect"},
    )


def _handle_move_random_discard_to_hand(
    state: GameState,
    unit: UnitState,
    _ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    player_id = _resolve_player_id(unit.owner_player_id, step.get("player"))
    player = state.players[player_id]
    category = step.get("category")
    candidates = [
        card_instance_id
        for card_instance_id in player.discard_pile.cards
        if category is None or state.card_catalog[state.card_instances[card_instance_id].card_no].category == category
    ]
    if not candidates:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    chosen_index = state.rng.randrange(len(candidates))
    chosen_card_instance_id = candidates[chosen_index]
    chosen_instance = state.card_instances[chosen_card_instance_id]
    random_event = state.event_store.append(
        "random_resolved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "kind": "discard_pile_card",
            "seed": state.seed,
            "player_id": player_id,
            "candidate_card_instance_ids": candidates,
            "chosen_index": chosen_index,
            "chosen_card_instance_id": chosen_card_instance_id,
            "category": category,
        },
    )
    player.discard_pile.cards.remove(chosen_card_instance_id)
    player.hand.add(chosen_card_instance_id)
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=random_event.event_no,
        source=EventSource(card_no=chosen_instance.card_no, card_instance_id=chosen_card_instance_id),
        payload={
            "from_zone": "discard_pile",
            "to_zone": "hand",
            "owner_player_id": player_id,
            "reason": "effect",
            "category": category,
        },
    )


def _handle_move_discard_to_hand(
    state: GameState,
    unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    selector = ability.raw.get("selector")
    if not isinstance(selector, dict):
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "selector_missing")
        return
    player_id = _resolve_player_id(unit.owner_player_id, selector.get("controller"))
    player = state.players[player_id]
    category = selector.get("category")
    candidates = [
        card_instance_id
        for card_instance_id in player.discard_pile.cards
        if category is None or state.card_catalog[state.card_instances[card_instance_id].card_no].category == category
    ]
    if not candidates:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    request_event = state.event_store.append(
        "choice_requested",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "choice_id": selector.get("id"),
            "type": "card",
            "candidate_card_instance_ids": candidates,
            "required": bool(selector.get("required", True)),
            "zone": "discard_pile",
        },
    )
    chosen_card_instance_id = candidates[0]
    state.event_store.append(
        "choice_selected",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=request_event.event_no,
        source=ability_event.source,
        payload={
            "choice_id": selector.get("id"),
            "chosen_card_instance_id": chosen_card_instance_id,
            "fallback": "first_legal",
        },
    )
    player.discard_pile.cards.remove(chosen_card_instance_id)
    player.hand.add(chosen_card_instance_id)
    chosen_instance = state.card_instances[chosen_card_instance_id]
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=request_event.event_no,
        source=EventSource(card_no=chosen_instance.card_no, card_instance_id=chosen_card_instance_id),
        payload={
            "from_zone": "discard_pile",
            "to_zone": "hand",
            "owner_player_id": player_id,
            "reason": "effect",
        },
    )


def _handle_destroy_trigger_zone_card(
    state: GameState,
    unit: UnitState,
    _ability: AbilityDefinition,
    ability_event: FactEvent,
    _step: dict,
) -> None:
    target_player_id = opponent_id(unit.owner_player_id)
    target_player = state.players[target_player_id]
    if not target_player.trigger_zone.cards:
        return
    candidates = list(target_player.trigger_zone.cards)
    chosen_index = state.rng.randrange(len(candidates))
    chosen_card_instance_id = candidates[chosen_index]
    target_player.trigger_zone.remove(chosen_card_instance_id)
    chosen_instance = state.card_instances[chosen_card_instance_id]
    random_event = state.event_store.append(
        "random_resolved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "kind": "trigger_zone_card",
            "seed": state.seed,
            "player_id": target_player_id,
            "candidate_card_instance_ids": candidates,
            "chosen_index": chosen_index,
            "chosen_card_instance_id": chosen_card_instance_id,
        },
    )
    target_player.discard_pile.add(chosen_card_instance_id)
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=target_player_id,
        cause_event_no=random_event.event_no,
        source=EventSource(card_no=chosen_instance.card_no, card_instance_id=chosen_card_instance_id),
        payload={
            "from_zone": "trigger_zone",
            "to_zone": "discard_pile",
            "owner_player_id": target_player_id,
            "reason": "effect",
        },
    )


def _handle_destroy_unit(
    state: GameState,
    unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    target = _resolve_unit_target_for_effect(state, unit, ability, ability_event, step.get("target"))
    if target is None:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    from .combat import destroy_unit

    destroy_unit(state, target, ability_event.event_no, reason="effect")


def _handle_return_unit_to_hand(
    state: GameState,
    unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    target = _resolve_unit_target_for_effect(state, unit, ability, ability_event, step.get("target"))
    if target is None:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "no_valid_target")
        return
    target_player = state.players[target.owner_player_id]
    if target.unit_id not in state.units:
        _append_effect_fizzled(state, unit.owner_player_id, ability_event, step, "target_not_on_battlefield")
        return

    target_player.battlefield.remove(target.unit_id)
    target_instance = state.card_instances[target.card_instance_id]
    before_level = target_instance.level
    target_instance.level = 1
    to_zone = "hand" if len(target_player.hand.cards) < MAX_HAND_SIZE else "discard_pile"
    if to_zone == "hand":
        target_player.hand.add(target.card_instance_id)
    else:
        target_player.discard_pile.add(target.card_instance_id)
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=target.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=EventSource(card_no=target.card_no, card_instance_id=target.card_instance_id, unit_id=target.unit_id),
        payload={
            "from_zone": "battlefield",
            "to_zone": to_zone,
            "owner_player_id": target.owner_player_id,
            "reason": "return_unit",
            "hand_limit": MAX_HAND_SIZE,
            "hand_limit_exceeded": to_zone == "discard_pile",
            "before_level": before_level,
            "after_level": target_instance.level,
        },
    )

    state.event_store.append(
        "unit_returned_to_hand",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "target_unit_id": target.unit_id,
            "target_card_instance_id": target.card_instance_id,
            "owner_player_id": target.owner_player_id,
            "to_zone": to_zone,
        },
    )
    del state.units[target.unit_id]


def _resolve_unit_target(
    state: GameState,
    source_unit: UnitState,
    target_ref,
    selector: dict | None = None,
) -> UnitState | None:
    if target_ref == "source":
        return source_unit
    if isinstance(target_ref, str) and target_ref in state.units:
        return state.units[target_ref]
    if selector is None:
        return source_unit if target_ref in (None, "source") else None
    controller = selector.get("controller")
    if controller == "rival":
        player_id = opponent_id(source_unit.owner_player_id)
    elif controller == "owner":
        player_id = source_unit.owner_player_id
    else:
        player_id = source_unit.owner_player_id
    candidates = _unit_candidates_for_selector(state, player_id, selector)
    return candidates[0] if candidates else None


def _resolve_unit_target_for_effect(
    state: GameState,
    source_unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    target_ref,
) -> UnitState | None:
    selector = ability.raw.get("selector")
    if not isinstance(selector, dict):
        return _resolve_unit_target(state, source_unit, target_ref)
    if target_ref != selector.get("id") or selector.get("type") != "unit":
        return _resolve_unit_target(state, source_unit, target_ref, selector)
    controller = selector.get("controller")
    if controller == "rival":
        player_id = opponent_id(source_unit.owner_player_id)
    elif controller == "owner":
        player_id = source_unit.owner_player_id
    else:
        player_id = source_unit.owner_player_id
    candidates = [unit.unit_id for unit in _unit_candidates_for_selector(state, player_id, selector)]
    if not candidates:
        return None
    request_event = state.event_store.append(
        "choice_requested",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=source_unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "choice_id": selector.get("id"),
            "type": "unit",
            "candidate_unit_ids": candidates,
            "required": bool(selector.get("required", True)),
        },
    )
    chosen_unit_id = candidates[0]
    state.event_store.append(
        "choice_selected",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=source_unit.owner_player_id,
        cause_event_no=request_event.event_no,
        source=ability_event.source,
        payload={
            "choice_id": selector.get("id"),
            "chosen_unit_id": chosen_unit_id,
            "fallback": "first_legal",
        },
    )
    return state.units[chosen_unit_id]


def _resolve_unit_targets_for_effect(
    state: GameState,
    source_unit: UnitState,
    ability: AbilityDefinition,
    _ability_event: FactEvent,
    target_ref,
) -> list[UnitState]:
    selector = ability.raw.get("selector")
    if not isinstance(selector, dict):
        target = _resolve_unit_target(state, source_unit, target_ref)
        return [] if target is None else [target]
    if target_ref != selector.get("id") or selector.get("type") != "unit":
        target = _resolve_unit_target(state, source_unit, target_ref, selector)
        return [] if target is None else [target]
    controller = selector.get("controller")
    if controller == "rival":
        player_id = opponent_id(source_unit.owner_player_id)
    elif controller == "owner":
        player_id = source_unit.owner_player_id
    else:
        player_id = source_unit.owner_player_id
    candidates = _unit_candidates_for_selector(state, player_id, selector)
    count = selector.get("count", 1)
    if count == "all":
        return candidates
    return candidates[: int(count)]


def _unit_candidates_for_selector(state: GameState, player_id: str, selector: dict) -> list[UnitState]:
    candidates = [state.units[unit_id] for unit_id in state.players[player_id].battlefield.units if unit_id in state.units]
    if "exhausted" in selector:
        expected = bool(selector["exhausted"])
        candidates = [unit for unit in candidates if unit.exhausted == expected]
    if "min_level" in selector:
        min_level = int(selector["min_level"])
        candidates = [unit for unit in candidates if unit.level >= min_level]
    if "max_level" in selector:
        max_level = int(selector["max_level"])
        candidates = [unit for unit in candidates if unit.level <= max_level]
    return candidates


def _append_effect_fizzled(
    state: GameState,
    actor_player_id: str,
    ability_event: FactEvent,
    step: dict,
    reason: str,
) -> None:
    state.event_store.append(
        "effect_fizzled",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=actor_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={"effect": step.get("effect"), "reason": reason},
    )


def _resolve_player_id(owner_player_id: str, player_ref) -> str:
    if player_ref == "rival":
        return opponent_id(owner_player_id)
    return owner_player_id


def _clear_unit_damage(state: GameState, unit: UnitState, cause_event_no: int, *, reason: str) -> None:
    if unit.current_damage == 0:
        return
    before_damage = unit.current_damage
    unit.current_damage = 0
    state.event_store.append(
        "unit_damage_cleared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=cause_event_no,
        source=EventSource(card_no=unit.card_no, card_instance_id=unit.card_instance_id, unit_id=unit.unit_id),
        payload={"unit_id": unit.unit_id, "before_damage": before_damage, "after_damage": 0, "reason": reason},
    )

def _handle_draw_card_by_category(
    state: GameState,
    unit: UnitState,
    _ability: AbilityDefinition,
    ability_event: FactEvent,
    step: dict,
) -> None:
    player = state.players[unit.owner_player_id]
    category = step.get("category")
    count = int(step.get("count", 1))
    drawn: list[str] = []
    for _ in range(count):
        if not player.deck.cards:
            _refresh_deck(state, unit.owner_player_id, cause_event_no=ability_event.event_no, source=ability_event.source)
        matched_index = None
        for index, card_instance_id in enumerate(player.deck.cards):
            card_no = state.card_instances[card_instance_id].card_no
            if state.card_catalog[card_no].category == category:
                matched_index = index
                break
        if matched_index is None:
            break
        card_instance_id = player.deck.cards.pop(matched_index)
        player.hand.add(card_instance_id)
        drawn.append(card_instance_id)
        instance = state.card_instances[card_instance_id]
        state.event_store.append(
            "card_moved",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=unit.owner_player_id,
            cause_event_no=ability_event.event_no,
            source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
            payload={
                "from_zone": "deck",
                "to_zone": "hand",
                "owner_player_id": unit.owner_player_id,
                "reason": "effect",
                "category": category,
            },
        )
    state.event_store.append(
        "cards_drawn",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={"count": len(drawn), "card_instance_ids": drawn, "category": category},
    )
