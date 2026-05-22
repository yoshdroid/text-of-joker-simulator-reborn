# implementation spec v9

v8 では 100 種カードのエンジン実装、GUI 確認シナリオ、リプレイ目視確認の進め方がかなり安定した。
v9 は新カード追加と細かい未実装ゲーム仕様の追加に入る前に、カード追加基盤を少し整える。

## 目的

- カード追加時の変更範囲を小さく保つ。
- 実装済み / 部分実装 / 未実装カードを機械的に確認できるようにする。
- 発動不能理由や scenario 管理を、GUI 確認に使いやすい形へ寄せる。
- 大きなリファクタリングは避け、v8 で安定した engine / GUI の手触りを保ったまま段階的に進める。

## カード追加の基本方針

カード効果は次の 3 層に分けて扱う。

1. カード定義層
   - `carddata/manual/ability_mapping.json` に timing / condition / selector / cost_steps / effect_steps を書く。
   - 既存 primitive で表現できるカードは Python コードを増やさずここだけで追加する。

2. 効果 primitive 層
   - `draw_cards`, `modify_bp`, `deal_damage_to_unit`, `grant_keyword`, `move_discard_to_hand` など、カードをまたいで使う小さな engine effect。
   - 新カード実装で Python 追加が必要な場合、まず新しい汎用 primitive として切り出せるか検討する。

3. 特殊ルール層
   - ロデオドライヴの post block choice、沈黙、呪縛、貫通、戦闘前離脱など、ゲーム構造に関わるもの。
   - カード固有 special case として閉じ込めず、timing / keyword / rule として名前を付ける。

## v9 推奨実装順

### V9-1 カード実装ステータス表の自動生成

- `carddata/generated/cards.normalized.json` と `carddata/generated/cardpool_report.json` から、カードごとの実装状態を markdown 表にする。
- 状態は `supported`, `partial`, `deferred`, `unsupported`, `no_ability` のように集約する。
- ability count は `supported/deferred/unsupported` 形式で表示する。
- v9 以降のカード追加前後で、差分を見れば進捗が分かるようにする。

### V9-2 ability_mapping の分割方針を決める

- すぐに分割移行せず、まず分割後の形を決める。
- Excel 側は今後セット単位または追加パック単位でシートを分ける想定とする。
- JSON 側も Excel シート単位に合わせ、次のようなディレクトリ構成を第一候補にする。
  - `carddata/manual/abilities/1-0/ability_mapping.json`
  - `carddata/manual/abilities/1-0-EX/ability_mapping.json`
  - `carddata/manual/abilities/1-1/ability_mapping.json`
- 統合後の生成物は現在の `ability_mapping.json` と互換にする。
- 移行する場合は、既存 normalizer / tests / cardpool report が変わらないことを最優先にする。
- 実装視点では、カード別ファイルよりもシート単位ファイルの方が当面扱いやすい。
  - Excel 追加範囲と JSON 追加範囲が一致するため、レビューしやすい。
  - セット単位で cardpool report / status report の差分を追いやすい。
  - `1-0-EX` のような例外的な追加枠も自然に扱える。
  - ファイル数が増えすぎず、現行の `ability_mapping.json` に近い一覧性を保てる。
- 一方で、1ファイルが大きくなりすぎたセットは、将来的に `red.json` / `green.json` など色別へ再分割できる余地を残す。
- normalizer は最終的に以下のどちらも読めるようにする。
  - 現行互換: `carddata/manual/ability_mapping.json`
  - 分割形式: `carddata/manual/abilities/*/ability_mapping.json` をマージしたもの
- マージ時のルール:
  - `schema_version` は全ファイルで一致していること。
  - `cards` の key が重複した場合はエラーにする。
  - 出力順はディレクトリ名、card_no の昇順で安定化する。
  - 生成後の統合 mapping は現行形式と同じ `{ "schema_version": 1, "cards": {...} }` にする。

### V9-3 発動不能理由の構造化

- `engine/activation_requirements.py` を中心に、発動不可理由を返せる小さな API を追加する。
- 例:
  - CP 不足
  - 同色ユニット不在
  - window 不一致
  - condition 不一致
  - valid target 不在
- まずは debug / report 用とし、既存の発動処理を壊さない。
- 将来的には replay GUI の window open 行で「発動候補」「発動できない理由」を表示できるようにする。

V9-3 first implementation:
- `engine.activation_requirements.explain_card_activation()` returns `ActivationCheck(can_activate, reasons, details)`.
- Existing `card_can_activate()` remains as the boolean compatibility API.
- Current reason codes:
  - `insufficient_cp`
  - `missing_same_color_unit`
- Current scope is card-level activation requirements, especially intercept CP and same-color unit requirements.
- Future GUI/log work can display these reason codes for cards that are visible but not activatable.
- Future expansion candidates: window mismatch, condition mismatch, target missing.

### V9-4 scenario catalog の整理

- `io/scenario_cli.py` は価値のある一覧性を保ちつつ肥大化している。
- v9 ではいきなり大分割せず、まず scenario 名、対象カード、event count、replay path を機械的に出せる catalog を作る。
- `python -m tojs_reborn.io.scenario_cli --scenario all --catalog-markdown docs/scenario_catalog.md` で生成する。
- 生成元は実際の scenario replay とし、初期状態 / 最終状態の card instances から登場カードを集約する。
- 目視確認状態は当面 `docs/scenario_cli_v7.md` に残す。
- 将来的には `docs/scenario_cli_v7.md` の確認表を `docs/scenario_catalog.md` または別の machine readable catalog へ統合する。

### V9-5 新カード追加サイクル

以降のカード追加は次の単位を基本にする。

- `ability_mapping` 追加または primitive 追加
- engine test
- GUI 確認 scenario
- card status report 更新
- scenario catalog 更新
- git commit

複数カードを同一ゲーム場面にまとめられる場合は、v8 と同様にまとめる。
問題を見つけたらそこで止め、仕様確認を優先する。

## V9-1 実装メモ

`python -m tojs_reborn.cardpool.cli` に `--status-markdown` を追加し、カード実装ステータス表を生成する。

```powershell
python -m tojs_reborn.cardpool.cli --status-markdown docs/card_status_v9.md
```

生成される `docs/card_status_v9.md` は手編集せず、カード追加や mapping 更新後に再生成する。
