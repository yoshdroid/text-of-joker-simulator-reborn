# 2026-05-11 V1 Public State And Override

## Purpose

Start implementing the v1 decisions added to `implementation_spec_v1.md`.

This slice covers:

- V1-A public trigger-zone color visibility
- V1-C hand override / LV management, first pass

## Implemented

- Opponent trigger zone is now visible as `{count, colors, items}` in protocol public state.
- `items[].revealed_card_no` is reserved for future used/revealed intercept state.
- Added `override_card` for hand-only same-card override.
- Override increases the target hand card level by 1.
- Override material is reset to level 1 and moved from hand to discard pile.
- Legal actions now expose `override_card` instead of battlefield `overclock_unit`.
- LV3 unit drive resolves CIP first, then emits `unit_overclocked`, then resolves `SELF_OC`.

## Verification

`python -m unittest -v`

- 33 tests passed.

## Notes

The old `overclock_unit` API remains in place temporarily for compatibility, but legal action generation no longer emits it.
