# v5 Match CLI 実行手順

## 1. sample player 同士の対戦

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 sample:first --p2 sample:pass --seed 1 --max-turns 20 --replay test_output/replay.json --verify-replay
```

## 2. 外部 process player

`cmd:<command line>` を指定すると、JSON Lines で子プログラムと通信する。

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 "cmd:python -m tojs_reborn.io.sample_player --mode first" --p2 "cmd:python -m tojs_reborn.io.sample_player --mode pass" --seed 1 --max-turns 20 --replay test_output/replay.json --verify-replay
```

## 3. decklist

通常は `card_name` で指定する。

```json
{
  "deck_name": "sample",
  "cards": [
    { "card_name": "ハッパロイド", "count": 4 },
    { "card_name": "ブラッドハウンド", "count": 4 }
  ]
}
```

検証用途では `card_no` も使える。

```json
{
  "cards": [
    { "card_no": "1-0-040", "count": 4 }
  ]
}
```

## 4. replay 検証

保存済み replay は次で再実行検証できる。

```powershell
python -m tojs_reborn.io.replay_cli --cards carddata/generated/cards.normalized.json --replay test_output/replay.json
```

event log が一致すれば exit code 0 を返す。

## 5. replay viewer

1 event 1 行で表示する。

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/replay.json
```

payload を省略する。

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/replay.json --no-payload
```

match end の state だけ見る。

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/replay.json --event-type match_ended --only-state
```

## 6. fallback / player error

v5 では、timeout / invalid response / process closed などで fallback が発生した場合、`player_response_fallback` event を記録する。

既定では player ごとに 3 回目の fallback で `player_error` として match を終了し、その player の敗北にする。

`match_ended` payload には次が含まれる。

```json
{
  "winner_player_id": "P2",
  "reason": "player_error",
  "turn_count": 0,
  "error_player_id": "P1"
}
```

## 7. JSON Lines message

### 7.1 state_update

action / choice request の前に送られる通知。子プログラムは応答しなくてよい。

```json
{
  "type": "state_update",
  "request_id": "P1:state:12",
  "player_id": "P1",
  "state_revision": 12,
  "public_state": {},
  "private_view": {}
}
```

### 7.2 request_action

通常行動、ブロック、window などで使う。

```json
{
  "type": "request_action",
  "request_id": "P1:action",
  "player_id": "P1",
  "request_context": {
    "kind": "turn_action",
    "cause_event_no": null,
    "window": null
  },
  "public_state": {},
  "private_view": {},
  "legal_actions": []
}
```

`request_context.kind` の主な値:

- `turn_action`
- `block_action`
- `intercept_window`
- `trigger_window`
- `window_action`

### 7.3 choice_request

カード効果の対象選択や optional ability の use / pass で使う。

対象ユニット選択の例:

```json
{
  "type": "choice_request",
  "request_id": "choice:17",
  "player_id": "P1",
  "choice": {
    "type": "unit",
    "choice_id": "target",
    "required": true,
    "count": 1
  },
  "display": {
    "label": "対象ユニットを1体選択"
  },
  "legal_choices": [
    {
      "unit_id": "u0001",
      "target": {
        "type": "unit",
        "controller": "P2",
        "card_instance_id": "c0008",
        "card_no": "1-0-001",
        "card_name": "ブラッドハウンド",
        "level": 1,
        "base_bp": 1000,
        "modified_bp": 0,
        "damage": 0,
        "current_bp": 1000,
        "exhausted": false
      },
      "display": {
        "label": "P2 ブラッドハウンド LV1 BP1000 DMG0"
      }
    }
  ]
}
```

optional ability の例:

```json
{
  "type": "choice_request",
  "request_id": "optional:22:1-0-099:a1",
  "player_id": "P1",
  "choice": {
    "type": "optional_ability",
    "ability_id": "1-0-099:a1",
    "source_unit_id": null,
    "source_card_instance_id": "c0010"
  },
  "legal_choices": [
    {
      "type": "pass_ability",
      "ability_id": "1-0-099:a1"
    },
    {
      "type": "use_ability",
      "ability_id": "1-0-099:a1"
    }
  ]
}
```

timeout / invalid response 時の optional ability fallback は `pass_ability`。

### 7.4 request_mulligan

```json
{
  "type": "request_mulligan",
  "request_id": "P1:mulligan",
  "player_id": "P1",
  "public_state": {},
  "private_view": {}
}
```

応答:

```json
{
  "type": "mulligan_selected",
  "request_id": "P1:mulligan",
  "player_id": "P1",
  "do_mulligan": false
}
```

## 8. GUI sample player 予定

v5 では本体統合 UI は扱わない。

GUI は JSON Lines 子プログラムの sample として実装する方針。
現時点では `tojs_reborn.io.gui_view_model` で、`public_state` / `private_view` から表示用 model を作れる。

想定コマンド:

```powershell
python -m tojs_reborn.io.gui_player --images carddata/images
```

Pillow がインストールされている場合は JPG / PNG のカード画像を表示する。
Pillow がない場合も、同じ GUI 上に card_no / card_name のプレースホルダーを表示して継続する。

GUI を開かず、JSON Lines 子プログラムとしての protocol 応答だけを確認する場合:

```powershell
python -m tojs_reborn.io.gui_player --no-window --mode pass --images carddata/images
```

match CLI から呼ぶ場合の想定:

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 "cmd:python -m tojs_reborn.io.gui_player --images carddata/images" --p2 sample:pass --replay test_output/replay.json --verify-replay
```

GUI で進行を視認したい場合は、イベントごとの `state_update` に待ち時間を入れる:

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/v6_p1.json --deck2 decklists/v6_p2.json --p1 "cmd:python -m tojs_reborn.io.gui_player --images carddata/images --mode pass" --p2 sample:first --seed 6 --max-turns 4 --event-delay-seconds 0.4 --replay test_output/gui_player_replay.json --verify-replay
```

自動テストや GUI を開けない環境では `--no-window` を使う:

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/v6_p1.json --deck2 decklists/v6_p2.json --p1 "cmd:python -m tojs_reborn.io.gui_player --no-window --mode pass --images carddata/images" --p2 sample:first --seed 6 --max-turns 4 --event-delay-seconds 0.01 --replay test_output/gui_player_replay.json --verify-replay
```
