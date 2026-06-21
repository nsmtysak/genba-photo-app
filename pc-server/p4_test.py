"""フェーズ4 統合テスト（PC単体・実HTTPS通信）。

実ソケット越しにHTTPS(TLS)でサーバーへ ping / photos を送り、
フォルダ自動生成・重複排除・GPSなし振り分けを検証する。
さらに実機Nominatimでの逆ジオコーディングを best-effort で確認する。

テスト用に config.json の保存先を pc-server/_p4_inbox へ向ける。
（呼び出し側で実行後に restore_config.py で既定へ戻す）
"""
import json
import shutil
import threading
import time
from pathlib import Path

import config as cfgmod

# ---- テスト用の保存先と設定を用意（importより前に） ----
INBOX = Path(cfgmod.BASE_DIR) / "_p4_inbox"
if INBOX.exists():
    shutil.rmtree(INBOX)
INBOX.mkdir(parents=True)

_c = cfgmod.default_config()
_c["root_path"] = str(INBOX)
_c["token"] = ""
_c["cors_origins"] = ["*"]
cfgmod.save_config(_c)

# Nominatim呼び出しを避けるため座標→地点名を事前投入
(INBOX / "location_cache.json").write_text(
    json.dumps({"35.6895,139.6917": "テスト地点新宿"}, ensure_ascii=False), encoding="utf-8"
)

import server  # noqa: E402  (config.json確定後にimport)
from gen_cert import ensure_cert  # noqa: E402

import uvicorn  # noqa: E402
import requests  # noqa: E402
import urllib3  # noqa: E402

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://127.0.0.1:8443"


def start_server():
    crt, key = ensure_cert()
    conf = uvicorn.Config(server.app, host="127.0.0.1", port=8443,
                          ssl_certfile=str(crt), ssl_keyfile=str(key), log_level="warning")
    srv = uvicorn.Server(conf)
    srv.install_signal_handlers = lambda: None  # 非メインスレッドで動かすため無効化
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(150):
        if srv.started:
            break
        if not th.is_alive():
            raise RuntimeError("サーバースレッドが異常終了しました")
        time.sleep(0.1)
    if not srv.started:
        raise RuntimeError("サーバーが起動しませんでした")
    return srv


def main():
    srv = start_server()
    print("[p4] HTTPSサーバー起動:", BASE)
    s = requests.Session()
    s.verify = False  # 自己署名のためテスト時のみ検証無効

    # 1) ping over TLS
    r = s.get(f"{BASE}/api/ping", timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "ok"
    print(f"  [1] ping OK  version={j['version']} free={j['free_space_mb']}MB root={j['root_path']}")

    # 2) photos: GPSあり → 地点/案件 へ格納
    meta = {"schema_version": 1, "photo_id": "p4-001", "project_name": "統合テスト案件",
            "captured_at": "2026-06-21T09:32:11+09:00", "source": "app",
            "gps": {"lat": 35.6895, "lng": 139.6917, "accuracy_m": 8,
                    "captured_at": "2026-06-21T09:32:10+09:00", "available": True},
            "device": {"platform": "iOS", "ua": "p4"}, "original_filename": "a.jpg", "mime": "image/jpeg"}
    r = s.post(f"{BASE}/api/photos",
               files={"file": ("p4-001.jpg", b"FAKEJPEGDATA-1", "image/jpeg")},
               data={"meta": json.dumps(meta)}, timeout=15)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["place"] == "テスト地点新宿" and b["project"] == "統合テスト案件" and b["dedup"] is False, b
    saved = INBOX / b["saved_path"]
    assert saved.exists() and saved.read_bytes() == b"FAKEJPEGDATA-1"
    print(f"  [2] photos(GPSあり) OK  saved={b['saved_path']}")

    # 3) 同一photo_id 再送 → dedup
    r = s.post(f"{BASE}/api/photos",
               files={"file": ("p4-001.jpg", b"FAKEJPEGDATA-1", "image/jpeg")},
               data={"meta": json.dumps(meta)}, timeout=15)
    assert r.json()["dedup"] is True, r.json()
    print("  [3] 重複再送 dedup OK")

    # 4) GPSなし → _未分類_GPSなし / 未案件
    meta2 = dict(meta, photo_id="p4-002", project_name=None,
                 gps={"lat": None, "lng": None, "accuracy_m": None, "captured_at": None, "available": False})
    r = s.post(f"{BASE}/api/photos",
               files={"file": ("p4-002.jpg", b"FAKE-2", "image/jpeg")},
               data={"meta": json.dumps(meta2)}, timeout=15)
    b2 = r.json()
    assert b2["place"] == "_未分類_GPSなし" and b2["project"] == "未案件", b2
    assert (INBOX / "_未分類_GPSなし" / "未案件").exists()
    print(f"  [4] photos(GPSなし) OK  saved={b2['saved_path']}")

    # 5) CORS プリフライト相当（Originヘッダ付きGET）
    r = s.get(f"{BASE}/api/ping", headers={"Origin": "https://example.github.io"}, timeout=10)
    aco = r.headers.get("access-control-allow-origin")
    assert aco in ("*", "https://example.github.io"), f"CORSヘッダ無し: {dict(r.headers)}"
    print(f"  [5] CORS OK  access-control-allow-origin={aco}")

    # 6) 実機Nominatim（best-effort）
    print("  [6] Nominatim実呼び出し（東京駅付近）…", end=" ")
    try:
        name = server.STATE.storage.geocoder._reverse_nominatim(35.681236, 139.767125)
        print(f"OK -> {name}" if name else "応答あり(名前空)")
    except Exception as e:
        print(f"スキップ（ネットワーク不可）: {e}")

    srv.should_exit = True
    time.sleep(0.5)
    print("\n[p4] HTTPS統合テスト ALL PASSED")


if __name__ == "__main__":
    main()
