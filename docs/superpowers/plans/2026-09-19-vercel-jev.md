# Vercel Jev 接続の実装計画

**Goal:** 保存済みの AI_GATEWAY_API_KEY を使い、Mac上のマリオをJevで操作する。
**Architecture:** 既存Pythonゲームから常駐Node子プロセスへJSON Linesで状態・質問を渡す。公式AI SDK 7のevaluateを呼び、既存Policyが使うTypeSafe応答形式に変換する。鍵は環境/.envから読み込み、通信ログに出さない。
**Tech Stack:** Python 3.13、既存typesafe-sdk、Node 23、ai 7。

- [x] Python起動修復: editable登録のpthがmacOS hidden属性のためPython 3.13に無視されている。nohiddenに戻し、importと既存pytestを実行。
- [x] gateway/adapter.test.mjs: choice/score/noulのリクエスト変換、応答変換、未対応型拒否を先にテスト。node --testで失敗確認後にadapter.mjsを実装。
- [x] gateway/worker.mjs: stdinの1行につきevaluateを1回。リトライ0・20秒タイムアウト。エラーは名前とHTTP状態のみ出力。
- [x] src/typesafe_mario/gateway.py: Node子プロセスを常駐、同期要求応答、タイムアウト時終了。typesafe policyのclient差替えで既存プロンプトを再利用。
- [x] CLI --policy vercel、.env読み込み、接続試験、Mac用起動.commandを追加。上限100判断から開始。
- [ ] テスト・lint、鍵の非追跡、実API1回、画面なし3判断、GUI上限100判断を確認。アカウント側エラーなら連続再試行せず正確に報告。

## 実行結果
Python 13件・Node 3件のテスト、lint、固定ルール3判断が成功。起動時のPYTHONPATH指定でhidden属性に依存しない起動に修正。実APIとブリッジの疎通はVercelのカード未登録HTTP 403を確認。ゲームの実Jev操作はカード登録待ち。課金・カード登録・自動チャージ設定は変更していない。
