# Text of Joker Simulator Reborn 実装仕様書 v4.0

## 1. v4 の位置づけ

v3 で、decklist から 1 match を実行し、外部子プログラム player と JSON Lines で対戦し、replay を保存・検証・閲覧できるようになった。

v4 では、子プログラムが「合法手の羅列を選ぶだけ」ではなく、公開情報と自分の非公開情報を見て判断できる状態を作る。

主目的は下記である。

- action request の前に `state_update` を送る。
- `public_state` と `private_view` を分けて protocol 化する。
- 自分の手札、場、トリガーゾーン、相手の公開情報を子プログラムに渡す。
- legal action に、人間・AI が扱いやすい表示情報を付ける。
- mulligan の最小 protocol を追加する。
- 先攻 1 turn 目の攻撃不可ルールを engine に入れる。
- replay viewer / protocol test で状態の見え方を確認できるようにする。

## 2. v3 時点でできること

### 2.1 match CLI

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 sample:first --p2 sample:pass --seed 1 --max-turns 20 --replay test_output/replay.json --verify-replay
```

### 2.2 外部子プログラム player

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 "cmd:python -m tojs_reborn.io.sample_player --mode first" --p2 "cmd:python -m tojs_reborn.io.sample_player --mode pass" --max-turns 20 --replay test_output/replay.json --verify-replay
```

