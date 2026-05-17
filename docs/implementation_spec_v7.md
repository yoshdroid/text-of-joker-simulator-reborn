# Text of Joker Simulator Reborn 実装仕様書 v7.0

## 1. v7 の位置づけ

v5 で子プログラム protocol / replay / GUI の基盤を整え、v6 でカード対応とルール厳密化を進めた。
v7 では、カード追加だけを急がず、次の 4 系統を並行して強くする。

- ルール厳密化
- サンプルプレイヤー bot 強化
- カード対応拡張
- 可観測性と自動検証の強化

目的は、カード追加時に「効果は動くが試合としておかしい」「replay はあるが原因追跡しづらい」という状態を減らすこと。
v7 の実装は、小さい単位で実装、テスト、コミットを繰り返す。

## 2. v7 完了条件

- `python -m unittest tests.test_engine tests.test_protocol tests.test_cardpool_normalizer tests.test_decklist -v` が通る。
- sample player 同士の match CLI が replay 保存と verify replay まで通る。
- v7 で追加した bot / batch / viewer / rule の各変更に、最低 1 つの仕様テストがある。
- 追加したルールは `docs/implementation_spec_v7.md` または関連 docs に明記されている。
- v7 で決め切れなかった仕様は「追加で確認したい仕様」に残す。

## 3. 推奨実装順

### V7-1 サンプルプレイヤー bot 強化

最優先。
カード追加やルール厳密化の結果を、試合として自然に動かして確認できるようにする。

実装候補:

- `sample:first`: 既存通り、合法手の先頭を選ぶ。
- `sample:pass`: 既存通り、可能な限り pass。
- `sample:random`: seed 付きで合法手をランダム選択する。
- `sample:aggressive`: attack 可能なら attack を優先し、次に evolve / drive / trigger set を選ぶ。
- `sample:board`: battlefield を埋めることを優先し、5体上限、CP、進化元を考慮する。
- `sample:evolve`: evolve 可能なら evolve を優先し、進化 unit の即 attack まで確認しやすくする。

仮決定:

- まずは `sample:random` と `sample:aggressive` を実装する。
- random は replay 再現性を守るため、match seed から派生する deterministic RNG を使う。
- aggressive は完全な強さより、試合上の action 種類を広く発生させることを優先する。

要追記:

- bot の優先順位をどこまでゲーム戦略寄りにするか。
デバッグ時点では戦略よりは満遍なく行動をおこすことを期待したい。
- bot が choice request を受けた時、どの選択方針にするか。
randomはランダムに、それ以外は有効度が判定できるなら高い方を、それ以外は若い順番の候補を選ぶようにする
- random bot の seed を match seed と player id から作るか、bot 専用 seed を protocol で渡すか。
再現性を担保できる方法ならどちらでもよい。

### V7-2 match batch / smoke test CLI

複数 seed で sample match を連続実行し、クラッシュ、replay 不一致、例外を早期発見する。

実装候補:

- `python -m tojs_reborn.io.match_batch_cli --cards ... --deck1 ... --deck2 ... --p1 sample:random --p2 sample:aggressive --seeds 1-100`
- 各 match の result を JSON Lines または summary JSON に出力する。
- 失敗時は seed、player、turn、最後の event を表示する。
- `--verify-replay` を有効化できる。

仮決定:

- v7 初版では 10 seed 程度を高速に回す smoke test を作る。
- CI 的な用途では unittest から小さい batch を呼ぶ。

要追記:

- batch 結果を保存するディレクトリ。
BattleLogs/ とする。 git ignoreに追加する。
- replay を seed ごとに保存するか、失敗時だけ保存するか。
テストにおいては失敗時保存する。
（正規 simulator実行ならば seed値情報も含めて常時保存する）
- 勝率や平均ターン数などを集計対象に含めるか。
まだ不要。良い提案で、将来的には実装検討したい。

### V7-3 ルール厳密化

v6 までに一部の基本ルールを入れた。
v7 では、カード追加の前提になる共通ルールをもう一段固める。

実装済みの前提:

- hand 上限は 7。
- battlefield unit 上限は 5。
- 通常 unit は drive された turn に attack できない。
- evolve unit は drive された turn に attack できる。
- hand 内 override のみ対応し、battlefield unit への同名 override は不可。

候補:

- CP 上限と turn 開始時 CP 増加ルール。
- trigger zone 上限。
- 先攻 / 後攻の初期手札、初回 draw、初回 attack 可否。
- mulligan の回数と戻し方。
- deck 切れ時の refresh / loss 条件。
- 同時発生 event の優先順位をさらに整理する。
- action ごとの不正理由を machine-readable にする。

仮決定:

- まずは `ruleset` 定数を整理し、hand / battlefield / deck / trigger zone の上限を一か所で参照できるようにする。
- 次に trigger zone 上限を入れる。

要追記:

- CP 上限値。
12とする。
- turn 開始時 CP の正式な増え方。
先攻プレイヤー 2 3 4 5 6 7 7 7 7 7
後攻プレイヤー 3 3 4 5 6 7 7 7 7 7
- trigger zone 上限数。
4とする。
- deck 切れ時、refresh ができない場合の敗北条件。
deck 0の状態で drawが行われたら必ず refreshする。敗北条件にはかかわらない。

- 手札上限枚数は 7枚とする。
たとえばターン冒頭の 2枚ドローは、手札が上限に達したら以降無効になる。

### V7-4 カード対応拡張

v6 のカード対応スタイルを継続する。
カード 1 枚または効果 1 系統ごとに、mapping、engine、テスト、decklist、必要なら docs を更新してコミットする。

優先候補:

