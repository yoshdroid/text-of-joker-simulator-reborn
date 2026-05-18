# scenario CLI v7

個別機能・個別カード効果を GUI で目視確認するため、固定テストシナリオから replay を生成する CLI。

## 生成

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --scenario all --verify
```

既定では `test_output/scenarios/` に replay を出力する。

## テストシナリオ一覧

| scenario | 確認対象 | 期待する目視ポイント | v7 |
| --- | --- | --- | --- |
| `bishamon_evolve_destroy_all` | 毘沙門 | 左からスカルウォーカー、ライマル、ミイラくんで開始し、真ん中の `1-0-021` ライマルを元に `1-0-026` 毘沙門を進化ドライブする。ミイラくんで P2 手札1枚をランダム破壊し、スカルウォーカーで進化元ライマルを手札へ戻し、カラスマドウで P2 が intercept をサーチドローする。最後に毘沙門でアタックし、P2 LIFE が減る。 | ✓ |
| `bloodhound_level3_damage` | ブラッドハウンド | `1-0-001` ブラッドハウンドを手札オーバーライドで LV3 にしてドライブし、OC の対象選択、4000ダメージ、相手ユニット破壊を確認する。 | ✓ |
| `display_stand_trigger_draw` | ディスプレイスタンド | `1-0-062` ディスプレイスタンドが owner unit enter 後に強制発動し、デッキトップを1枚引く。 | ✓ |
| `happaloid_cip_draw` | ハッパロイド | `1-0-040` ハッパロイドをドライブし、CIP でデッキトップのカードが手札に移る。 | ✓ |
| `hand_limit_draw` | 手札上限 | 自分の手札3枚、相手の手札2枚から開始し、ターン冒頭ドローで 6->7 は増え、7->7 は `draw_skipped` になって手札上限7を超えない。 | ✓ |
| `kaim_cip_trigger_search` | カイム | `1-0-020` カイムをドライブし、デッキ内の trigger だけを探して手札に加え、unit / intercept がデッキに残る。 | ✓ |
| `new_armor_trigger` | 新品の鎧 | `1-0-061` 新品の鎧が unit enter 後に強制発動し、deck から intercept を探して手札に加える。 | ✓ |
| `rairyu_evolve_damage` | 雷龍 | `1-0-024` 雷龍を黄ユニットに進化ドライブし、進化元が捨札へ移動し、疲弊した相手ユニットへ7000ダメージを与えて破壊する。 | ✓ |
| `lina_discard_choice` | 見習い魔導士リーナ | デッキ5枚の先頭を `1-0-033` ヴァイパーにして開始し、CP7で1枚ドローする。`1-0-031` 見習い魔導士リーナを手札オーバーライドで LV3 にした後、ヴァイパーで捨札のリーナを回収し、LV3リーナのOCでもリーナを回収する。最後に手札のリーナ2枚をオーバーライドしてLV2にする。 | ✓ |
| `viper_discard_unit_recover` | バイパー | `1-0-033` バイパーをドライブし、捨札の unit だけが候補になって同じカードインスタンスが手札へ戻る。 | ✓ |

## GUI で開く

単体シナリオは `--open-gui` で replay 生成後にそのまま開ける。

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --images carddata/images --scenario new_armor_trigger --verify --open-gui
```

画面サイズに依存しにくい状態で確認を始めたい場合は `--fullscreen` を追加する。

```powershell
python -m tojs_reborn.io.scenario_cli --cards carddata/generated/cards.normalized.json --images carddata/images --scenario lina_discard_choice --verify --open-gui --fullscreen
```

既に生成した replay を開く場合:

```powershell
python -m tojs_reborn.io.replay_gui --cards carddata/generated/cards.normalized.json --images carddata/images --replay test_output/scenarios/hand_limit_draw.json
```

## シナリオの初期デッキ規約

- テストシナリオでも、初期配置される手札・場・捨札・トリガーゾーン・デッキ上のカードは、すべて `initial_deck_card_nos` に含まれていたカードとして扱う。
- `initial_deck_card_nos` 上の同名カードは3枚までとする。
- 純粋なドローでデッキが空の場合は、`initial_deck_card_nos` をシャッフルし、新しいカードインスタンスとしてデッキを再生成してからドローする。このとき既存の手札・場・捨札は戻さない。
- カテゴリサーチはデッキリフレッシュのきっかけにならない。デッキが空ならサーチは不発になり、`cards_drawn.count` は0になる。
