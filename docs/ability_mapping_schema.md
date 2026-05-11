# Ability Mapping Schema

`carddata/manual/ability_mapping.json` の設計ひな形。

この文書は、Excel の `abilities` セルに書かれた自然言語の能力情報を、ゲームエンジンが解釈できる構造化データへ対応付けるための仕様を定義する。

## 目的

Excel ファイルを唯一のゴールデン入力としつつ、エンジンが自然言語を直接推測しないようにする。

`ability_mapping.json` は、人間が確認・追記する手動対応表である。変換ユーティリティは Excel と `ability_mapping.json` を読み、`carddata/generated/cards.normalized.json` を生成する。

## 基本方針

- Excel のカード本文は表示・照合用として保持する。
- 発動タイミング、対象、コスト、効果は `ability_mapping.json` の構造化フィールドを正とする。
- `card_no` が分かる場合は `card_no` を主キーにする。
- デッキレシピや人間向け指定では `card_name` も使えるようにする。
- `cards.normalized.json` は再生成で上書きされるため手編集しない。
- 手編集は `carddata/manual/ability_mapping.json` に集約する。

## ファイル配置

```text
carddata/
  text-of-joker.cardpool.xlsx
  manual/
    ability_mapping.json
  generated/
    cards.normalized.json
    cardpool_report.json
```

## トップレベル構造

```json
{
  "schema_version": 1,
  "notes": "Manual mapping from Excel ability text to engine-readable ability definitions.",
  "cards": {
    "1-0-001": {
      "card_name": "ブラッドハウンド",
      "abilities": []
    }
  }
}
```

## カード項目

```json
{
  "card_name": "ブラッドハウンド",
  "abilities": [
    {
      "ability_key": "1-0-001:a1",
      "ability_name": "ダメージブレイク",
      "source_text": "Excel に書かれている元テキスト",
      "status": "supported",
      "timing": "SELF_OC",
      "optional": false,
      "priority": {
        "band": "unit",
        "order": "source_only"
      },
      "condition": null,
      "cost_steps": [],
      "selector": null,
      "effect_steps": []
    }
  ]
}
```

## 必須フィールド

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `ability_key` | string | `card_no:a1` のような能力識別子 |
| `ability_name` | string | Excel 側の能力名 |
| `source_text` | string | Excel 側の能力本文 |
| `status` | string | `supported` / `unsupported` / `deferred` |
| `timing` | string | 発動タイミング |
| `optional` | boolean | 任意効果かどうか |
| `priority` | object | 同時誘発時の優先帯と順序 |
| `condition` | object/null | 発動条件 |
| `cost_steps` | array | 「そうした場合」等の前提コスト |
| `selector` | object/null | 対象選択 |
| `effect_steps` | array | 解決する効果ステップ |

## `status`

```text
supported   エンジン実装済みであり、変換後 JSON に有効な能力として出力する
unsupported 構造化できない、または仕様未確定
deferred    構造化済みだが、エンジン未実装または今回対象外
```

初期 M1-M3 では、対象 unit 9 枚以外を `deferred` として扱ってよい。

## `source_text` / `notes`

`supported` の ability は、Excel の自然言語記述との対応を追跡できるように、原則として次のどちらかを持つ。

- `source_text`: Excel 側の能力本文を転記する。
- `notes`: Excel 本文が空、または本文だけでは説明しづらい場合の手動メモ。

normalizer は `source_text` と `notes` の両方が空の `supported` ability を warning として報告する。

## `timing`

初期案では、自然言語の主語と契機を組み合わせた短いコードを使う。

### 主語

| コード | 意味 |
| --- | --- |
| `SELF` | このユニットが |
| `YOUR` | あなたのユニットが |
| `RIVAL` | 対戦相手のユニットが |

### 契機

| コード | 意味 |
| --- | --- |
| `CIP` | フィールドに出た時 |
| `PIG` | 破壊された時 |
| `OC` | オーバークロックした時 |
| `ATK` | アタックした時 |
| `BLOCK` | ブロックした時 |
| `TURN_END` | ターン終了時 |

例:

```text
SELF_CIP
YOUR_CIP
RIVAL_CIP
SELF_PIG
SELF_OC
SELF_ATK
SELF_BLOCK
SELF_TURN_END
TRIGGER_ANY
TRIGGER_<EVENT_TYPE>
INTERCEPT_ANY
INTERCEPT_<WINDOW>
```

変換後の `cards.normalized.json` では、必要に応じてエンジン内部イベント名へ展開してよい。

例:

```text
SELF_CIP -> unit_entered where source_unit == ability_source_unit
YOUR_CIP -> unit_entered where source_unit.owner == ability_owner and source_unit != ability_source_unit
RIVAL_CIP -> unit_entered where source_unit.owner != ability_owner
```

