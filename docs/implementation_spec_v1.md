# Text of Joker Simulator Reborn

実装仕様書 v1.0

## v1 の位置づけ

`implementation_spec_v0.md` は、初期方針と M0-M5 の叩き台としては完了とみなす。

現時点では、Excel からカードプールを正規化し、イベント駆動の最小エンジンでターン進行、ユニット登場、戦闘、破壊時能力の一部まで検証できている。一方で、v0 に含まれていた能力候補のうち、未実装の効果ステップ、対象選択、リプレイ検証、通信層は残っている。

この v1 は、実装済み内容を基準に仕様を整理し、次に進めるべき残タスクを明示する。

## 実装済み範囲

### M0: 仕様固定

完了。

- Excel を唯一のゴールデン入力とする方針を採用。
- `carddata/manual/ability_mapping.json` を人間が確認する能力対応表とする。
- 変換後の `carddata/generated/cards.normalized.json` は再生成物とし、手編集しない。
- 初期対象は unit 中心とする。
- リプレイは最終状態だけでなくイベント列まで一致させる方針。

### M1: カードプール変換

完了。

- Excel 読み込み。
- `ability_mapping.json` 読み込み。
- 正規化 JSON 生成。
- レポート生成。
- normalizer テスト。

主なファイル:

- `src/tojs_reborn/cardpool/excel_loader.py`
- `src/tojs_reborn/cardpool/normalizer.py`
- `src/tojs_reborn/cardpool/schema.py`
- `src/tojs_reborn/cardpool/cli.py`
- `tests/test_cardpool_normalizer.py`

### M2: イベントとゾーン

完了。

- `EventStore`
- `GameState`
- `AgentInfo`
- `Deck`
- `Hand`
- `BattleField`
- `TriggerZone`
- `DiscardPile`
- `CardInstance`
- `UnitState`
- `FactEvent` の逐次採番
- イベントログの JSON 化

主な確認済み仕様:

- 状態変化はイベントとして記録する。
- `card_instance_id` と `unit_id` を分離する。
- ハッパロイドの `SELF_CIP` は、場に出た本人だけが発動する。
- 既存ハッパロイドの `SELF_CIP` は、別ユニットの CIP では発動しない。
- 相手場の既存ハッパロイドの `SELF_CIP` も、こちらの CIP では発動しない。

### M3: 最小ゲーム進行

完了。

- `turn_started`
- ターンプレイヤー設定
- ターン開始時の行動権回復
- `cp_set`
- ターン開始ドロー
- `turn_ended`
- P1/P2 のターン交代
- P2 終了後のラウンド進行
- `drive_unit` のターンプレイヤー制約
- `drive_unit` の CP 支払いと `cp_changed`

### M4: 最小戦闘

完了。

- アタック宣言
- アタック済みユニットの exhausted 化
- プレイヤーへの直接攻撃
- ライフ変化
- ユニット同士の戦闘
- 双方ダメージ
- 戦闘結果イベント
- lethal unit の破壊
- battlefield から discard pile への移動

実装済み戦闘結果イベント:

- `battle_won`
- `battle_lost`
- `battle_draw`
- `battle_unresolved`

### M5: 最小能力

一部完了。

実装済み:

- `SELF_CIP`
- `YOUR_CIP`
- `RIVAL_CIP`
- `SELF_PIG`
- `draw_cards`
- `discard_from_hand`
- `draw_card_by_category`
- 破壊時能力のターンプレイヤー優先
- 同一プレイヤー内の破壊時能力の左から右順
- `random_resolved` への候補一覧と選択結果記録

確認済みカード:

- ハッパロイド
  - `SELF_CIP`
  - 1ドロー
- ミイラくん
  - `SELF_PIG`
  - 対戦相手手札を1枚ランダム捨て
- カラスマドウ
  - `SELF_PIG`
  - インターセプトカードを1枚引く

## 現在のイベント仕様

イベントは `FactEvent` として `EventStore` に記録する。

共通フィールド:

```json
{
  "event_no": 1,
  "type": "card_moved",
  "round_no": 1,
  "turn_no": 1,
  "actor_player_id": "P1",
  "cause_event_no": null,
  "source": {
    "card_no": "1-0-001",
    "card_instance_id": "c0001",
    "unit_id": null,
    "ability_id": null
  },
  "payload": {}
}
```

