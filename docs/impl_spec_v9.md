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
- 候補:
  - `carddata/manual/abilities/1-0-001.json` のようなカード別ファイル
  - `carddata/manual/abilities/1-0/red.json` のようなセット・色別ファイル
- 統合後の生成物は現在の `ability_mapping.json` と互換にする。
- 移行する場合は、既存 normalizer / tests / cardpool report が変わらないことを最優先にする。

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

### V9-4 scenario catalog の整理

- `io/scenario_cli.py` は価値のある一覧性を保ちつつ肥大化している。
- v9 ではいきなり大分割せず、まず scenario 名、対象カード、確認状態を機械的に出せる catalog を検討する。
- `docs/scenario_cli_v7.md` は v7/v8 名のまま育っているため、将来的に `docs/scenario_catalog.md` へ移す。

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
