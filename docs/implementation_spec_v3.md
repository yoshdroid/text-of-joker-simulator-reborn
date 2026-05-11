# Text of Joker Simulator Reborn 実装仕様書 v3.0

## 1. v3 の位置づけ

v2 までで、カードプール正規化、能力マッピング、主要なエンジン部品、JSON Lines 形式の子プログラム通信、match runner、replay 記録の基礎が実装済みである。

v3 では、これらを「本体実行できる対戦プログラム」としてまとめる。

主目的は下記である。

- decklist を読み込んで初期 GameState を作成できる。
- 2つのプレイヤーを指定して 1 match を最後まで進行できる。
- sample player 同士、および外部子プロセス player を起動して対戦できる。
- 対戦結果と replay record をファイル出力できる。
- replay record を再実行して、同じ event log になることを検証できる。

## 2. v2 時点で実行できること

### 2.1 cardpool utility

Excel と `ability_mapping.json` を読み込み、正規化カードプールを生成できる。

```powershell
python -m tojs_reborn.cardpool.cli --excel <cards.xlsx> --mapping carddata/manual/ability_mapping.json --output-dir carddata/generated
```

### 2.2 engine demo

ハッパロイドの CIP 動作を確認する最小 demo を実行できる。

```powershell
python -m tojs_reborn.engine.demo_happaloid
```

### 2.3 sample player

JSON Lines protocol で `request_action` / `choice_request` に応答する sample player を起動できる。

```powershell
python -m tojs_reborn.io.sample_player --mode first
python -m tojs_reborn.io.sample_player --mode pass
```

### 2.4 Python API としての match runner

Python テストまたは内部 API から下記を実行できる。

- legal action 生成
- drive / set_trigger / override / overclock / attack / block / no_block
- trigger / intercept window
- 不正応答時の fallback
- match runner の intent 記録
- match runner replay

## 3. v3 の完成条件

v3 完了時点で、下記のようなコマンドで 1 match を実行できる状態を目標とする。

```powershell
python -m tojs_reborn.io.match_cli --p1 sample:first --p2 sample:pass --deck1 decklists/sample_p1.json --deck2 decklists/sample_p2.json --seed 1 --max-turns 20 --replay out/replay.json
```

完了条件は下記である。

- decklist JSON を読み込み、カード定義に存在しない `card_name` / `card_no` を検出できる。
- decklist から player ごとの deck instance を作成できる。
- seed を指定した match は deterministic に実行できる。
- match 開始、turn 開始、action request、window、match 終了が event log に記録される。
- match 終了時に winner / reason / turn count を出力できる。
- replay JSON を保存できる。
- 保存した replay JSON を再実行し、event log の一致を確認できる。
- sample player 同士で対戦できる。
- 外部子プロセス player を JSON Lines protocol で起動して対戦できる。
- player の timeout / invalid response は fallback で継続し、その事実を event log に記録できる。

## 4. v3 で追加する想定モジュール

### 4.1 `tojs_reborn.io.decklist`

decklist の読み込みと validation を担当する。

想定する decklist JSON:

```json
{
  "deck_name": "sample_happaloid",
  "cards": [
    { "card_name": "ハッパロイド", "count": 3 },
    { "card_name": "ランサー", "count": 3 }
  ]
}
```

decklist は原則として `card_name` を使用する。
互換用に `card_no` も許可するが、通常のレシピ入力では `card_name` を使う。
`card_name` は正規化カードプールの `name` と完全一致する必要がある。
同名カードが複数ある場合は曖昧な decklist として validation error にする。

v3 初期では、テスト用の小さい decklist を許可する。

正式ルール用 validation は将来拡張とし、v3 では下記を必須とする。

- `cards` が存在する。
- `card_name` が正規化カードプールに存在し、一意に解決できる。
- 互換用の `card_no` が指定された場合は、正規化カードプールに存在する。
- `count` が 1 以上の整数である。
- 展開後の deck が 1 枚以上である。

追加で `--strict-deck-rule` を指定した場合のみ、正式デッキ枚数などを検証する設計にしておく。

### 4.2 `tojs_reborn.io.match_setup`

cardpool と decklist から `GameState` を構築する。

担当範囲:

- normalized cardpool の読み込み。
- player 0 / player 1 の `AgentInfo` 作成。
- decklist の順番に `CardInstance` を作成して deck に投入。
- `initial_deck_card_nos` を replay 用に保存。
- seed を `GameState.rng_state` または既存の rng 管理へ渡す。
- 初期 life / cp / hand / turn player を設定する。

### 4.3 `tojs_reborn.io.match_cli`

match 実行用 CLI entrypoint。

想定オプション:

```text
--cards carddata/generated/cards.normalized.json
--deck1 decklists/sample_p1.json
--deck2 decklists/sample_p2.json
--p1 sample:first
--p2 sample:pass
--seed 1
--max-turns 20
--max-actions-per-turn 20
--replay out/replay.json
--verify-replay
```

`--p1` / `--p2` の形式:

