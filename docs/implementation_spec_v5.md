# Text of Joker Simulator Reborn 実装仕様書 v5.0

## 1. v5 の位置づけ

v4 までで、次の基盤はおおむね揃った。

- decklist から 1 match を実行できる。
- JSON Lines 子プログラム player と対戦できる。
- `public_state` / `private_view` を player に渡せる。
- action / choice / mulligan を replay intent として記録し、再実行できる。
- trigger / intercept window の最小実装がある。
- replay viewer で event と turn / match end の状態を確認できる。

v5 では、カード追加を急ぐ前に「子プログラムが安定して判断できる対戦環境」を作る。

主眼は次の 5 点。

- choice request の仕様を強くする。
- optional ability / window の pass と起動判断を整理する。
- trigger / intercept の公開情報と activation 情報を子プログラム向けに明確化する。
- match runner の終了条件・エラー処理・CLI 出力を整える。
- v6 以降のカード追加に備え、ability mapping と engine effect の拡張ポイントを明文化する。

## 2. v5 完了条件

v5 完了時点で、下記を満たす。

- `python -m unittest tests.test_engine tests.test_protocol -v` が通る。
- match CLI で sample player 同士の対戦を実行し、replay 保存・検証・viewer 表示ができる。
- 子プログラムが action / choice / mulligan / window の各局面を区別できる。
- choice request に、人間表示用 `display` と machine-readable な `target` 情報が含まれる。
- optional ability を「使う / 使わない」として replay に残せる。
- trigger / intercept activation の選択が replay で完全再現される。
- 不正応答・timeout・プロセス終了時の扱いが event と match result に残る。
- v5 で未確定の実ゲーム仕様が、本文の「追加で確認したい仕様」に列挙されている。

## 3. 現状でできること

### 3.1 match 実行

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 sample:first --p2 sample:pass --seed 1 --max-turns 20 --replay test_output/replay.json --verify-replay
```

### 3.2 外部 process player

```powershell
python -m tojs_reborn.io.match_cli --cards carddata/generated/cards.normalized.json --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --p1 "cmd:python -m tojs_reborn.io.sample_player --mode first" --p2 "cmd:python -m tojs_reborn.io.sample_player --mode pass" --max-turns 20 --replay test_output/replay.json --verify-replay
```

### 3.3 replay viewer

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/replay.json --no-payload
```

```powershell
python -m tojs_reborn.io.replay_viewer --cards carddata/generated/cards.normalized.json --replay test_output/replay.json --event-type match_ended --only-state
```

## 4. v5 実装アイテム

### V5-0 追加検討アイテム
プレイヤープログラムのサンプルとして、起動時に GUIを立ち上げ、
自陣のフィールドユニット、手札、トリガーゾーン、敵側のフィールドユニットを画像表示してほしい。
git ignoreに carddata/images/ を追加している。この下に、jpgフォーマットでカード画像を格納している。
カード番号を prefixとしたファイル名で保存されており、対応したものを表示する。
ゲーム進行に従いイベントが発生するたび描画を更新し、よりプレイヤー目線での出来事を視認できるようにしたい。

実現のために必要な不足情報があれば問い合わせてください。

### V5-1 choice request の表示情報と target schema

現状の choice request は、合法選択肢を返せば動くが、子プログラムが判断しやすい情報がまだ少ない。

実装方針:

- `choice_request_message` に `display` を追加する。
- `legal_choices` の各要素に `display` と `target` を追加する。
- unit target の場合、少なくとも次を含める。
  - `unit_id`
  - `controller`
  - `card_instance_id`
  - `card_no`
  - `card_name`
  - `level`
  - `bp`
  - `damage`
  - `exhausted`
- hand / trigger zone card target の場合、公開可否に応じた情報だけを含める。
- engine 判定には既存の machine-readable id を使い、`display` は判定に使わない。

追加テスト:

- Lancer / Bloodhound などの target required ability で、choice request に対象 unit の情報が含まれる。
- illegal choice を返した場合、従来どおり先頭合法選択肢へ fallback し、`invalid_response` または `player_response_fallback` が残る。
- replay で choice request / selected choice の event log が一致する。

