"""現場写真 PC側 常駐サーバー（FastAPI / HTTPS）。

役割（PHASE_1 §7, PHASE_2 §5）:
  - GET  /api/ping    : 死活・バージョン・空き容量
  - POST /api/photos  : 写真+メタ受信 → 地点解決 → フォルダ自動生成 → 格納
  - GET/POST /api/config : 保存ルート等の取得・更新
起動: python server.py  （初回に config.json と自己署名証明書を自動生成）
"""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import load_config, update_config
from discovery import Discovery
from gen_cert import ensure_cert
from geocoder import NO_GPS_FOLDER, Geocoder
from utils import build_filename, sanitize_name, unique_path

VERSION = "1.0.0"
INDEX_FILE = ".genba_index.json"  # photo_id → 保存相対パス（重複排除）


class Storage:
    """ファイル格納と重複排除インデックスを管理する。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.root = Path(cfg["root_path"])
        self.root.mkdir(parents=True, exist_ok=True)
        self.geocoder = Geocoder(cfg, self.root)
        self.index_path = self.root / INDEX_FILE
        self._lock = threading.Lock()
        self.index: dict[str, str] = self._load_index()

    def _load_index(self) -> dict:
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_index(self) -> None:
        try:
            self.index_path.write_text(
                json.dumps(self.index, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"[storage] インデックス保存失敗: {e}")

    def store(self, data: bytes, meta: dict) -> dict:
        photo_id = meta.get("photo_id") or ""
        gps = meta.get("gps") or {}
        project = meta.get("project_name")
        project_folder = sanitize_name(project, fallback="未案件")

        # --- 重複排除（冪等性）: 同一photo_idが格納済みならスキップ ---
        with self._lock:
            prev = self.index.get(photo_id)
        if prev and (self.root / prev).exists():
            return {"status": "ok", "photo_id": photo_id, "saved_path": prev,
                    "project": project_folder, "place": Path(prev).parts[0],
                    "dedup": True}

        # --- 地点（第1階層）の解決 ---
        if gps.get("available") and gps.get("lat") is not None and gps.get("lng") is not None:
            place = self.geocoder.resolve_place(float(gps["lat"]), float(gps["lng"]))
            place_folder = sanitize_name(place, fallback="_地点未解決_")
        else:
            place_folder = NO_GPS_FOLDER

        dest_dir = self.root / place_folder / project_folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = build_filename(meta.get("captured_at"), photo_id, meta.get("mime", "image/jpeg"))
        dest = unique_path(dest_dir / filename)
        dest.write_bytes(data)

        rel = str(dest.relative_to(self.root))
        with self._lock:
            self.index[photo_id] = rel
            self._save_index()

        return {"status": "ok", "photo_id": photo_id, "saved_path": rel,
                "project": project_folder, "place": place_folder, "dedup": False}

    def free_space_mb(self) -> int:
        try:
            return int(shutil.disk_usage(self.root).free / (1024 * 1024))
        except Exception:
            return -1


# ------------------------------------------------------------------ アプリ状態
class State:
    def __init__(self):
        self.cfg = load_config()
        self.storage = Storage(self.cfg)
        self.discovery = Discovery(self.cfg)

    def rebuild_storage(self):
        self.storage = Storage(self.cfg)


STATE = State()
app = FastAPI(title="現場写真 PCサーバー", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=STATE.cfg.get("cors_origins", ["*"]),
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_auth(authorization: str | None = Header(default=None)):
    token = STATE.cfg.get("token") or ""
    if token:
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid token")


@app.get("/api/ping")
def ping(_=Depends(require_auth)):
    return {
        "status": "ok",
        "version": VERSION,
        "root_path": str(STATE.storage.root),
        "free_space_mb": STATE.storage.free_space_mb(),
    }


@app.post("/api/photos")
async def upload(
    file: UploadFile = File(...),
    meta: str = Form(...),
    _=Depends(require_auth),
):
    try:
        m = json.loads(meta)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid meta json")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        result = STATE.storage.store(data, m)
        return result
    except Exception as e:
        print(f"[photos] 格納失敗: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "reason": str(e)})


@app.get("/api/config")
def get_config(_=Depends(require_auth)):
    c = STATE.cfg
    return {"root_path": c["root_path"], "advertised_hostname": c["advertised_hostname"],
            "geocode_zoom": c["geocode_zoom"], "token_set": bool(c.get("token"))}


@app.post("/api/config")
async def set_config(patch: dict, _=Depends(require_auth)):
    old_root = STATE.cfg["root_path"]
    STATE.cfg = update_config(patch)
    if STATE.cfg["root_path"] != old_root:
        STATE.rebuild_storage()
    return {"status": "ok", "config": get_config()}


@app.on_event("startup")
def on_startup():
    STATE.discovery.start()


@app.on_event("shutdown")
def on_shutdown():
    STATE.discovery.stop()


def main():
    crt, key = ensure_cert()
    cfg = STATE.cfg
    print("=" * 56)
    print(" 現場写真 PCサーバー 起動")
    print(f"  保存先   : {STATE.storage.root}")
    print(f"  URL      : https://{cfg['advertised_hostname']}:{cfg['port']}")
    print(f"  認証     : {'トークンあり' if cfg.get('token') else 'なし'}")
    print("  （初回はスマホに certs/server.crt を信頼インストールしてください）")
    print("=" * 56)
    uvicorn.run(app, host=cfg["host"], port=int(cfg["port"]),
                ssl_certfile=str(crt), ssl_keyfile=str(key))


if __name__ == "__main__":
    main()