- `sample:first`
- `sample:pass`
- `cmd:<command line>`

`cmd:` は v3 で実装する外部子プロセス player 用である。

### 4.4 `tojs_reborn.io.process_player`

外部子プロセス player を起動し、stdin/stdout JSON Lines で通信する。

既存の `TextIOJsonLineTransport` / `JsonLinePlayer` を再利用する。

担当範囲:

- subprocess 起動。
- stdout から JSON Lines を読む。
- stdin へ request を送る。
- timeout 時に fallback する。
- 終了時に process を停止する。

## 5. match loop 仕様

v3 の match loop は、実ゲーム完全再現よりも「本体として対戦を進められること」を優先する。

### 5.1 match 開始

match 開始時に `match_started` event を記録する。

記録候補:

- seed
- player ids
- deck names
- deck card count
- cardpool version または file path

### 5.2 turn 開始

turn 開始時に既存の `start_turn` 相当処理を呼ぶ。

v3 初期値案:

- 初期 life: 7
- 初期 hand: 0 または仕様追記待ち
- turn draw: 1
- turn CP: 既存実装の最小ルールを使用
- 先攻 1 turn 目攻撃可否: 仕様追記待ち

未確定項目は v3 の「追加で必要な仕様情報」に記録し、実装時はテストしやすい暫定値を明記する。

### 5.3 action phase

turn player に legal actions を提示し、1 action ずつ処理する。

turn 終了条件:

- player が `pass` を選んだ。
- legal actions が `pass` のみになった。
- `max-actions-per-turn` に到達した。
- match が終了した。

`max-actions-per-turn` 到達は、無限ループ防止用の暫定終了条件として event log に記録する。

### 5.4 window

既存の `windows.py` を使用する。

v3 で match CLI から確認したい window:

- unit_entered trigger
- unit_entered intercept
- unit_attacked intercept

window 中の player choice は、match runner の action request と同様に記録する。

### 5.5 match 終了

match 終了時に `match_ended` event を記録する。

終了理由候補:

- `life_zero`
- `max_turns`
- `max_actions_per_turn`
- `runner_error`

v3 では deck refresh が存在するため、deck out による敗北は未確定扱いとする。

## 6. replay 仕様

v3 の replay record は下記を含む。

```json
{
  "version": 3,
  "seed": 1,
  "initial_state": {},
  "players": {},
  "intents": [],
  "events": [],
  "result": {}
}
```

v3 で保証する replay:

- match runner が記録した action / choice intent を再適用できる。
- 再実行後の event log が保存時の event log と一致する。
- replay verification の成功 / 失敗を CLI の終了コードに反映できる。

v3 でまだ保証しない replay:

- 異なる cardpool version での再現。
- 外部 player の再問い合わせ。
- 自然言語能力テキストからの再解釈。

## 7. protocol 仕様

v3 では既存 protocol を維持し、必要な message を追加する。

既存:

- `request_action`
- `action_selected`
- `choice_request`
- `choice_selected`
- `game_over`

追加検討:

- `hello`
- `state_update`
- `match_started`
- `match_ended`

v3 実装では、子プログラムに対して最低限 `request_action` / `choice_request` を送れば動作する状態を維持する。

`state_update` を送るかどうかは実装時に決める。送る場合でも、子プログラムが無視できる protocol にする。

## 8. v3 実装アイテム

### V3-1 decklist loader

- `decklist.py` を追加する。
- decklist JSON を読み込む。
- cardpool に存在しない `card_name` / `card_no` を validation error にする。
- test deck 用の小さい deck を許可する。
- unittest を追加する。
- commit する。

### V3-2 match setup

- decklist から `GameState` を作る。
- deck instance と `initial_deck_card_nos` を設定する。
- seed 指定を反映する。
- unittest を追加する。
- commit する。

### V3-3 in-process full match loop

- sample player を Python API として使い、match を複数 turn 進める。
- `match_started` / `match_ended` event を追加する。
- `max_turns` / `max-actions-per-turn` を実装する。
- unittest を追加する。
- commit する。

### V3-4 match CLI

- `python -m tojs_reborn.io.match_cli` を追加する。
- sample player 同士の対戦を CLI で実行できる。
- replay JSON を出力できる。
- `--verify-replay` を実装する。
- unittest または subprocess test を追加する。
- commit する。

### V3-5 external process player

- `cmd:<command line>` 形式の player 指定を実装する。
- `sample_player.py` を外部子プロセスとして起動し、match を進行できる。
- timeout / invalid response fallback を event log に残す。
- unittest を追加する。
- commit する。

### V3-6 replay verification CLI

- replay JSON 単体を検証する CLI を追加する。
- 例:

```powershell
python -m tojs_reborn.io.replay_cli --replay out/replay.json
```

- event log 不一致時に差分の概要を出す。
- unittest を追加する。
- commit する。

### V3-7 documentation / devlog

- `.devlog/2026-05-11_v3_match_cli.md` を作成する。
- README または docs に本体実行手順を追記する。
- 現時点で実装済みの本体機能と未実装の実ゲーム仕様を分けて記載する。
- commit する。

