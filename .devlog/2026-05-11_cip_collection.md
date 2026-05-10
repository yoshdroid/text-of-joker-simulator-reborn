# 2026-05-11 CIP Collection

## Purpose

Extend the initial engine resolver from source-only `SELF_CIP` to the three-stage CIP collection rule:

1. entering unit `SELF_CIP`
2. same-side existing units `YOUR_CIP` from left to right
3. opponent existing units `RIVAL_CIP` from left to right

## Important Rule

Existing Happaloids have `SELF_CIP`, not `YOUR_CIP` or `RIVAL_CIP`.
Therefore, they must not draw when another unit enters on either side.

## Scope

- Move supported ability resolution into `resolver.py`
- Keep only `draw_cards` effect implemented
- Add synthetic test cards for `YOUR_CIP` and `RIVAL_CIP`
- Preserve existing Happaloid behavior

## Implemented Files

- `src/tojs_reborn/engine/resolver.py`
- `src/tojs_reborn/engine/actions.py`
- `tests/test_engine.py`

## Verification

`python -m unittest -v`

- 9 tests passed.

`python -m tojs_reborn.engine.demo_happaloid`

- Still prints the expected Happaloid event chain.