現在使用中の主なイベント:

- `action_declared`
- `ability_resolved`
- `battle_draw`
- `battle_lost`
- `battle_started`
- `battle_unresolved`
- `battle_won`
- `card_moved`
- `cards_drawn`
- `cp_changed`
- `cp_set`
- `damage_dealt`
- `life_changed`
- `random_resolved`
- `turn_ended`
- `turn_started`
- `unit_action_recovered`
- `unit_attacked`
- `unit_destroyed`
- `unit_entered`

未実装だが v0 から残す候補:

- `match_started`
- `deck_shuffled`
- `block_declared`
- `ability_queued`
- `choice_requested`
- `choice_selected`
- `invalid_response`
- `match_ended`

## 現在の能力収集順

### CIP

ターンプレイヤーがユニットを場に出したイベントを `CIP` とする。

収集・解決順:

1. 場に出たユニット自身の `SELF_CIP`
2. 自陣の他ユニットを左から右に確認し、`YOUR_CIP`
3. 対戦相手のユニットを左から右に確認し、`RIVAL_CIP`

注意:

- 既存ユニットの `SELF_CIP` は確認しない。
- 相手場の既存ユニットの `SELF_CIP` も確認しない。
- 現在は収集後スタックに積むより、該当順に即時解決する実装。

### PIG

ユニット破壊時を `PIG` とする。

現在の解決順:

1. lethal unit を先に収集する。
2. ターンプレイヤー側の destroyed unit を先に処理する。
3. 同一プレイヤー内では battlefield 左から右に処理する。
4. 各ユニットについて、battlefield から discard pile へ移動する。
5. `unit_destroyed` を記録する。
6. `SELF_PIG` を解決する。
7. `state.units` から削除する。

未実装:

- `YOUR_PIG`
- `RIVAL_PIG`
- 他イベントキューとの厳密な相互作用

## 残タスク

### R1: リプレイ検証

目的:

イベントログをゲーム進行の正として扱えるか検証する。

実装候補:

- `engine/replay.py`
- replay input schema
- replay metadata
- initial state snapshot
- intent/fact event の分類整理
- イベント列完全一致テスト

必要なメタ情報:

- `schema_version`
- `engine_version`
- `cardpool_hash`
- `regulation_hash`
- `seed`
- `created_at`
- `initial_decklists`

### R2: 乱数管理

目的:

ランダム処理を完全リプレイ可能にする。

現在:

- `discard_from_hand` は決定的に先頭候補を選んでいる。
- `random_resolved` に候補と選択結果を残している。

残り:

- `GameState` または engine context に seed/RNG を持たせる。
- RNG で選択した結果を `random_resolved` に記録する。
- replay 時は記録済み結果を使用するか、同じ seed から同じ結果を検証する。
- `deck_shuffled` の扱いを決める。

### R3: 対象選択

目的:

カード効果が対象を必要とする場合に、エンジンが選択要求と合法性検証を行えるようにする。

必要なもの:

- selector 解決
- selector の合法候補列挙
- `choice_requested`
- `choice_selected`
- 不正応答時の `invalid_response`
- 先頭合法候補へのフォールバック
- 対象不在時に能力を発動しない処理

最初の対象カード候補:

- ランサー
  - `SELF_ATK`
  - 対戦相手ユニット1体に1000ダメージ
- ブラッドハウンド
  - `SELF_OC`
  - 対戦相手ユニット1体に4000ダメージ

### R4: ダメージ効果

目的:

戦闘以外の効果ダメージを実装する。

必要な効果ステップ:

- `deal_damage_to_unit`
- `deal_life_damage`

確認したいこと:

- 効果ダメージで lethal になったユニットの破壊
- 効果ダメージによる `SELF_PIG`
- ダメージ発生源と `cause_event_no`
- 対象不在時の不発

候補カード:

- ランサー
- ブラッドハウンド
- ゴライアス

### R5: CP 変化効果

目的:

カード効果による CP 増減を扱う。

必要な効果ステップ:

- `change_cp`

候補カード:

- グラインドビートル
  - `SELF_CIP`
  - CP +2

