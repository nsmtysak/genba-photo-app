# PHASE 2 SUMMARY — PWA フロントエンド開発

> 担当: Frontend Developer Agent
> ステータス: 実装完了・動作検証済み（実通信はフェーズ4で統合）
> 最終更新: 2026-06-21
> 前提: `PHASE_1_SUMMARY.md`（§4.3 転送フロー / §5 メタJSON / §7 API仕様 に準拠）

---

## 1. 実装サマリー

現場で「案件名入力 → 撮影 → GPS自動取得 → 端末内キューに保存（完全オフライン）」、帰社後に「転送開始ボタン1回でPCへ一括送信」という体験を、Vanilla HTML/CSS/JS のみで実装した。外部ライブラリ・ビルドツールは不使用。

### 主な機能
- **案件名管理**: 入力＋履歴サジェスト（`<datalist>`、最大30件）、現在の案件をヘッダ下に常時表示。「未案件にする」で案件なし撮影に切替。
- **撮影**: ネイティブカメラ起動（`<input type="file" accept="image/*" capture="environment">`）。iOS Safari / Android Chrome 双方で確実に動作する方式を採用（getUserMediaのライブプレビューは端末差が大きいため不採用）。
- **GPS取得**: 撮影直後に `geolocation.getCurrentPosition`（高精度・15秒タイムアウト）。取得結果（精度／拒否／タイムアウト／非対応）を画面表示。失敗してもデータは破棄せずGPSなしで保存。
- **メタデータ付与**: 撮影ごとに §5 スキーマ準拠のJSONを生成（`photo_id`(UUID)、`project_name`、`captured_at`(オフセット付きISO8601)、`source:"app"`、`gps`、`device`、`mime` 等）。
- **オフライン保存（送信キュー）**: 画像Blob＋メタを **IndexedDB**（`queue` ストア、keyPath=`photo_id`）に保存。枚数・合計容量・サムネイル一覧・ステータス（queued/sending/done/failed）・GPSなし警告を表示。
- **転送（1アクション）**: 「転送開始」で §4.3 のフロー実行 → `/api/ping` 接続確認 → 未送信分を時系列で順次 `POST /api/photos`（multipart: `file`+`meta`）→ 成功はステータス`done`、失敗は`failed`でキュー保持 → 進捗バー＋ログ＋トーストで結果表示。冪等性は `photo_id` に依拠（再送安全）。
- **PC接続設定**: PCのHTTPS URL・接続トークン（任意、`Authorization: Bearer`）を localStorage 保存。接続テストボタン。ヘッダに接続状態インジケータ。
- **PWA化**: `manifest.json`（standalone・テーマ色・SVGアイコン）、`service-worker.js`（アプリシェルをcache-first、`/api/`は常にネットワーク、ナビゲーションはオフライン時フォールバック）。

---

## 2. 成果物リスト

| ファイル | 役割 |
|---|---|
| `pwa-app.html` | PWA本体（UI＋全ロジックを単一ファイルに内包） |
| `manifest.json` | インストール用マニフェスト |
| `service-worker.js` | オフラインキャッシュ（アプリシェル） |
| `icon.svg` | アプリアイコン（512基準・maskable対応のSVG） |
| `.claude/launch.json` | ローカル確認用の静的サーバー設定（`python -m http.server 8765`） |
| `PHASE_2_SUMMARY.md` | 本書 |

---

## 3. 動作検証（フェーズ2範囲）

ローカル静的サーバー（`http://localhost:8765/pwa-app.html`）＋プレビューで確認：
- ✅ 読み込み時 **コンソールエラーなし**。
- ✅ UI描画（mobile 375px）正常。案件カード・撮影ボタン・キュー・転送・接続設定が表示。
- ✅ `localISO()` がオフセット付き（`2026-06-21T09:32:11+09:00`）を生成（§5準拠）。
- ✅ 案件設定 → `getActiveProject()` / 履歴反映。
- ✅ IndexedDB へ追加 → 枚数カウント・サムネイル描画 → 削除でリセット、を一連で確認。
- ✅ 生成メタJSONが §5 スキーマと一致。GPSあり/なし両方を確認。

