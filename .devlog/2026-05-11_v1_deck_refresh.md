# 2026-05-11 V1 Deck Refresh

## Purpose

Implement V1-E: deck refresh for draw effects.

## Implemented

- Added `AgentInfo.initial_deck_card_nos`.
- `draw_cards` refreshes an empty deck before drawing.
- `draw_card_by_category` refreshes an empty deck before searching.
- Refresh clears discard pile and emits `deck_refreshed`.
- When `initial_deck_card_nos` exists, refresh creates shuffled new card instances from it.
- In ad-hoc test states without initial deck registration, refresh falls back to shuffling discard-pile instances.

## Verification

`python -m unittest -v`

- 37 tests passed.
