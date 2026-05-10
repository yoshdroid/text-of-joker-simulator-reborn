# 2026-05-11 Engine M2 Start

## Purpose

Start implementing the simulator engine, not just cardpool utilities.

This slice focuses on the smallest executable engine loop that can prove the event-first design:

- create game state
- move cards between zones
- drive a unit from hand to battlefield
- emit ordered fact events
- resolve the supported Happaloid `SELF_CIP -> draw_cards` ability
- expose a small demo command that prints the event log as JSON

## Scope

In scope:

- `EventStore`
- basic zones
- `GameState`, `AgentInfo`, `CardInstance`, `UnitState`
- card catalog loading from normalized card data
- `draw_cards`
- `drive_unit`
- minimal supported ability resolver for `draw_cards`
- tests for event ordering and Happaloid behavior

Out of scope:

- battle
- CP costs
- legal action generation
- trigger/intercept windows
- child process communication
- replay file format

## Design Notes

`SELF_CIP` is treated as source-only. Existing Happaloids on either side do not trigger their own `SELF_CIP` when another unit enters.

All state changes in this slice are paired with events.

## Implemented Files

- `src/tojs_reborn/engine/events.py`
- `src/tojs_reborn/engine/zones.py`
- `src/tojs_reborn/engine/state.py`
- `src/tojs_reborn/engine/actions.py`
- `src/tojs_reborn/engine/demo_happaloid.py`
- `tests/test_engine.py`

## Verification

`python -m unittest -v`

- 7 tests passed.

`python -m tojs_reborn.engine.demo_happaloid`

- Printed a 6-event log:
  - `action_declared`
  - `card_moved`
  - `unit_entered`
  - `ability_resolved`
  - `card_moved`
  - `cards_drawn`