### V5-2 optional ability の choice 化

現状、optional intercept は window action として選べるが、unit ability 側の optional は十分に整理されていない。

実装方針:

- `ability.optional == true` の unit ability は、解決前に `optional_ability` choice を発行できるようにする。
- 選択肢は `use_ability` / `pass_ability` とする。
- 強制 ability は従来どおり自動解決する。
- optional choice は replay intent に残す。
- 子プログラム timeout / invalid response の fallback は `pass_ability` を基本とする。

追加テスト:

- optional ability を pass した場合、`ability_resolved` が発生しない。
- optional ability を use した場合、従来どおり effect が解決される。
- replay で optional ability の use / pass が再現される。

追加で確認したい仕様:

```text
optional unit ability の default fallback は「使わない」でよいか。
trigger は強制、intercept は任意、unit optional は任意、という整理でよいか。
```

### V5-3 window request の protocol 明確化

現状 window action は `request_action` の legal action として渡っている。子プログラムから見ると通常 action と window action の区別が弱い。

実装方針:

- `request_action` に `request_context` を追加する。
- 値の例:
  - `turn_action`
  - `block_action`
  - `trigger_window`
  - `intercept_window`
  - `optional_ability`
- window action の `display` に window 名と cause event を含める。
- `pass_window` は window type を必ず持つ。

追加テスト:

- 通常行動 request の `request_context` が `turn_action` になる。
- block request の `request_context` が `block_action` になる。
- intercept window request の `request_context` が `intercept_window` になる。
- sample child program が未知 field を無視して従来どおり動く。

### V5-4 trigger / intercept の公開情報整理

trigger zone は「自分にはカード内容が見える」「相手には公開済み情報だけ見える」という方針を v4 で入れた。v5 では activation 時の公開状態をより明確にする。

実装方針:

- `trigger_activated` / `intercept_activated` event の payload に公開されたカード情報を含める。
- activated 後は discard pile に移動するため、以降は全員がカード内容を見られる。
- `public_state` の opponent trigger zone は、未公開なら count / color / revealed_card_no のみとする。
- `private_view` の own trigger zone は card_no / name / category / cp を含める。
- replay viewer では activation event にカード名を出せるようにする。

追加テスト:

- opponent の未公開 trigger zone が private 情報を漏らさない。
- activation 後の discard pile でカード名が見える。
- viewer の activation 行にカード名が表示される。

追加で確認したい仕様:

```text
セット済み trigger / intercept の色は相手に常時公開でよいか。
カード種別 trigger / intercept は相手に常時公開でよいか。
```

### V5-5 match result と process 異常系

現状 timeout / invalid response は fallback で継続できる。v5 では子プロセス異常時の見え方を整える。

実装方針:

- 子プロセスが終了して stdout が閉じた場合、`player_response_fallback` に `reason: "process_closed"` 相当を残す。
- timeout 回数を player ごとに集計できるようにする。
- `--max-fallbacks-per-player` を検討する。
- 上限を超えた場合、match result を `player_error` として終了する。
- `match_ended` payload に `winner_player_id` / `reason` / `turn_count` / `error_player_id` を含める。

追加テスト:

- timeout が fallback event に残る。
- 上限を超えた場合、match が `player_error` で終了する。
- replay で player_error 終了が再現される。

追加で確認したい仕様:

```text
子プログラム異常終了時は即敗北でよいか、それとも fallback 継続でよいか。
timeout は何回まで許容するか。
```

### V5-6 match CLI / docs 更新

v3 以降 CLI の実機能が増えたため、実行手順書を更新する。

実装方針:

- `docs/match_cli_v5.md` を作成する。
- decklist by card_name の例を載せる。
- sample player / external process player の例を載せる。
- replay verify / replay viewer / filters の例を載せる。
- 子プログラムに届く JSON Lines の例を載せる。

追加テスト:

- docs に載せる代表コマンドのうち、テスト可能なものを unit test または smoke test に含める。

### V5-7 ability mapping report の強化

