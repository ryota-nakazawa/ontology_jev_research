# Mario × Jev：オントロジーと Skill による操作実験

マリオの状態・地形・敵・アイテムを構造化し、Jev が実行可能な Skill を選び、フレーム単位の制御で操作する検証です。テトリス・スイカゲームは含みません。

## 詳細ドキュメント

[マリオで実装したオントロジーと設計上の工夫](docs/mario-ontology-and-design.md)：知識の管理、Skill の意味、Jev の役割、非同期制御、フラワー取得、ログと比較方法をコードと対応づけて解説しています。

[全Skillと判断条件一覧](docs/mario-skill-catalog.md)：19種類の候補Skill、2種類の内部Skill、ローカル安全制御の目的・適用条件・成功／中断条件を表で確認できます。

## 構成

`RAM・テレメトリ → 状態と関係の計算 → 実行可能な Skill → Jev の選択 → ローカル制御 → 結果の記録`

- `src/typesafe_mario/knowledge.py`：対象・関係・能力の定義
- `stage_knowledge.py`：ステージとアイテム配置の知識
- `continuous_skills.py`：Skill の条件と制御
- `skill_policy.py`：Jev に渡す判断条件
- `continuous_runner.py`：非同期判断とフレーム単位の実行
- `flower_fire.py`：フラワー取得とファイア操作

詳しくは [実行構成と改善履歴](docs/continuous-skill-runtime.md) と [ステージ知識](docs/mario-gimmick-knowledge.md) を参照してください。文書中の過去ログはローカル検証時の参照であり、この共有版には含みません。

## 起動（macOS / Linux）

Python 3.13 以降と Node.js 22 以降を用意してください。

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -e ".[mario,dev]"
npm ci
cp .env.example .env
```

`.env` に自分の TypeSafe API キーを設定します。API 利用にはサービス側のクレジットが必要になる場合があります。

```sh
PYTHONPATH=src .venv/bin/python -m typesafe_mario.cli play --policy direct --continuous-skills --display dashboard --until-game-over --interactive-session
```

macOS では `Start Jev Mario.command` でも起動できます。R / Restart で再試行、Q / Esc で終了します。ログは `artifacts/` に保存されます。
ゲーム ROM・キー・個人の実行ログは含みません。ゲーム実行には元プロジェクトに沿ったローカル環境が必要です。

## テスト

```sh
.venv/bin/python -m pytest -q
npm test
```

## 検証上の位置付け

ここでいうオントロジーは、対象・関係だけでなく、行動の目的・適用条件・成功条件を明示した運用上の知識を含みます。RDF / OWL 実装ではありません。
クリアの安定化は観測されていますが、認識・制御の改善も含むため、オントロジー単独の因果効果やクリア率 100% を証明したものではありません。

## 元プロジェクト

[fhshaik/typesafe-mario](https://github.com/fhshaik/typesafe-mario) のコミット `ca22449ed187118d19326d1f54b01b6636578aa4` を基にした拡張です。元プロジェクトの著者は fhshaik です。この共有用コピーでは独自の再利用ライセンスを付与していません。