確認したいこと:

- drive cost 支払い後に CP +2 が解決される。
- `cp_changed` の `reason` を action と effect で区別する。
- CP 上限があるかどうかを決める。

### R6: 条件付き能力

目的:

`condition` を持つ能力を解決前に判定できるようにする。

候補カード:

- グラインドビートル
  - このターンに他のコスト2以上の緑カードを使用している場合、1ドロー

必要な記録:

- 使用済みカード履歴
- 使用カードの cost/color
- source card を除外する判定

### R7: ターン終了時能力

目的:

ターン終了時に発動する能力を扱う。

候補カード:

- キャットムル
- ギガマムート

必要な仕様:

- `SELF_TURN_END` の収集順
- ターン終了時の `recover_action`
- ターン開始時の通常回復との違い
- ターン終了処理内で発生した追加イベントの扱い

### R8: BP 修正

目的:

一時的な BP 変更を扱う。

候補カード:

- リーフィア
  - `SELF_BLOCK`
  - ターン終了時まで BP +2000

必要なもの:

- modifier model
- `modify_bp`
- duration: `turn` / `battle` / `permanent`
- duration 期限切れイベント
- BP 変化後の lethal 判定

### R9: ブロック宣言

目的:

現在の `attack_unit` は直接ブロック済み戦闘を実行しているため、実際のアクションとしてブロック宣言を分離する。

必要なイベント:

- `block_declared`
- `SELF_BLOCK` 誘発
- ブロック可能ユニットの合法性

候補カード:

- リーフィア

### R10: トリガーゾーン

目的:

トリガー/インターセプトカードを扱うための土台を作る。

必要なもの:

- trigger zone へのセット
- 公開情報: 色、配置枚数
- 非公開情報: card instance
- ランダム破壊
- `destroy_trigger_zone_card`

候補カード:

- ヘルハウンド
  - `SELF_CIP`
  - 相手トリガーゾーンのカードを1枚ランダム破壊

### R11: オーバークロック

目的:

同名カードの重ね、レベル変化、OC能力を扱う。

必要なもの:

- card instance と unit の関係更新
- level 管理
- `set_level`
- `SELF_OC`
- 手札/場の同名判定

候補カード:

- ブラッドハウンド
- ゴライアス

### R12: 行動生成

目的:

子プログラムに渡す合法アクションを生成する。

必要なもの:

- drive candidates
- attack candidates
- block candidates
- pass
- action payload schema
- action legality tests

現状:

- `drive_unit` / `attack_player` / `attack_unit` は直接呼び出し API として存在する。
- 合法手一覧生成は未実装。

### R13: 通信層

目的:

子プログラム同士の 1vs1 対戦を実行する。

必要なもの:

- `io/protocol.py`
- `io/player_runner.py`
- `io/match_runner.py`
- stdio / JSON Lines
- timeout
- invalid response handling
- public state view
- private state view

初期メッセージ候補:

- `hello`
- `deck_submit`
- `mulligan_decision`
- `state_update`
- `request_action`
- `choice_request`
- `game_over`

## 次の推奨順

次は、エンジン品質を上げる観点から次の順で進める。

1. R1 リプレイ検証の最小版
2. R2 乱数管理
3. R4 効果ダメージ
4. R3 対象選択
5. R5 CP 変化効果
6. R10 トリガーゾーン
7. R9 ブロック宣言
8. R8 BP 修正
9. R7 ターン終了時能力
10. R11 オーバークロック
11. R12 行動生成
12. R13 通信層

理由:

- リプレイと乱数を先に固めると、以後のカード効果追加で手戻りが少ない。
- 効果ダメージと対象選択は、多くのカード効果の共通部品になる。
- 通信層は、エンジンの action/choice schema が固まってから作るほうがよい。

## v1 完了条件

v1 は、次を満たした時点で完了とする。

- replay の最小検証がある。
- RNG を seed で管理し、`random_resolved` に結果を残せる。
- selector を使う効果を1つ以上実装している。
- 効果ダメージでユニット破壊と PIG が連動する。
- CP 変化効果を1つ以上実装している。
- すべての追加仕様にテストがある。

## v1 実装進捗