カードを増やす前に、Excel -> mapping -> normalized の差分確認をしやすくする。

実装方針:

- `cardpool_report.json` に effect / timing / status の集計を追加する。
- `supported` ability のうち engine が未対応の effect を検出する。
- `optional: true` なのに optional 解決未対応の timing があれば warning にする。
- ability_mapping の `source_text` 欠落を warning にする。

追加テスト:

- 未知 effect が warning になる。
- `supported_ability_count` と `effect_counts` が出力される。
- source_text 欠落が warning になる。

### V5-8 追加カード候補の選定

v5 の最後に、v6 で追加するカード候補を決める。

候補:

- optional unit ability を持つカード。
- 複数 target または target 条件を持つカード。
- trigger / intercept window の仕様確認に使えるカード。
- BP 修正の duration 違いを確認できるカード。
- discard pile / deck search / hand reveal に関わるカード。

v5 では原則として大量追加しない。追加する場合も、仕様テスト目的の 1-3 枚に限定する。

選定結果は `docs/v6_card_candidates.md` にまとめる。

## 5. protocol 拡張案

### 5.1 request_action

```json
{
  "type": "request_action",
  "request_id": "P1:action:12",
  "player_id": "P1",
  "request_context": {
    "kind": "turn_action",
    "cause_event_no": null,
    "window": null
  },
  "state_revision": 12,
  "public_state": {},
  "private_view": {},
  "legal_actions": []
}
```

### 5.2 choice_request

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
        "bp": 1000,
        "damage": 0,
        "exhausted": false
      },
      "display": {
        "label": "P2 ブラッドハウンド LV1 BP1000"
      }
    }
  ],
  "public_state": {},
  "private_view": {}
}
```

### 5.3 optional ability choice

```json
{
  "type": "choice_request",
  "request_id": "optional:22",
  "player_id": "P1",
  "choice": {
    "type": "optional_ability",
    "ability_id": "1-0-099:a1",
    "source_unit_id": null,
    "source_card_instance_id": "c0010"
  },
  "legal_choices": [
    {
      "type": "use_ability",
      "ability_id": "1-0-099:a1"
    },
    {
      "type": "pass_ability",
      "ability_id": "1-0-099:a1"
    }
  ]
}
```

## 6. v5 で扱わないこと

- 強い AI の実装。
- tournament / league runner。
- ネットワーク越しの対戦。
- UI。
- JOKER / キャラクター固有能力。
- 全カード対応。
- 実ゲーム完全準拠の priority system。

## 7. 実装順序案

1. V5-1 choice request の表示情報と target schema。
2. V5-3 window request の protocol 明確化。
3. V5-4 trigger / intercept の公開情報整理。
4. V5-2 optional ability の choice 化。
5. V5-5 match result と process 異常系。
6. V5-6 match CLI / docs 更新。
7. V5-7 ability mapping report の強化。
8. V5-8 追加カード候補の選定。

理由:

- 子プログラムの判断材料を先に増やす。
- window / optional の区別を protocol に出してから optional ability を実装する。
- 異常系と docs は、protocol の形が固まってから更新する。
- カード追加は、mapping report で不足が見える状態にしてから進める。

## 8. 追加で確認したい仕様

v5 実装前または実装中に確認したい内容。

```text
1. optional unit ability の default fallback は「使わない」でよいか。
  よい。
2. trigger は強制、intercept は任意、unit optional は任意、という整理でよいか。
  よい。
3. セット済み trigger / intercept の色は相手に常時公開でよいか。
  常時公開する。トリガーカードはすべて無色。
4. セット済み trigger / intercept のカード種別は相手に常時公開でよいか。
  カード種別は非公開情報。対戦相手のトリガーゾーンにあるのが triggerか interceptか コスト軽減目的の unit/evolveかは判断できず、推測するところに駆け引きをもたせたい。
5. 子プログラム timeout / process closed は即敗北にするか、一定回数 fallback 継続にするか。
  3回目の timeoutで敗北とする仕様にする。
6. fallback 上限を設ける場合、初期値はいくつにするか。
  3。