`TRIGGER_<EVENT_TYPE>` は、原因イベントの `type` を大文字化した値と対応する。

例:

```text
TRIGGER_UNIT_ENTERED -> unit_entered 発生後に確認する trigger
TRIGGER_CARDS_DRAWN -> cards_drawn 発生後に確認する trigger
```

`INTERCEPT_<WINDOW>` は、engine が開いた intercept window 名と対応する。

例:

```text
INTERCEPT_ATTACK -> attack window で発動確認する intercept
```

任意実行 trigger は現時点では存在しない。trigger は timing が一致した場合、強制発動する。

### CIP 収集順

ターンプレイヤーがユニットを場に出したとき、`CIP` として扱う。

`CIP` イベントでは、まず場に出されたユニット自身だけを見て `SELF_CIP` を持つか調べる。`SELF_CIP` を持っていれば、その能力を解決する。

続けて、自陣に出ている他のユニットを左から順に見て、`YOUR_CIP` を持つか調べる。ここでは `SELF_CIP` は調べない。

さらに、対戦相手の場に出ているユニットを左から順に見て、`RIVAL_CIP` を持つか調べる。ここでも `SELF_CIP` は調べない。

例:

```text
自陣 0 に既存ハッパロイドがいる。
自陣 1 に新しいハッパロイドを出す。

1 の新しいハッパロイドの SELF_CIP は発動する。
0 の既存ハッパロイドの SELF_CIP は発動しない。
0 の既存ハッパロイドが YOUR_CIP を持つ場合だけ、その YOUR_CIP を発動候補にする。

対戦相手の場に既存ハッパロイドがいる場合も、その既存ハッパロイドの SELF_CIP は発動しない。
対戦相手の既存ユニットが RIVAL_CIP を持つ場合だけ、その RIVAL_CIP を発動候補にする。
```

## `priority`

初期案:

```json
{
  "band": "unit",
  "order": "source_only"
}
```

| フィールド | 値 | 説明 |
| --- | --- | --- |
| `band` | `unit` | ユニット能力 |
| `band` | `trigger` | トリガー能力 |
| `band` | `intercept` | インターセプト能力 |
| `order` | `source_only` | イベント発生源だけを見る |
| `order` | `left_to_right` | 左から右 |

M1-M3 の unit のみ実装では、`SELF_*` は `order: source_only`、`YOUR_*` / `RIVAL_*` は `order: left_to_right` を基本とする。

## `condition`

発動条件が追加で必要な場合に書く。

条件なし:

```json
null
```

例:

```json
{
  "type": "source_level_at_least",
  "level": 2
}
```

このターンに、発生源以外の条件を満たすカードを使っている:

```json
{
  "type": "used_other_card_this_turn",
  "owner": "owner",
  "exclude_source": true,
  "min_cp": 2,
  "color": "緑"
}
```

初期実装では、未使用でもよい。

## `cost_steps`

「そうした場合」の前半や、ライフ支払い、手札破棄などのコストを表す。

コストなし:

```json
[]
```

例:

```json
[
  {
    "effect": "discard_from_hand",
    "player": "owner",
    "count": 1,
    "selector": {
      "type": "owner_hand"
    }
  }
]
```

処理方針:

- `cost_steps` がすべて成功した場合のみ `effect_steps` を実行する。
- コスト支払い不能なら能力は解決失敗として記録し、効果は実行しない。

## `selector`

効果対象を選ぶ必要がある場合に書く。

対象選択なし:

```json
null
```

相手ユニットを 1 体選ぶ:

```json
{
  "id": "target",
  "type": "unit",
  "controller": "rival",
  "count": 1,
  "required": true
}
```

自分のユニットを 1 体選ぶ:

```json
{
  "id": "target",
  "type": "unit",
  "controller": "owner",
  "count": 1,
  "required": true
}
```

対戦相手のトリガーゾーンからランダムに 1 枚選ぶ:

```json
{
  "id": "target",
  "type": "trigger_zone_card",
  "controller": "rival",
  "count": 1,
  "required": false,
  "random": true
}
```

対戦相手の手札からランダムに 1 枚選ぶ:

```json
{
  "id": "target",
  "type": "hand_card",
  "controller": "rival",
  "count": 1,
  "required": false,
  "random": true
}
```

対象不適正時:

- 対象選択不可能時には、効果を発動させない。
- 選択可能な対象がいるが無効な対象が選ばれた時には、`invalid_response` を記録し、先頭の合法候補にフォールバックする。

## `effect_steps`

初期対応候補:

