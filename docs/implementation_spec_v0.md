# Text of Joker Simulator Reborn

実装仕様書 初版 v0.1

## 目的

`text-of-joker-simulator-reborn` は、2 つの子プログラムが 1vs1 で対戦するデジタルカードゲームのシミュレータを、旧試作版より小さく、検証しやすく、リプレイ可能な構成で作り直す。

旧 `text-of-joker-simulator` では、全体の動作可能性は確認できた。一方で、カード効果の自然言語解釈、誘発順、解決順、個別効果の追加により、後から期待動作とのズレが発見されやすかった。

今回の初期方針は次のとおり。

- Excel ファイルを唯一のゴールデン入力とする。
- ただし、ゲーム本体は Excel を直接解釈せず、変換済みカードプール JSON を読む。
- カード効果は自然言語本文ではなく、構造化された能力定義を正とする。
- すべてのゲーム進行と状態変化をイベントとして記録する。
- まずカード種類と効果種類を絞り、1 つずつ仕様、実装、テストを追加する。

## 旧試作版からの学び

旧版で確認できた有用な要素:

- `stdio` / JSON Lines による子プログラム対戦は成立する。
- `state_update`、`request_action`、`choice_request` の通信モデルは再利用候補になる。
- Excel 読み込み処理は実用可能だった。
- `internal event log` から観戦ログを生成する方針は妥当。
- 回帰テストは、盤面変化、公開情報、誘発順、インターセプト解決のズレ検出に有効だった。

旧版で再設計したい要素:

- `game.py` に状態、ルール、合法手、戦闘、誘発収集、個別効果、表示用状態が集中していた。
- 効果メタデータと Python の個別分岐が混ざり、カードが増えるほど追跡が難しくなった。
- イベントログは存在したが、「状態復元のための正」としてはまだ曖昧だった。
- 自然言語テキストと実装済み効果の対応を機械的に検証しづらかった。

## 基本アーキテクチャ

ゲーム本体は、通信層から独立したエンジンとして実装する。

推奨ディレクトリ:

```text
src/tojs_reborn/
  cardpool/
    excel_loader.py
    normalizer.py
    schema.py
  engine/
    events.py
    event_store.py
    state.py
    zones.py
    rules.py
    actions.py
    resolver.py
    effects.py
    selectors.py
    replay.py
  io/
    protocol.py
    player_runner.py
    match_runner.py
  bots/
  cli/
tests/
docs/
carddata/
configs/
```

初期実装では、通信層より先に `engine` と `cardpool` を固める。

## ゾーン設計

ユーザー案のとおり、ゾーンはシミュレータの部品として分離する。ただし、各ゾーンが勝手にイベントを発行するのではなく、状態変更 API がイベントを記録する。

| 部品 | 役割 | 主な保持情報 |
| --- | --- | --- |
| `BattleField` | 場のユニット管理 | unit id、card id、level、damage、action state、modifiers |
| `TriggerZone` | トリガー/インターセプト配置 | slot、card instance、公開色、裏向き情報 |
| `DiscardPile` | 捨札管理 | card instances、順序、公開情報 |
| `Deck` | 山札管理 | card instances、順序、シャッフル履歴 |
| `Hand` | 手札管理 | card instances、公開/非公開情報 |
| `AgentInfo` | プレイヤー情報 | player id、life、cp、role、visible state policy |

補足:

- `Deck`、`Hand`、`TriggerZone` のカードは、カード番号だけではなく `card_instance_id` を持たせる。
- ユニット化したカードは `unit_id` を持ち、元カードインスタンスとの関係を保持する。

追記欄:

```text
ゾーン名称の最終案:
  DiscardPileにする。
  イベント発動タイミングとしてユニット破壊時 = PIG(PutIntoGraveyard)があるが、すべて Graveyardを DiscardPileに読み替える。

捨札の順序は公開情報か:
  公開情報とする。対戦相手は相手の捨て札順序から行動を推測可能。

トリガーゾーンの相手公開情報:
　セットされたカードの色情報、およびゾーン配置された枚数を公開情報とする。

カードインスタンス ID が必要になる場面:
  Handおよび TriggerZoneでは オーバーライド行動によるレベル変化を保持記憶するため IDによる区別を必要とする。
  Deckでは最終的に不要となる可能性あるが、用意しておく。
```

