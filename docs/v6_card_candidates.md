# v6 追加カード候補

v5 では、カードを大量追加する前に player protocol と replay / viewer の足場を固めた。
v6 では、現在の engine が持つ能力処理を横断的に確認しつつ、不足している仕様を早めに発見できるカードを優先する。

## 1. 候補選定の方針

- 既存の supported effect を使い、すぐ仕様テスト化できるカードを先に使う。
- 新しい engine effect が必要なカードは、Excel 効果文と `ability_mapping.json` の対応を確認してから 1-3 枚ずつ追加する。
- 「対象選択」「window」「optional」「duration」「ランダム」「公開情報」のどれかを強く検証できるカードを優先する。
- 追加カードは decklist / replay viewer で人間が挙動確認しやすいものにする。

## 2. まずテスト強化に使う既存 supported カード

次のカードはすでに `ability_mapping.json` で supported になっているため、v6 冒頭では新規カード追加より先に仕様テストとサンプル decklist を厚くする。

| card_no | card_name | 検証したいこと |
| --- | --- | --- |
| `1-0-001` | ブラッドハウンド | OC 時の対象選択、効果ダメージ、choice target 表示 |
| `1-0-004` | ランサー | 攻撃時能力、対象選択、BP / damage 表示 |
| `1-0-005` | ヘルハウンド | 相手 trigger zone の非公開情報、ランダム破壊、公開後情報 |
| `1-0-027` | ミイラくん | PIG 順序、相手手札ランダム discard、replay 再現性 |
| `1-0-029` | カラスマドウ | PIG 順序、category draw、deck refresh 連携 |
| `1-0-043` | グラインドビートル | CP 変化、同一カード複数 ability、条件付き draw |
| `1-0-045` | リーフィア | block 時 BP modifier、turn duration 解除 |
| `1-0-061` | 新品の鎧 | trigger window、trigger 強制発動、category draw |
| `1-0-097` | 追い風 | intercept window、optional pass/use、CP 変化 |
| `1-0-099` | ハウリング | intercept optional、draw 2、choice / replay 表示 |

## 3. v6 で追加したい新規カード枠

### 3.1 optional unit ability

目的:
unit の `optional: true` を、intercept ではなく battlefield unit で検証する。

必要な仕様:

- optional unit ability の効果文上の「してもよい」相当の表現を Excel から確認する。
- 発動しない選択をした場合、以後同じ原因イベントで再確認するかを決める。

### 3.2 複数 target / target 条件

目的:
selector が 1 つだけの前提を崩し、子プログラムに十分な対象情報を渡せるか確認する。

必要な仕様:

- 複数対象を選ぶ能力で、同じ対象を複数回選べるか。
- 対象条件がカード属性、BP、種族、行動権、damage などに依存する場合の schema 表現。
- 対象不在時に ability 自体を不発にするか、発動して効果だけ不発にするか。

### 3.3 discard pile / deck search / reveal

目的:
公開領域と非公開領域の境界をさらに検証する。

必要な仕様:

- deck search 時、検索対象候補を player にどこまで見せるか。
- hand reveal は相手に一時公開するのか、以後公開済みカードとして扱うのか。
- discard pile からの移動は card instance を維持するか、新しい instance として扱うか。

### 3.4 duration が異なる BP 修正

目的:
現在の `duration: "turn"` 以外の BP modifier を追加し、解除タイミングを確認する。

必要な仕様:

- 永続 BP 修正、戦闘中のみ、次の自分ターンまで、などの duration 候補。
- level / OC / 破壊 / 手札戻りで modifier を引き継ぐか。

## 4. 推奨する v6 実装順

1. 既存 supported カードの仕様テストを増やす。
2. v6 用 decklist を作り、match CLI と replay viewer で確認しやすくする。
3. optional unit ability の候補カードを Excel から 1 枚選び、mapping と engine テストを追加する。
4. 複数 target または target 条件を持つカードを 1 枚追加する。
5. discard pile / deck search / reveal のどれか 1 系統を選び、公開情報 schema を先に決める。

## 5. 追加で確認したい仕様

- optional unit ability の候補カードをどれにするか。
- deck search / reveal の private / public view の境界。
- discard pile から移動したカードの instance id の扱い。
- BP modifier の duration 種類と解除タイミング。