- trigger / intercept の実戦寄りカード。
- 戦闘中 BP 修正。
- 複数対象。
- 捨札からの選択。
- deck search / reveal。
- keyword layer。

確認用カード候補:

- `1-0-045` リーフィア: block 時 BP modifier。
- `1-0-061` 新品の鎧: trigger 強制発動と category draw。
- `1-0-097` 追い風: intercept window と CP 変化。
- `1-0-099` ハウリング: intercept optional と draw 2。
- `1-0-031` 見習い魔導士リーナ: 捨札から選択して hand へ。
- keyword `不屈`: 現状は SELF_TURN_END として表現。将来は SELF_CIP 付与 + persistent keyword に分離する。

仮決定:

- v7 では bot / batch が先。
- その後、`リーフィア` または `新品の鎧` を追加確認カードとして進める。

要追記:

- v7 で優先したいカード名。
- trigger / intercept の実ゲーム上の任意 / 強制の扱い。
triggerは強制発動。
interceptは必要コスト以上の CPを保有し、無色以外のカードは自分の場に同色のユニットが出ているときのみ任意で発動可能。
- keyword layer を v7 で着手するか、v8 に送るか。
着手する。

### V7-5 可観測性の強化

replay と GUI は動いているが、原因追跡のための情報をさらに増やす。

実装候補:

- replay viewer に legal action / selected action の簡易表示を追加する。
- action が legal action に出なかった理由を dump する debug CLI を作る。
- event ごとの state diff を表示できるようにする。
- GUI に life / CP / hand count / deck count / discard count / trigger zone count をより見やすく表示する。
- GUI に current event の説明文を表示する。
- `effect_fizzled` の reason を一覧化し、テストで安定させる。

仮決定:

- v7 では match batch の失敗調査に必要な最低限として、最後の event と match result の summary を強化する。

要追記:

- GUI 強化を v7 に含めるか。
おこなう。
- replay viewer の出力形式を人間向け優先にするか、機械処理しやすい JSON Lines も出すか。
今 プレイヤー視点でのカード画像表示 GUIが準備されている。
テスト動作を繰り返し確認していくデバッグにおいては、すべての情報を視認可能な唯一本体の情報を表示する GUIがほしい。
これを実装検討する。
カード画像は縮小表示して画面に収める。。
両プレイヤーの手札、トリガーゾーン、墓地、デッキ、すべて表示したい。
プレイヤー情報も、CP/LIFE/(未実装)JOKER/NAME/その他、値をテキストにて表示する。
右ペインには小さいフォントにて、すべてのイベントログをターミナルのように上から表示していく。
最下部にはシークバーを設け、再生・停止ボタンと、1STEPずつ操作できるボタンを用意する。
テスト結果やリプレイデータの特定箇所を 起動時引数として渡し、当該挙動を視認できる環境として準備する。

### V7-6 不変条件チェック

engine の各 action 後に、状態破損を早期検出する。

候補:

- 同じ card instance が複数 zone に存在しない。
- battlefield unit が参照する card instance は battlefield に対応する。
- `state.units` に存在しない unit id が battlefield に残らない。
- discard pile / hand / deck / trigger zone に存在する card instance id は `state.card_instances` に存在する。
- 各 player の battlefield unit 数が上限以下。
- hand 枚数が上限を超える場合、効果ごとの overflow 処理が明示されている。

仮決定:

- まずは `assert_game_state_integrity(state)` を engine debug helper として実装し、match batch と主要 unittest で使う。
- production match で常時有効にするかは後で決める。

要追記:

- integrity violation を例外にするか、event として記録するか。
例外扱いにしておく。
- match runner の各 action 後に必ず走らせるか、debug option にするか。
debugオプションとして常時有効化できるようにする。

### V7-7 ルール設定ファイル化

定数が増えてきたため、将来的に ruleset として外出しする。

候補:

- `default_ruleset.json`
- Python dataclass `Ruleset`
- `GameState.ruleset`
- match CLI option `--ruleset`

含める項目:

- hand 上限
- battlefield unit 上限
- trigger zone 上限
- deck 枚数
- 同名カード枚数上限
- 初期手札枚数
- mulligan 回数
- 初期 life
- CP 上限
- turn 開始 CP ルール

仮決定:

- v7 では定数整理まで。
- JSON ruleset は v8 以降でもよい。

要追記:

- 早期に ruleset JSON が必要か。
v8以降とする。
- GUI / replay に ruleset 情報を出す必要があるか。
出すようにして。

## 4. v7 推奨ループ

1. `sample:random` bot を追加し、テストとコミット。
2. `sample:aggressive` bot を追加し、テストとコミット。
3. match batch CLI の最小版を追加し、テストとコミット。
4. integrity check helper を追加し、テストとコミット。
5. ruleset 定数整理、trigger zone 上限などを追加し、テストとコミット。
6. 追加カード 1 枚を選び、mapping / engine / test / decklist / docs を更新してコミット。

## 5. 追加で確認したい仕様

- CP 上限値と turn 開始時 CP ルール。
既に記載、参照して。
- trigger zone 上限数。
既に記載、参照して。
- deck 切れ時、refresh 不能なら敗北か。
既に記載、参照して。
- random bot の seed 仕様。
既に記載、参照して。
- aggressive bot の行動優先順位。
既に記載、参照して。
- batch 実行時に replay を全保存するか、失敗時だけ保存するか。
既に記載、参照して。
- integrity check を常時有効にするか、debug option にするか。
既に記載、参照して。
- v7 で優先したい追加カード。
おすすめのカードをすべて実施する。
- keyword layer を v7 で実装するか。
既に記載、参照して。