| effect | 説明 |
| --- | --- |
| `consume_action` | 行動権を消費する |
| `draw_cards` | カードを引く |
| `move_card` | カードをゾーン間移動する |
| `deal_damage_to_unit` | ユニットにダメージを与える |
| `deal_life_damage` | ライフにダメージを与える |
| `modify_bp` | BP を変更する |
| `destroy_unit` | ユニットを破壊する |
| `destroy_trigger_zone_card` | トリガーゾーンのカードを破壊する |
| `discard_from_hand` | 手札を捨てる |
| `draw_card_by_category` | 指定カテゴリのカードを引く |
| `move_random_discard_to_hand` | 捨札から条件に合うカードをランダムに手札へ戻す |
| `move_discard_to_hand` | 捨札から選択したカードを手札へ戻す |
| `recover_action` | 行動権を回復する |
| `return_unit_to_hand` | ユニットを手札へ戻す。手札上限時は捨札へ送る |
| `set_level` | レベルを変更する |
| `change_cp` | CP を変更する |

### `draw_cards`

```json
{
  "effect": "draw_cards",
  "player": "owner",
  "count": 1
}
```

### `deal_damage_to_unit`

```json
{
  "effect": "deal_damage_to_unit",
  "target": "target",
  "amount": 3000
}
```

### `modify_bp`

```json
{
  "effect": "modify_bp",
  "target": "source",
  "amount": 1000,
  "duration": "turn"
}
```

`duration` 候補:

```text
turn       ターン終了まで
permanent 盤面を離れるまで
battle     戦闘終了まで
```

### `change_cp`

```json
{
  "effect": "change_cp",
  "player": "owner",
  "amount": 2
}
```

### `destroy_trigger_zone_card`

```json
{
  "effect": "destroy_trigger_zone_card",
  "target": "target"
}
```

この効果は、`selector.type: trigger_zone_card` と組み合わせる。

### `discard_from_hand`

```json
{
  "effect": "discard_from_hand",
  "target": "target"
}
```

この効果は、`selector.type: hand_card` と組み合わせる。

### `draw_card_by_category`

```json
{
  "effect": "draw_card_by_category",
  "player": "owner",
  "category": "intercept",
  "count": 1
}
```

## 初期対象カードの記述例

以下は形式例であり、実際の `source_text` と効果量は Excel 確認後に更新する。

### ハッパロイド

```json
{
  "card_name": "ハッパロイド",
  "abilities": [
    {
      "ability_key": "1-0-040:a1",
      "ability_name": "ドロー",
      "source_text": "このユニットがフィールドに出た時、カードを1枚引く。",
      "status": "supported",
      "timing": "SELF_CIP",
      "optional": false,
      "priority": {
        "band": "unit",
        "order": "source_only"
      },
      "condition": null,
      "cost_steps": [],
      "selector": null,
      "effect_steps": [
        {
          "effect": "draw_cards",
          "player": "owner",
          "count": 1
        }
      ]
    }
  ]
}
```

### ランサー

```json
{
  "card_name": "ランサー",
  "abilities": [
    {
      "ability_key": "1-0-004:a1",
      "ability_name": "ダメージブレイク",
      "source_text": "このユニットがアタックした時、対戦相手のユニットを1体選び、3000ダメージを与える。",
      "status": "deferred",
      "timing": "SELF_ATK",
      "optional": false,
      "priority": {
        "band": "unit",
        "order": "source_only"
      },
      "condition": null,
      "cost_steps": [],
      "selector": {
        "id": "target",
        "type": "unit",
        "controller": "rival",
        "count": 1,
        "required": true
      },
      "effect_steps": [
        {
          "effect": "deal_damage_to_unit",
          "target": "target",
          "amount": 3000
        }
      ]
    }
  ]
}
```

## 変換ユーティリティの検証項目

`normalizer` は少なくとも次を検証する。

- Excel に存在しない `card_no` が `ability_mapping.json` に含まれていないこと。
- `card_name` が Excel 側のカード名と一致すること。
- Excel 側の能力名が `ability_name` と一致すること。
- `status: supported` の能力は `timing` と `effect_steps` を持つこと。
- `timing` が既知コードであること。
- `effect_steps[].effect` が既知 effect であること。
- `selector` を参照する `effect_steps` は、対応する selector id を持つこと。
- 初期対象カード 9 枚について、未対応能力が残っていないこと。

## レポート出力

`cardpool_report.json` には、少なくとも次を出力する。

```json
{
  "schema_version": 1,
  "source_excel": "carddata/text-of-joker.cardpool.xlsx",
  "card_count": 100,
  "supported_ability_count": 1,
  "unsupported_abilities": [],
  "deferred_abilities": [],
  "warnings": []
}
```

## 未決事項

```text
card_no を Excel から常に取得できるか:

初期対象 9 枚の正確な card_no:

Excel の source_text と ability_mapping の source_text を完全一致させるか:

カード名重複時のデッキレシピ表現:

複数 selector が必要な能力の表現:

複数 ability が同名の場合の ability_key 付番:
```