2026-05-11 時点で、次の項目は最小実装済み。

- R1 リプレイ検証の最小版
- R2 乱数管理
- R3 対象選択
- R4 効果ダメージ
- R5 CP 変化効果
- R7 ターン終了時能力
- R8 BP 修正
- R9 ブロック宣言
- R10 トリガーゾーン
- R11 オーバークロック

この段階の実装は、各機能の完全版ではなく、エンジン部品としてイベントに記録され、カード効果から呼び出せる最小版である。

今後の残タスク:

- replay の完全な再実行。最小実装済み。
- action/choice の合法手生成。最小実装済み。
- 子プログラム通信用 protocol / match runner。最小実装済み。
- trigger / intercept の割り込み window。候補列挙のみ最小実装済み。
- OC の実ゲーム相当のカード統合処理。unit stack として最小実装済み。
- 追加カードを使った仕様テスト拡充。継続。

## v1 追加実装仕様

### replay の完全な再実行

replay record は次を持つ。

- `initial_state`
- `intents`
- `events`
- `final_state`
- `seed`

再実行時は `initial_state` から `GameState` を復元し、`intents` を順に適用する。その結果の `events` と `final_state` が replay record と一致しなければ replay failure とする。

現在 replay 可能な intent:

- `start_turn`
- `end_turn`
- `drive_unit`
- `set_trigger`
- `overclock_unit`
- `attack_player`
- `attack_unit`
- `pass`

### action/choice の合法手生成

`list_legal_actions(state, player_id)` は、現在のターンプレイヤーに対して次を返す。

- `drive_unit`
- `set_trigger`
- `overclock_unit`
- `attack_player`
- `attack_unit`
- `pass`

非ターンプレイヤーには現時点では `pass` のみ返す。割り込み window での発動候補は `list_trigger_intercept_window` で別管理する。

### protocol / match runner

通信層の初期実装は JSON Lines の message encode/decode とする。

現在の message type:

- `hello`
- `state_update`
- `request_action`
- `action_selected`
- `choice_request`
- `choice_selected`
- `game_over`

`public_state_message` は、相手の hand / deck / trigger_zone を枚数のみ公開する。

`MatchRunner` は、同じ action payload を使って player object から action を受け取り、合法手でなければ `invalid_response` を記録して先頭合法手にフォールバックする。

### trigger / intercept window

`list_trigger_intercept_window` は、指定 player の trigger_zone にある trigger / intercept の公開候補を返す。

現在は候補列挙のみで、実際の発動、コスト支払い、発動権移動、連続パス終了は未実装。

### OC のカード統合

overclock は、手札の同名 card instance を `unit_stack` に移動したものとして扱う。素材カードは discard pile に置かず、`UnitState.stacked_card_instance_ids` に保持する。

現在の OC 処理:

1. 手札から同名カードを選ぶ。
2. 対象 unit の `stacked_card_instance_ids` に追加する。
3. unit level を最大3まで +1 する。
4. `unit_level_changed` を記録する。
5. `unit_overclocked` を記録する。
6. `SELF_OC` を解決する。

## 追加で確認したい仕様

次に実装を深める前に、以下を決めたい。

1. trigger / intercept の発動 window
   - どのイベント後に window を開くか。
   - 先に発動権を得るプレイヤー。
   - 両者連続パスで閉じる単位。

2. block の扱い
   - 現在は `attack_unit` が「ブロック済み戦闘」を直接表す。
   - 実際には attack 宣言後に defender が block / no block を選ぶ形へ分離するか。

3. overclock の素材カード
   - 素材カードは unit stack に置く方針でよいか。
   - unit 破壊時に stack の全 card instance を discard pile に置くか。
   - discard pile の順序は上から素材、新しいカード、元カードのどれにするか。

4. legal action の粒度
   - 子プログラムに `attack_unit` を直接渡してよいか。
   - それとも `attack` と `block` を別 request に分けるか。

5. public state
   - 相手 trigger_zone は枚数と色を公開する方針だったが、現在の protocol では枚数のみ隠蔽している。
   - 色一覧を公開 payload に含めるか。

## 現在の検証状況

2026-05-11 時点:

```text
python -m unittest -v
Ran 33 tests
OK
```