## 9. v3 で追加したいテスト

- decklist に未知 `card_name` / `card_no` があると失敗する。
- decklist に重複名で曖昧な `card_name` があると失敗する。
- decklist の `count` が 0 以下だと失敗する。
- decklist から deck instance が期待枚数作られる。
- match setup 後に `initial_deck_card_nos` が replay 用に保持される。
- sample:first vs sample:pass が `max_turns` まで進行し、`match_ended` を出す。
- replay JSON 保存後、再実行検証に成功する。
- external process の sample player と通信できる。
- external process が timeout した場合、fallback action で継続する。
- invalid JSON を返す player に対して fallback する。

## 10. v3 では扱わないこと

下記は v3 の範囲外とする。

- 全カードの能力実装。
- 実ゲーム完全準拠の deck 構築ルール。
- mulligan。
- JOKER / キャラクター固有能力。
- UI。
- 強い AI。
- ネットワーク対戦。
- 複数 match の tournament runner。

## 11. 追加で必要な仕様情報

実装中に暫定値を置けるが、最終的には下記の仕様入力が必要である。

### 11.1 初期状態

- 初期 life。
  7。レギュレーション設定にて変更可能。システム的な上限は12。
- 初期 hand 枚数。
  デッキから 4枚 drawした状態とする。レギュレーション設定にて変更可能。
- mulligan の有無。
  初期 handの内容を確認したプレイヤーは mulliganリクエストを出す。5回まで実行可能とする。レギュレーションえっていにて変更可能
- 先攻 / 後攻の決定方法。
  --p1で起動したものを先攻とする。
- 先攻 1 turn 目の攻撃可否。
  スピードムーブ効果をもっていても、OC発動しても、攻撃できない。

### 11.2 turn 進行

- turn 開始時の CP 増加ルール。
  先攻 2 3 4 5 6 7 7 7 7 7
  後攻 3 3 4 5 6 7 7 7 7 7
  レギュレーション設定にて変更可能。
- turn 開始時の draw 枚数。
  先攻 0 2 2 2 2 2 2 2 2 2
  後攻 2 2 2 2 2 2 2 2 2 2
  レギュレーション設定にて変更可能。
- action phase で pass 後に相手へ priority が移るか、turn が終了するか。
  ターンプレイヤーの行動としてターン終了が選ばれ、相手にターンを渡す。
- 1 turn 中に同じ unit が攻撃できる回数。
  攻撃したユニットは、戦闘解決後、またはプレイヤーアタック後、行動権を失う。
  行動権は、戦闘勝利し LV2から LV3になり OCによる回復、ユニット・トリガー・インターセプト効果による回復など復活することがある。
  行動権がある限り 1ターン中に同じユニットが何回でも攻撃できる。

### 11.3 勝敗条件

- life 0 時の即時敗北でよいか。
  よい。
  例外は燃え広がる戦火カード効果による両プレイヤー同時 life 0で、両者敗北となる。
- deck が空の時の扱い。
  ライブラリアウトによる敗北はない。ドロー発生時デッキリフレッシュしゲームは継続する。
- refresh deck が発生する場合のペナルティ。
  なし。
- `max_turns` 到達時の winner 判定。
  ライフ同点時、後攻プレイヤーの勝利。
  ライフが異なる場合、値の大きいプレイヤーの勝利。

### 11.4 deck 構築

- 正式 deck 枚数。
  40枚。
  レギュレーション設定にて変更可能。
- 同名カード上限。
  3枚。
  レギュレーション設定にて変更可能。
- trigger / intercept / unit の枚数制限。
  なし。
  レギュレーション設定にて各種上限枚数変更可能。unit / evolve onlyのようなデッキ構築ルールが設定できるように。
- 同一カード番号と同名カードの扱い。
  このシミュレータでは、一つのカード番号には一つのカード名前が対応することにする。そうでなければ Excelカードプールの誤りであり、修正する。

### 11.5 protocol

- 子プログラムに毎 action 前 `state_update` を送るべきか。
  送る。
  たとえば対戦相手のターンでアタック宣言がされたとき、場のどのユニットが攻撃してくるのかをみてブロックするかしないかを判断するような進行にしたい。
- 子プログラムが `hello` を返す handshake を必須にするか。
  helloのやりとりは初期検討時の仕組み確認を目的としていたので、なくてもよい。helloの代わりに playerの名前など agent情報を対戦相手に伝える目的で実装することが可能か検討する。
- 子プログラムに private hand をどの形式で渡すか。
  下記ふたつを併用する。
  B. public_state と private_view を分ける
  C. legal_actions の中に使える手札情報だけ入れる
- request timeout の標準秒数。
  0.5秒にする。

## 12. v3 開始前の確認

v2 終了時点の確認結果:

```text
python -m unittest -v
Ran 58 tests in ...s
OK
```

v3 では、各 item ごとに実装、test、commit を繰り返す。
