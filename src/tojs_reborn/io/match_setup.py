from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tojs_reborn.engine.state import (
    CardDefinition,
    GameState,
    JokerDefinition,
    create_game_state,
    load_card_catalog,
    load_joker_catalog,
)

from .decklist import Decklist, load_decklist


@dataclass(frozen=True)
class MatchSetupConfig:
    seed: int = 0
    initial_life: int = 7
    initial_hand_size: int = 4
    first_player_id: str = "P1"
    shuffle_deck: bool = True


def setup_match_state(
    card_catalog: dict[str, CardDefinition],
    decklists: dict[str, Decklist],
    *,
    joker_catalog: dict[str, JokerDefinition] | None = None,
    config: MatchSetupConfig | None = None,
) -> GameState:
    config = config or MatchSetupConfig()
    state = create_game_state(card_catalog, joker_catalog=joker_catalog, seed=config.seed)
    state.turn_player_id = config.first_player_id
    for player_id, decklist in decklists.items():
        if player_id not in state.players:
            raise ValueError(f"unknown player_id: {player_id}")
        _register_decklist(state, player_id, decklist, config)
    return state


def setup_match_state_from_files(
    *,
    cards_path: str | Path,
    deck1_path: str | Path,
    deck2_path: str | Path,
    config: MatchSetupConfig | None = None,
    strict_deck_rule: bool = False,
) -> GameState:
    card_catalog = load_card_catalog(cards_path)
    joker_catalog = load_joker_catalog(cards_path)
    deck1 = load_decklist(deck1_path, card_catalog, strict_deck_rule=strict_deck_rule)
    deck2 = load_decklist(deck2_path, card_catalog, strict_deck_rule=strict_deck_rule)
    return setup_match_state(card_catalog, {"P1": deck1, "P2": deck2}, joker_catalog=joker_catalog, config=config)


def _register_decklist(
    state: GameState,
    player_id: str,
    decklist: Decklist,
    config: MatchSetupConfig,
) -> None:
    player = state.players[player_id]
    expanded_card_nos = decklist.expanded_card_nos()
    player.life = config.initial_life
    player.current_cp = 0
    if decklist.joker_no not in state.joker_catalog:
        raise ValueError(f"unknown joker_no: {decklist.joker_no}")
    player.joker_no = decklist.joker_no
    player.joker_gauge = 0
    player.joker_granted = False
    player.initial_deck_card_nos = list(expanded_card_nos)

    deck_card_nos = list(expanded_card_nos)
    if config.shuffle_deck:
        state.rng.shuffle(deck_card_nos)
    for card_no in deck_card_nos:
        instance = state.create_card_instance(card_no, player_id)
        player.deck.cards.append(instance.instance_id)

    for _ in range(min(config.initial_hand_size, len(player.deck.cards))):
        card_instance_id = player.deck.draw_top()
        if card_instance_id is not None:
            player.hand.add(card_instance_id)