## イベント設計

完全リプレイ性のため、イベントログをゲーム進行の正とする。

イベントには 2 種類を置く。

- `IntentEvent`: プレイヤー選択、乱数結果、外部入力など、再実行時に固定すべき入力。
- `FactEvent`: 実際に起きた状態変化、誘発、解決結果。

リプレイでは `IntentEvent` を順に再投入し、同じ `FactEvent` 列と最終状態が得られることを検証する。

全イベント共通フィールド:

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
    "card_instance_id": "c001",
    "unit_id": null,
    "ability_id": null
  },
  "payload": {}
}
```

初期イベント候補:

- `match_started`
- `deck_shuffled`
- `cards_drawn`
- `turn_started`
- `cp_set`
- `action_declared`
- `card_moved`
- `unit_entered`
- `unit_attacked`
- `block_declared`
- `battle_started`
- `damage_dealt`
- `unit_destroyed`
- `life_changed`
- `ability_queued`
- `ability_resolved`
- `choice_requested`
- `choice_selected`
- `random_resolved`
- `turn_ended`
- `match_ended`

追記欄:

```text
イベント名として残したい旧版の名称:

観戦ログに必ず出したい出来事:
  開発序盤はデバグ可能ならよく、どのイベントが発火しているかを常に観測したい。

リプレイファイルに含めたいメタ情報:
最低限 schema_version、engine_version、cardpool_hash、regulation_hash、seed、created_at、initial_decklists 
```

## 状態変更ルール

状態は直接書き換えない。すべての変更は、エンジンが提供する操作関数を通す。

例:

- `move_card(...)`
- `draw_cards(...)`
- `set_cp(...)`
- `deal_damage_to_unit(...)`
- `destroy_unit(...)`
- `change_life(...)`
- `queue_ability(...)`
- `resolve_ability(...)`

各操作関数は次を同時に行う。

- 合法性チェック
- 状態変更
- `FactEvent` 記録
- 追加で発生するイベントまたは能力解決キューの登録

この方針により、状態復元、テスト、観戦ログ生成を同じ材料から行う。

## カードプール変換

Excel は唯一のゴールデン入力とする。ただし、エンジンは変換済み JSON のみを読む。

変換ユーティリティの役割:

1. Excel を読み込む。
2. 列名と型を検証する。
3. 能力本文を保持する。
4. 能力本文に対応する構造化フィールドを付与する。
5. 正規化カードプール JSON を出力する。
6. 変換エラー、未対応効果、曖昧な効果をレポートする。

推奨出力:

```text
carddata/
  source/
    text-of-joker.cardpool.xlsx
  generated/
    cards.normalized.json
    cardpool_report.json
  manual/
    ability_mapping.json
    effect_templates.json
```

`manual/ability_mapping.json` は Excel 本文と実装用定義の対応表とする。これにより、Excel をゴールデンにしつつ、自然言語を実行時に推測しない。

カード JSON 最小案:

```json
{
  "card_no": "1-0-001",
  "name": "ブラッドハウンド",
  "category": "unit",
  "color": "red",
  "cp": 1,
  "race": "獣",
  "bp_by_level": [3000, 4000, 5000],
  "abilities": [
    {
      "ability_id": "1-0-001:a1",
      "name": "ダメージブレイク",
      "text": "元の効果文章",
      "timing": "unit_overclocked",
      "optional": false,
      "cost": null,
      "selector": null,
      "effect_steps": [
        {
          "effect": "deal_damage_to_unit",
          "target": "opponent_unit.selected",
          "amount": 3000
        }
      ]
    }
  ]
}
```

追記欄:

```text
Excel の列名一覧:
  no	category	rarity	color	name	race	cp	bp	abilities	
  abilitiesをいちばん右に変更した  

Excel の abilities セル形式:
  過去検討と同様
  name + text

手動対応表に持たせたい項目:
  "このユニットが"       → SELF_
  "あなたのユニットが"   → YOUR_
  "対戦相手のユニットが" → RIVAL_

  "フィールドに出た時"   → CIP ComeIntoPlay
  "破壊された時"        → PIG PutIntoGraveyard
  "オーバークロックした時" → OC OverClocked
  "アタックした時"      → ATK

