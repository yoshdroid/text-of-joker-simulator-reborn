# 2026-05-11 V1 Remaining Tasks

## Purpose

Advance the remaining v1 items after the minimal rules commit:

- complete replay re-execution
- legal action generation
- protocol / match runner
- trigger / intercept window skeleton
- more realistic OC card integration
- additional specification tests

## Implemented

- Added `engine/legal_actions.py` for drive, set trigger, overclock, attack, and pass actions.
- Expanded `engine/replay.py` to restore initial state, apply intents, and compare event logs and final state.
- Added `engine/windows.py` for trigger/intercept window candidate listing.
- Added `io/protocol.py` for JSON Lines message encode/decode and public state payloads.
- Added `io/match_runner.py` for an in-process runner using the same action payloads.
- Changed OC material handling from discard pile movement to `unit_stack` movement.
- Added `UnitState.stacked_card_instance_ids`.

## Verification

`python -m unittest -v`

- 33 tests passed.

## Spec Questions Raised

1. Which exact events open trigger/intercept windows?
2. Does the defender choose block in a separate request after attack declaration?
3. On unit destruction, how should stacked OC material cards be ordered in discard pile?
4. Should child programs receive direct `attack_unit` actions, or separate `attack` and `block` decisions?
5. Should public state expose opponent trigger-zone colors as planned, not just count?
