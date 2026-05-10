# 2026-05-11 V1 Minimal Rules

## Purpose

Advance the v1 implementation plan through the requested items:

1. R1 minimal replay verification
2. R2 seeded random handling
3. R4 effect damage
4. R3 target selection
5. R5 CP change effects
6. R10 trigger zone
7. R9 block declaration
8. R8 BP modifiers
9. R7 turn-end abilities
10. R11 overclock

## Implemented

- Added replay record helpers with event log and final-state digest verification.
- Added `GameState.seed` and an engine-owned RNG for random effects.
- Extended effect handlers for damage, life damage, CP changes, BP modifiers, action recovery, and trigger-zone destruction.
- Added minimal selector handling for unit targets.
- Added `choice_requested` and `choice_selected` events for first-legal unit target fallback.
- Added trigger-zone set and random trigger-zone destruction.
- Added block declaration events and `SELF_BLOCK` resolution.
- Added turn-end ability resolution and turn-duration modifier expiration.
- Added same-card overclock action with `SELF_OC` resolution.
- Promoted the first unit ability set in `ability_mapping.json` to `supported` where the engine now handles the effect.

## Tests

- `python -m unittest -v`
  - 27 tests passed.

## Notes

This is still a minimal engine slice. Full action generation, protocol integration, and full replay re-execution remain future work.