### 2.3 replay viewer

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/replay.json --no-payload
```

turn 終了時と match 終了時には、viewer が field / trigger / hand count / deck count などを表示する。

## 3. v4 の完成条件

v4 完了時点で、下記を満たす。

- `JsonLinePlayer` が `request_action` の前に `state_update` を受け取れる。
- `state_update` に `public_state` と `private_view` が含まれる。
- `request_action` にも同じ `public_state` / `private_view` を含めるか、直前 `state_update` の `state_revision` を参照する。
- 子プログラムは自分の手札カード名、カード番号、カテゴリ、CP を見られる。
- 相手の手札は枚数のみ見える。
- 相手の trigger zone は枚数、色、公開済みカードのみ見える。
- legal action には `display` 情報が付く。
- mulligan request / response が JSON Lines protocol に追加される。
- 先攻 1 turn 目の attack action が legal action に出ない。
- replay に mulligan と state_update 関連の event が必要十分に記録される。
- `python -m unittest -v` が通る。

## 4. protocol 方針

### 4.1 state_update

子プログラムには、action / choice request の前に `state_update` を送る。

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

`state_update` は通知であり、子プログラムから応答しなくてもよい。

将来 handshake を導入した場合、`state_update_ack` を追加できる余地は残すが、v4 では不要とする。

### 4.2 request_action

v4 では `request_action` にも `public_state` / `private_view` を含める。

理由:

- 子プログラム側が直前の `state_update` を保持しなくても判断できる。
- request 単体でログを読める。
- 初期の外部 player 実装が簡単になる。

```json
{
  "type": "request_action",
  "request_id": "P1:action:12",
  "player_id": "P1",
  "state_revision": 12,
  "public_state": {},
  "private_view": {},
  "legal_actions": []
}
```

### 4.3 public_state

公開情報を表す。

含める候補:

```json
{
  "round_no": 1,
  "turn_no": 1,
  "turn_player_id": "P1",
  "players": {
    "P1": {
      "life": 7,
      "current_cp": 2,
      "hand_count": 4,
      "deck_count": 9,
      "discard_pile": [],
      "battlefield": [],
      "trigger_zone": []
    },
    "P2": {
      "life": 7,
      "current_cp": 0,
      "hand_count": 4,
      "deck_count": 8,
      "discard_pile": [],
      "battlefield": [],
      "trigger_zone": {
        "count": 0,
        "items": []
      }
    }
  }
}
```

### 4.4 private_view

player 本人だけが見える情報を表す。

```json
{
  "player_id": "P1",
  "hand": [
    {
      "card_instance_id": "c0001",
      "card_no": "1-0-040",
      "name": "ハッパロイド",
      "category": "unit",
      "color": "緑",
      "cp": 1,
      "level": 1
    }
  ],
  "deck_count": 9
}
```

v4 では deck の中身は渡さない。

将来、AI デバッグ用に `debug_private_deck` を追加する可能性はあるが、通常 protocol には含めない。

## 5. legal action 表示拡張

現状の legal action は engine 実行用 ID が中心である。

v4 では、行動選択しやすいように `display` を追加する。

例:

```json
{
  "type": "drive_unit",
  "card_instance_id": "c0001",
  "display": {
    "label": "ハッパロイドをフィールドに出す",
    "card_no": "1-0-040",
    "card_name": "ハッパロイド",
    "category": "unit",
    "cp": 1
  }
}
```

`display` は engine 判定には使わない。

子プログラムは action object 全体をそのまま返す必要があるため、`display` が付いていても合法手比較が崩れないようにする。

## 6. mulligan 仕様

v4 では mulligan を最小実装する。

### 6.1 flow

1. decklist 登録後、初期 hand 4 枚を draw する。
2. 各 player に `request_mulligan` を送る。
3. response が `do_mulligan: true` の場合、hand を deck に戻し、shuffle して 4 枚 draw し直す。
4. mulligan は 1 回のみ。
5. mulligan 後に match を開始する。

### 6.2 protocol

```json
{
  "type": "request_mulligan",
  "request_id": "P1:mulligan",
  "player_id": "P1",
  "public_state": {},
  "private_view": {}
}
```

```json
{
  "type": "mulligan_selected",
  "request_id": "P1:mulligan",
  "player_id": "P1",
  "do_mulligan": false
}
```

### 6.3 event

候補:

- `mulligan_requested`
- `mulligan_selected`
- `mulligan_performed`
- `deck_shuffled`

v4 では replay 再現のため、mulligan response と shuffle 結果を replay に残す。

## 7. 先攻 1 turn 目攻撃不可

spec_v3 で、先攻 1 turn 目は OC していても攻撃不可とした。

v4 では legal action 生成にこれを反映する。

条件:

- `turn_no == 1`
- `turn_player_id == "P1"`
- action type が `attack`

この場合、attack action を生成しない。

追加したい event:

- なし。

legal action に出ないだけでよい。

## 8. v4 実装アイテム

### V4-1 public_state / private_view builder

- `tojs_reborn.io.views` を追加する。
- `build_public_state(state, viewer_player_id)` を実装する。
- `build_private_view(state, viewer_player_id)` を実装する。
- opponent hand / deck の中身が漏れないテストを追加する。
- own hand の card_no / name / category / cp が見えるテストを追加する。
- commit する。

### V4-2 protocol message 拡張

- `state_update_message` を追加する。
- `request_action_message` に `public_state` / `private_view` / `state_revision` を追加する。
- `choice_request_message` も必要なら同じ view を持てるようにする。
- 既存 sample player が未知 field を無視して動くことを確認する。
- commit する。

### V4-3 JsonLinePlayer state_update 送信

- `JsonLinePlayer.choose_action` の前に `state_update` を送る経路を作る。
- `MatchRunner` から player に state view を渡せるようにする。
- 既存 player interface との互換のため、必要なら optional protocol を使う。
- external process sample player がそのまま動くことを確認する。
- commit する。

### V4-4 legal action display

- `legal_actions.py` で action に `display` を付与する。
- drive / set_trigger / override / overclock / attack / block / no_block / pass / window action を対象にする。
- engine 実行時は `display` を無視する。
- replay の action 比較が壊れないことを確認する。
- commit する。

### V4-5 mulligan minimal

- protocol に `request_mulligan` / `mulligan_selected` を追加する。
- sample player は default で mulligan しない。
- match setup または match runner 開始前に mulligan phase を追加する。
- replay に mulligan intent を記録する。
- commit する。

### V4-6 first turn attack restriction

- legal action 生成で先攻 1 turn 目 attack を出さない。
- 先攻 1 turn 目に unit がいても attack が出ないテストを追加する。
- 後攻 1 turn 目、先攻 2回目以降は attack が出るテストを追加する。
- commit する。

### V4-7 replay viewer enhancement

- state_update / mulligan event を viewer で読みやすく表示する。
- `--only-state` または `--event-type` filter を検討する。
- v4 の判断に必要なら実装する。
- commit する。

## 9. v4 で追加したいテスト

- 自分の `private_view.hand` に手札実体が出る。
- 相手の手札は `hand_count` のみで、card_no が漏れない。
- 相手 trigger zone の伏せカードは色と枚数のみ見える。
- `request_action` に `public_state` / `private_view` / `legal_actions` が同居する。
- sample child program が追加 field を無視して従来通り action を返す。
- legal action の `display` に card_name が含まれる。
- `display` 付き action を返しても legal action として受理される。
- mulligan しない場合、初期 hand が維持される。
- mulligan する場合、hand が戻され、shuffle 後に再 draw される。
- mulligan replay が再現する。
- 先攻 1 turn 目 attack action が生成されない。
- 後攻 1 turn 目 attack action は生成される。

## 10. v4 では扱わないこと

- 強い AI の実装。
- 複数 match の league / tournament runner。
- ネットワーク対戦。
- UI。
- 全カード能力。
- JOKER / キャラクター固有能力。
- 実ゲーム完全準拠の priority system。

## 11. 追加で確認したい仕様

### 11.1 mulligan

- mulligan は本当に 1 回でよいか。
5回まで実行可能にする。
- mulligan したカードは deck に戻してから shuffle でよいか。
よい。
- 両 player が mulligan 判断する順番は P1 -> P2 でよいか。
よい。
- mulligan 判断時に相手の mulligan 有無を見せるか。
見せない仕様とする。

### 11.2 state_update

- 毎 action 前に必ず送る方針でよいか。
よい。
- choice_request 前にも必ず送るか。
よい。
- `request_action` に state を同梱する方針でよいか。
よい。

### 11.3 private_view

- 自分の trigger zone の伏せカードは当然見える扱いでよいか。
そうしてほしい。
- 自分の deck の中身は見せない扱いでよいか。
よい。
- discard pile は全員に公開でよいか。
よい。

### 11.4 legal action display

- `display.label` は日本語固定でよいか。
日本語にしてほしい。
- 子プログラムが判断しやすいように、`display` ではなく machine-readable な `card` object を併設するべきか。
併設する。

## 12. v4 開始前の確認

v3 終了時点の確認結果:

```text
python -m unittest -v
Ran 78 tests in ...s
OK
```

直近コミット:

- `ddba0ca Show replay state at turn and match end`
- `d1cdc01 Add replay event viewer`
- `0c268bf Allow decklists to use card names`

v4 でも item ごとに実装、test、commit を繰り返す。