7. optional ability choice は通常の `choice_request` に統合するか、専用 message type に分けるか。
  カード効果を発動させるために必要な選択は、choice_requestとしてまとめてほしい。
  choice_requestが使われるケースを v5実装完了時にこの資料に追記 例示してほしい。
8. choice target の `bp` は現在値を出すか、基礎 BP と修正後 BP の両方を出すか。
  基礎 BP、修正後基礎 BP、ダメージやバフ計算後の BPのうち、最終的な BPを出す。
9. v6 で追加したいカード候補はどれか。
  v5実装完了時にあらためて指示したい。
```

## 9. v5 開始前の確認コマンド

```powershell
python -m unittest tests.test_engine tests.test_protocol -v
```

現時点の直近確認:

```text
Ran 74 tests
OK
```

## 10. 実装前決定事項

2026-05-11 時点の追記確認を受け、v5 は下記方針で実装する。

### 10.1 GUI の扱い

v5 では、本体統合 UI は扱わない。
ただし、JSON Lines 子プログラムのサンプルとして、GUI 表示できる player / viewer を検討・実装対象に含める。

位置づけ:

- engine / match runner は GUI に依存しない。
- GUI は外部 player と同じ protocol を使う。
- `state_update` / `request_action` / `choice_request` / `request_mulligan` を受け取り、表示と選択応答を行う。
- 自陣 battlefield / hand / trigger zone / 敵陣 battlefield を画像またはテキストで表示する。
- `carddata/images/` 配下の画像は git 管理外とし、card_no prefix の jpg/png を探索して使う。
- 画像がないカードは card_no / card_name のテキスト表示で代替する。
- 初期 GUI は観戦・デバッグ用途とし、選択操作は `--mode first/pass` による自動応答にする。
- JPG 表示には Pillow を使う。Pillow がない場合は画像枠に card_no / card_name を表示して継続する。
- `--no-window` は GUI を開けない環境で protocol 応答だけを確認するためのモードとする。

初期実装では、GUI 起動そのものを自動テスト対象にしない。
代わりに、state JSON から GUI 表示用 view model を作る処理を分離し、unit test する。

### 10.2 optional / window

- optional unit ability の timeout / invalid response fallback は `pass_ability` とする。
- trigger は強制。
- intercept は任意。
- unit optional ability は任意。
- optional ability の選択は専用 message type ではなく、通常の `choice_request` として扱う。
- v5 完了時に、`choice_request` が使われるケースを docs に追記する。

### 10.3 trigger / intercept 公開情報

- セット済み trigger / intercept の色は相手に常時公開する。
- trigger カードは現状すべて無色として扱う。
- セット済みカードの card category は相手には非公開とする。
- 相手からは、trigger / intercept / unit / evolve の判別ができない状態を目指す。
- activation 後は discard pile に移動するため、以降はカード内容を公開情報として扱う。

### 10.4 process player 異常系

- timeout / process closed は fallback 継続する。
- player ごとの fallback 上限初期値は 3。
- 3 回目の fallback 到達で、その player の敗北として match を `player_error` 終了する。
- `match_ended` payload には `error_player_id` を含める。

### 10.5 choice target BP 表示

choice target の unit 表示には次を含める。

- `base_bp`
- `modified_bp`
- `damage`
- `current_bp`

`current_bp` は、基礎 BP と modifier を反映した最終 BP とする。
damage は別 field として渡し、子プログラム側が「残り耐久相当」を判断できるようにする。

## 11. 修正後の実装順序

1. V5-1 choice request の表示情報と target schema。
2. V5-3 window request の protocol 明確化。
3. V5-0 GUI 用 view model の最小実装。
4. V5-4 trigger / intercept の公開情報整理。
5. V5-2 optional ability の choice 化。
6. V5-5 match result と process 異常系。
7. V5-6 match CLI / docs 更新。
8. V5-7 ability mapping report の強化。
9. V5-8 追加カード候補の選定。

GUI は早めに薄く入れ、以降の protocol 変更を「子プログラムから見て判断しやすいか」で確認できるようにする。