初期開発で対象にするカード番号:
  デッキレシピなど 番号の代わりにカード名で指示できるようにしていきたい
  ブラッドハウンド
  ランサー
  ヘルハウンド
  ゴライアス
  ハッパロイド
  グラインドビートル
  キャットムル
  リーフィア
  ギガマムート

以下は M3完了後の次期候補
  ベーシックキャノン
  サプライズボックス
  新品の鎧
  何でも屋の陳列台
  パワーショーテージ
  英雄の剣
  インペリアルソード
  悪の覚醒
  アースクエイク
  不可侵防壁
  ナチュラルフルーツ
  逆転の大竜巻

```

## 能力解決

能力解決は、旧版の「イベント駆動」を引き継ぐ。ただし、カード個別の Python 分岐を増やす前に、効果ステップを小さな命令として表す。

処理の流れ:

1. 盤面で `FactEvent` が発生する。
2. `trigger_table` から反応する能力を収集する。
3. 優先順位仕様に従い `AbilityOnStack` を作る。
4. 必要なら `choice_request` を発行する。
5. `effect_steps` を順に解決する。
6. 解決中に発生したイベントから、さらに能力を収集する。

初期対応する効果ステップ候補:

- `draw_cards`
- `move_card`
- `deal_damage_to_unit`
- `deal_life_damage`
- `modify_bp`
- `destroy_unit`
- `recover_action`
- `set_level`
- `change_cp`

初期はすべてを汎用 DSL にしすぎない。効果ステップの種類を固定し、テストとカード追加に合わせて拡張する。

追記欄:

```text
最初に実装したい能力:
  draw_cards

任意効果の選択方式:
「任意効果は choice_request で use/skip を選ぶ。応答不能時は skip」

「そうした場合」の表現方式:

対象不適正時の扱い:
  対象選択不可能時には、効果を発動させない
  選択可能な対象がいるが無効な対象が選ばれた時には、無効な選択であったことを明示したのち、「先頭の合法候補にフォールバック」する

```

## 優先順位と解決順

ここは開発前に最も重要な未決領域。

初期案:

- 1 つの出来事から誘発した能力は、同じ `cause_event_no` を持つ。
- 同じ契機内では、ターンプレイヤー側を先に収集する。
- 同じプレイヤー内では、イベント発生源自身の `SELF_*` を先に確認し、その後に該当する監視系能力をゾーン順、フィールド左から右、トリガー左から右で確認する。
- 解決中に発生した新しい契機は、現在の解決完了後にキューへ積む。
- インターセプトのような選択式割り込みは、通常誘発と別の `window` として定義する。

追記欄:

```text
同時誘発の先攻/後攻順:
  ターンプレイヤー側が優先される。
  後攻プレイヤーのターン中に CIP が同時発生した場合、ターンプレイヤーである後攻側を優先する

フィールド左から右の定義:
  左から順に並ぶ。
  ターンプレイヤーがユニットを場に出すことによるイベントを CIP とする。
  CIP イベントでは、まず場に出されたユニット自身が SELF_CIP を持つか調べ、持っていれば解決する。
  続けて、自陣に出ている他のユニットを左から順に見て、YOUR_CIP を持つか調べる。このとき SELF_CIP は調べない。
  さらに、対戦相手の場に出ているユニットを左から順に見て、RIVAL_CIP を持つか調べる。このときも SELF_CIP は調べない。
  例: 既存ハッパロイドが場にいる状態で新たなハッパロイドを場に出した場合、既存ハッパロイドの SELF_CIP は発動しない。
  例: 対戦相手の場に既存ハッパロイドがいる状態でユニットを場に出しても、対戦相手の既存ハッパロイドの SELF_CIP は発動しない。

トリガー左から右の定義:
  左から順にセットされる。
  ユニットと同様。

破壊時割り込みの扱い:
  破壊時効果はイベントキューに先駆けて処理する。
  スタックによる再起処理をおこなう。

インターセプト発動権の移動:
  複数発動可能であっても、一つ発動したのち対戦相手側に発動権がまわる。

連続パス時の終了条件:
  両プレイヤーがパスしたとき終了する。

```

## プレイヤー通信

通信方式は旧版と同じく `stdio` / JSON Lines を初期案とする。

ただし、通信層はエンジンの外側に置く。エンジンは `ChoiceResolver` インターフェイスだけを呼ぶ。

初期メッセージ:

- `hello`
- `deck_submit`
- `mulligan_decision`
- `state_update`
- `request_action`
- `choice_request`
- `game_over`

追記欄:

```text
子プログラムの実行形式:

