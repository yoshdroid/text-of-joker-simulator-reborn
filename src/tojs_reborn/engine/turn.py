from __future__ import annotations

from .actions import draw_cards
from .events import EventSource
from .rules import opponent_id
from .state import GameState


def start_turn(state: GameState, player_id: str, *, draw_count: int = 1, cp: int = 2) -> None:
    state.turn_player_id = player_id
    turn_event = state.event_store.append(
        "turn_started",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        payload={"draw_count": draw_count, "cp": cp},
    )
    player = state.players[player_id]
    before_cp = player.current_cp
    player.current_cp = cp
    state.event_store.append(
        "cp_set",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=turn_event.event_no,
        payload={"before_cp": before_cp, "after_cp": cp},
    )
    draw_cards(
        state,
        player_id,
        draw_count,
        cause_event_no=turn_event.event_no,
        source=EventSource(),
    )


def end_turn(state: GameState, player_id: str) -> None:
    if state.turn_player_id != player_id:
        raise ValueError(f"not turn player: {player_id}")
    state.event_store.append(
        "turn_ended",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
    )
    if player_id == "P2":
        state.round_no += 1
    state.turn_no += 1
    state.turn_player_id = opponent_id(player_id)

