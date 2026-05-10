# 2026-05-11 M5 Destroyed Abilities

## Purpose

Start M5 by adding real `SELF_PIG` cards to verify destroyed ability ordering.

Added:

- `1-0-027` ミイラくん
  - `SELF_PIG`
  - discard one random opponent hand card
- `1-0-029` カラスマドウ
  - `SELF_PIG`
  - draw one intercept card

## Implementation Notes

The battle destruction flow now gathers all lethally damaged units first, then resolves destruction in priority order.

Current priority:

1. turn player's destroyed units
2. non-turn player's destroyed units

For each destroyed unit:

1. move battlefield -> discard pile
2. emit `unit_destroyed`
3. resolve supported `SELF_PIG`
4. remove the unit from `state.units`

This is enough to verify the first important ordering case: turn player PIG before opponent PIG.

## Verification

`python -m unittest -v`

- 14 tests passed.

Important test:

- `test_simultaneous_destroyed_self_pig_resolves_turn_player_first`

It verifies that P1 ミイラくん resolves before P2 カラスマドウ when both are destroyed in the same battle.

## Remaining Follow-ups

- true random selection from multiple legal cards
- stronger replay support for `random_resolved`
- PIG ordering within multiple destroyed units on the same side
- `YOUR_PIG` / `RIVAL_PIG`
- death-trigger windows interacting with other queued events