タイムアウト:

不正応答時の扱い:
「invalid_response イベントを記録し、初期開発では先頭合法アクションにフォールバック」

通信ログに残す範囲:
```

## テスト方針

実装は、部品ごとにテストを先に近い順で追加する。

初期テスト分類:

- `cardpool normalization test`
- `zone operation test`
- `event store test`
- `replay test`
- `action legality test`
- `battle flow test`
- `ability trigger test`
- `priority order test`
- `protocol payload test`

各仕様テストは、次を持つ。

```text
case_id:
目的:
初期状態:
実行する IntentEvent:
期待する FactEvent 列:
期待する最終状態:
```

最初に作るべきテスト:

1. Excel から正規化 JSON を生成できる。
2. 正規化 JSON の能力タイミングが既知イベントだけを参照している。
3. `move_card` が状態変更と `card_moved` を同時に記録する。
4. `IntentEvent` 列から同じ最終状態を再現できる。
5. 1 体のユニットを出すと `unit_entered` が記録される。
6. 1 つの登場時能力がキューに積まれ、解決される。

## 初期マイルストーン

### M0: 仕様固定

- この文書に未決項目を追記する。
- 初期カードセットを選ぶ。
- Excel 列と能力対応表の形式を固定する。

### M1: カードプール変換

- Excel 読み込み。
- 正規化 JSON 出力。
- 未対応能力レポート出力。
- schema テスト。

### M2: イベントとゾーン

- `GameState`
- `AgentInfo`
- `Deck`
- `Hand`
- `BattleField`
- `TriggerZone`
- `DiscardPile`
- `EventStore`
- リプレイ可能性の最小テスト。
- CIP イベントでは、場に出されたユニット自身の SELF_CIP を先に確認し、その後に自陣の他ユニットの YOUR_CIP を左から順に確認する。
- 既存ハッパロイドが場にいる状態で新たなハッパロイドを場に出しても、既存ハッパロイドの SELF_CIP は発動しないことを確認する。
- 対戦相手の場に既存ハッパロイドがいる状態でユニットを場に出しても、対戦相手の既存ハッパロイドの SELF_CIP は発動しないことを確認する。

### M3: 最小ゲーム進行

- 初期手札。
- ターン開始。
- CP 設定。
- ドロー。
- ユニット登場。
- ターン終了。

### M4: 最小戦闘

- アタック。
- ブロックなしのライフダメージ。
- ブロック戦闘。
- 破壊と捨札移動。

### M5: 最小能力

- 登場時ドロー。
- 登場時ダメージ。
- アタック時 BP 変更。
- 破壊時能力。
- 優先順位テスト。

## 追加で決めたいこと

開発開始前、または M0 中にユーザーが追記するとよい情報。

```text
1. 最初の対象カードセット
例: 10 枚、20 枚、旧 rg_beatdown のみ、など

  ブラッドハウンド
  ランサー
  ヘルハウンド
  ゴライアス
  ハッパロイド
  グラインドビートル
  キャットムル
  リーフィア
  ギガマムート

2. 最初に対応したいカードカテゴリ
例: unit のみ / unit + trigger / unit + trigger + intercept
  上記 unitのみ

3. 初期ルールの簡略化許容範囲
例: OC なし、進化なし、インターセプトなし、など
  unitのみなので 進化なし

4. Excel ファイルの配置場所
例: carddata/source/text-of-joker.cardpool.xlsx
  carddata/text-of-joker.cardpool.xlsx

5. 正規化 JSON を手で編集してよいか
例: generated は編集禁止、manual は編集可
cards.normalized.json は再生成で上書きされる前提、手編集は manual/ability_mapping.json のみにする

6. リプレイに求める厳密さ
例: 最終状態一致でよい / イベント列まで完全一致
  イベント列まで完全一致させることでデバグ容易化したい

7. 乱数の責務
例: engine が seed 管理 / match_runner が random 結果を IntentEvent として渡す
「乱数生成は engine が seed から一元管理し、実際に選ばれた結果を random_resolved としてイベントに残す」

8. 子プログラム対戦の優先度
例: エンジン完成後でよい / 早期に疎通だけ作る
  エンジン完成後に作る

```