> 実際の `POST /api/photos` 成功までの確認は **PC側サーバー（フェーズ3）と統合するフェーズ4** で実施。フェーズ2では送信ロジック・エラーハンドリング・キュー保持の挙動までを実装・確認済み。

---

## 4. 設計上の判断・留意点

- **撮影方式**: `input capture` 採用（信頼性優先）。連続撮影できるよう、選択後に input をリセット。
- **GPSの正本**: EXIFではなく別送JSONを正本とする方針（§5）に従い、メタJSONにGPSを格納。EXIF書き込みは行わない。
- **アイコン**: SVG単一ファイルで提供（低依存）。iOSのapple-touch-iconはPNG推奨のため、ホーム画面アイコンの見栄えを最適化したい場合はフェーズ6で192/512のPNGを追加するとよい（任意）。
- **secure context**: カメラ/GPS/Service Worker はHTTPS必須。GitHub Pages配信（§PHASE_1 §4）で満たす。`localhost` でのローカル確認も secure context 扱いで動作。
- **CORS / 自己署名証明書**: 実通信成立にはPC側のCORS許可＋スマホでの証明書信頼が必要（フェーズ3/4で対応）。
- **パス**: 全アセットを相対パス参照。GitHub Pages のサブディレクトリ配信でも動作。

---

## 5. フェーズ3（PC側スクリプト）への引き継ぎ

Backend Developer Agent が実装すべき、PWAと整合するサーバー仕様：

- **エンドポイント**（PHASE_1 §7）:
  - `GET /api/ping` → `{status, version, root_path, free_space_mb}` を返す。CORS・トークン検証。
  - `POST /api/photos` → `multipart/form-data` の `file`（画像）＋ `meta`（JSON文字列）を受信。レスポンスに `{status, photo_id, saved_path, company|place, project, dedup}` を含めると、PWAの転送ログに地点名/重複が表示される（任意フィールド）。
- **CORS**: PWA配信オリジン（GitHub Pages のURL、ローカル確認用に `http://localhost:8765` も）からの `GET/POST` と `Authorization` ヘッダを許可。プリフライト(`OPTIONS`)対応。
- **認証**: `Authorization: Bearer <token>` を検証（トークン未設定運用も許容）。
- **メタ取り扱い**: `meta.gps.available=false` は `_未分類_GPSなし` へ。`meta.project_name` が null/空は `未案件` フォルダへ。`photo_id` で冪等化（重複は `dedup:true` でスキップ成功扱い）。
- **逆ジオコーディング**: **Nominatim/OSM（無料）に確定**（PHASE_1 §9-3a）。レート制限遵守・User-Agent明示、`location_cache.json` で座標→フォルダ名を再利用。差し替え可能なI/Fに。
- **HTTPS**: 自己署名証明書でHTTPS待受（PWAがHTTPSのため mixed-content 回避に必須）。
- **ファイル名**: PWAは `<photo_id>.<ext>` で送るが、保存名は PHASE_1 §6.2（`YYYYMMDD_HHMMSS_<photo_id先頭8桁>.<ext>`）でPC側が決定。

### フェーズ4（統合）で確認する項目
- 実機（iPhone/Android）→ GitHub Pages から起動 → 同一Wi-Fiで `genba-pc.local` 解決 → ping成功 → 撮影分の転送成功 → フォルダ自動生成の一気通貫。
- 自己署名証明書の信頼インストール手順の実機検証。

---

## 6. 未解決・留意（次セッションへ）
- 実通信（ping/photos）の成功確認はフェーズ3完了後（フェーズ4）。
- 自己署名証明書の信頼インストール許容（ユーザー確認・PHASE_1 §9-4）、保存ルートフォルダ既定（§9-5）は未確定。
- mDNSによる `genba-pc.local` 解決の実機到達性はフェーズ4で検証。
