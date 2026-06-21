"""設定の読み書き。

config.json は初回起動時に既定値で生成される。保存ルートフォルダの既定は
「マイドキュメント\\現場写真」。ユーザーは config.json を編集するか
PWA の設定API (/api/config) で変更できる。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# このファイル（pc-server/）のあるディレクトリ
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CERT_DIR = BASE_DIR / "certs"
CERT_FILE = CERT_DIR / "server.crt"
KEY_FILE = CERT_DIR / "server.key"


def default_documents_dir() -> Path:
    """Windowsのマイドキュメント。OneDrive配下も考慮し、無ければ ~/Documents。"""
    home = Path(os.path.expanduser("~"))
    candidates = [home / "Documents", home / "OneDrive" / "Documents", home / "ドキュメント"]
    for c in candidates:
        if c.exists():
            return c
    return home / "Documents"


def default_config() -> dict:
    root = default_documents_dir() / "現場写真"
    return {
        "root_path": str(root),
        "host": "0.0.0.0",
        "port": 8443,
        "advertised_hostname": "genba-photo.local",
        # 認証トークン（空文字なら認証なし）
        "token": "",
        # 逆ジオコーディング（Nominatim/OSM・無料）
        "geocoder": "nominatim",
        "nominatim_url": "https://nominatim.openstreetmap.org/reverse",
        # Nominatim利用規約: 連絡先を含むUser-Agentを必ず設定すること
        "user_agent": "GenbaPhotoApp/1.0 (please-set-your-contact-email)",
        "geocode_zoom": 16,          # 16=丁目/街区相当
        "geocode_lang": "ja",
        "min_request_interval_sec": 1.1,  # Nominatimは最大1req/秒
        # 座標量子化の小数桁（4桁≒約11m）。同一現場をまとめAPI呼び出しを節約
        "coord_precision": 4,
        # CORS許可オリジン（"*" は全許可。GitHub PagesのURLに絞ってもよい）
        "cors_origins": ["*"],
    }


def load_config() -> dict:
    cfg = default_config()
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in user.items() if v is not None})
        except Exception as e:  # 壊れていても既定で起動
            print(f"[config] 読み込み失敗、既定値で起動します: {e}")
    else:
        save_config(cfg)
        print(f"[config] {CONFIG_PATH} を新規作成しました。")
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def update_config(patch: dict) -> dict:
    cfg = load_config()
    for k in ("root_path", "token", "geocode_zoom", "advertised_hostname"):
        if k in patch and patch[k] is not None:
            cfg[k] = patch[k]
    save_config(cfg)
    return cfg
