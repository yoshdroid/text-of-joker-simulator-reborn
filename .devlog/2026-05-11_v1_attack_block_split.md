# 2026-05-11 V1 Attack Block Split

## Purpose

Implement V1-B: split attack declaration from defender block decision.

## Implemented

- Added public `declare_attack`.
- Added `resolve_unblocked_attack`.
- `list_legal_actions` now emits `attack` instead of direct `attack_player` / `attack_unit`.
- Added `list_block_actions` for defender `no_block` / `block` choices.
- `MatchRunner` now asks defender for a block action after attack.
- Kept existing `attack_player` and `attack_unit` as compatibility helpers.

## Verification

`python -m unittest -v`

- 35 tests passed.
