# PHASE 3 SUMMARY — PC側 常駐サーバー開発

> 担当: Backend Developer Agent
> ステータス: 実装完了・ローカル検証済み（実機/PWA実通信はフェーズ4）
> 最終更新: 2026-06-21
> 前提: `PHASE_1_SUMMARY.md`（§3 地点解決 / §6 命名 / §7 API）、`PHASE_2_SUMMARY.md`（§5 PWA整合仕様）

---

## 1. 実装サマリー

Python / FastAPI による Windows 常駐サーバーを実装。PWA から送られた写真＋メタを受信し、**逆ジオコーディング（Nominatim/OSM・無料）で地点名を解決 → フォルダ自動生成 → 格納**する。HTTPS（自己署名）＋ CORS ＋ トークン認証（任意）＋ mDNS 広告に対応。

### データフロー（受信時）
1. `POST /api/photos` で `file`＋`meta`(JSON) を受信。
2. `photo_id` で**重複排除**（格納済みなら `dedup:true` でスキップ）。
3. 第1階層フォルダを決定：
   - GPSあり → Nominatim で地点名解決（`location_cache.json` で再利用、レート制限1.1秒）。
   - GPSなし → `_未分類_GPSなし`。
4. 第2階層 = 案件名（無ければ `未案件`）。
5. ファイル名 `YYYYMMDD_HHMMSS_<photo_id先頭8桁>.<ext>`（衝突時は連番）で書き込み。
6. `{status, photo_id, saved_path, place, project, dedup}` を返却（PWAの転送ログに表示）。

---

## 2. 成果物リスト（`pc-server/`）

| ファイル | 役割 |
|---|---|
| `server.py` | FastAPI本体。エンドポイント、`Storage`（格納＋重複排除インデックス）、起動処理 |
| `geocoder.py` | Nominatim逆ジオコーディング＋`location_cache.json`。地点名組み立て。将来Google差替え可能なI/F |
| `config.py` | `config.json` 読み書き。既定保存先＝マイドキュメント\現場写真（OneDrive配下も考慮） |
| `utils.py` | フォルダ/ファイル名の安全化、保存名生成、LAN IP検出、座標キー、連番回避 |
| `gen_cert.py` | 自己署名証明書生成（SANにホスト名・localhost・LAN IP） |
| `discovery.py` | mDNS(Zeroconf)でPCを広告（`genba-photo.local`） |
| `requirements.txt` | 依存（fastapi, uvicorn, python-multipart, requests, cryptography, zeroconf） |
| `start.bat` | Windows起動スクリプト（初回venv作成＋依存導入） |
| `test_local.py` | ネットワーク不要のローカル検証スイート |

実行時生成物（gitignore対象）: `config.json`, `certs/`, `location_cache.json`, `.genba_index.json`, `.venv/`

---

## 3. API仕様（実装済み）

| Method | Path | 認証 | 概要 |
|---|---|---|---|
| GET | `/api/ping` | 任意 | `{status, version, root_path, free_space_mb}` |
| POST | `/api/photos` | 任意 | multipart `file`+`meta` 受信・格納。`{status, photo_id, saved_path, place, project, dedup}` |
| GET | `/api/config` | 任意 | `{root_path, advertised_hostname, geocode_zoom, token_set}` |
| POST | `/api/config` | 任意 | `root_path`/`token`/`geocode_zoom`/`advertised_hostname` を更新 |

- 認証: `config.json` の `token` が空なら認証なし。設定時は `Authorization: Bearer <token>` を検証。
- CORS: 既定 `*`（`config.json` の `cors_origins` で GitHub Pages のURLに絞り可）。

---

## 4. ローカル検証結果（`test_local.py`・全PASS / exit 0）

ネットワーク非依存で以下を確認（Nominatimはキャッシュ事前投入で回避）:
- ✅ `utils`: 禁止文字置換・予約名回避・保存名生成（`20260621_093211_8c9523c7.jpg`）・座標キー（`35.6895,139.6917`）。
- ✅ `_build_place_name`: `新宿区西新宿` / POI併記 `新宿区西新宿_○○建設` / display_nameフォールバック。
- ✅ 格納＆重複排除: `地点/案件/ファイル` 階層生成、同一`photo_id`再送で `dedup:true`、GPSなし→`_未分類_GPSなし/未案件`。
- ✅ 自己署名証明書生成（SAN: `genba-photo.local`, `localhost`, 検出LAN IP）。
- ✅ エンドポイント（FastAPI TestClient）: `ping` / `photos`(multipart, 実ファイル生成確認) / `config`。
- ✅ トークン認証: 未提示で401、正トークンで200。

依存インストール（`pip install -r requirements.txt`）も成功確認済み（Python 3.13）。

---

## 5. 運用メモ（フェーズ6で正式マニュアル化）

- 起動: `pc-server/start.bat` をダブルクリック（初回は自動でvenv作成＋依存導入＋証明書生成＋`config.json`生成）。
- 保存先変更: `config.json` の `root_path` を編集 or `POST /api/config`。
- 地点名の修正: `location_cache.json` の値（フォルダ名）を編集すると、以降その地点は新名称で自動格納（会社名へ書き換える運用）。
- Nominatim利用規約: `config.json` の `user_agent` に**連絡先メールを設定**すること（既定はプレースホルダ）。商用・大量利用時は自前Nominatim/有料サービスへ差し替え検討。
- 常駐化（将来）: タスクスケジューラのログオン時実行、または NSSM でサービス化。

---

## 6. フェーズ4（統合）への引き継ぎ

- **接続確立**: PWAの「PC接続設定」に `https://genba-photo.local:8443`（または `https://<PCのIP>:8443`）を設定。
- **必須セットアップ**（実機）: `pc-server/certs/server.crt` をスマホに**信頼インストール**（iOS=構成プロファイル＋証明書信頼設定、Android=CA証明書）。これが無いとHTTPS接続が拒否される。
- **CORS確認**: PWAを GitHub Pages から開く場合、`config.json` の `cors_origins` を `*` のままにするか、当該オリジンを追加。
- **mDNS到達性**: `genba-photo.local` が実機から解決できるか確認。不可なら IP直打ちで代替（PWAは手入力対応済み）。
- **エンドツーエンド試験項目**: 撮影→キュー→転送ボタン→`place/project`フォルダ生成→重複再送スキップ→GPSなし振り分け→中断後の再開。
- **Windowsファイアウォール**: 初回起動時にポート8443の受信許可が必要な場合あり。

### 未解決・留意
- 自己署名証明書の信頼インストール許容（PHASE_1 §9-4）は実機運用の前提。フェーズ6で手順書化。
- Nominatimの精度（現場のPOI/丁目解決）はフェーズ5(QA)で実測評価。必要に応じ `geocode_zoom` 調整 or 会社名解決(Places)をv2で追加。
