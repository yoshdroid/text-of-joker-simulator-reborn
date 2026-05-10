# 2026-05-11 M5 Follow-ups

## Purpose

Implement the next recommended engine items in order:

1. same-player simultaneous `SELF_PIG` order
2. richer `random_resolved` payloads
3. CP cost payment for `drive_unit`
4. action recovery at turn start
5. battle result events

## Notes

The engine still intentionally keeps action selection and full legality generation out of scope.
These changes make the existing direct engine operations closer to actual game rules while preserving testability.

## Implemented

- Added same-player simultaneous destruction ordering: turn player first, then battlefield left-to-right.
- Added replay-friendly `random_resolved` payload fields for discard selection candidates and chosen index.
- Added `drive_unit` turn-player validation and CP payment with `cp_changed` events.
- Added turn-start action recovery with `unit_action_recovered` events before CP and draw.
- Added battle result events: `battle_won`, `battle_lost`, `battle_draw`, and `battle_unresolved`.

## Tests

- `python -m unittest -v`
- `python -m tojs_reborn.engine.demo_happaloid`
