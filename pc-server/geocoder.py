"""逆ジオコーディング（Nominatim/OSM・無料）と地点名キャッシュ。

設計（PHASE_1 §3）:
  - 座標 → 住所(地名) をNominatimで取得しフォルダ名にする（MVPは住所ベース）。
  - location_cache.json（保存ルート直下）に「座標キー → 確定フォルダ名」を保持。
    一度解決した地点は再利用し、API呼び出しと表記ゆれを抑える。
    ユーザーが location_cache.json の名前を会社名へ書き換えれば、
    以降その地点は会社名フォルダへ自動格納される。
  - Nominatim利用規約遵守: 最大1req/秒、連絡先入りUser-Agent。
  - 将来 Google Geocoding/Places へ差し替え可能なI/F（resolve_place）。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import requests

from utils import coord_key

NO_GPS_FOLDER = "_未分類_GPSなし"
UNRESOLVED_PREFIX = "_地点未解決_"


class Geocoder:
    def __init__(self, cfg: dict, root: Path):
        self.cfg = cfg
        self.cache_path = root / "location_cache.json"
        self.cache: dict[str, str] = self._load_cache()
        self._last_call = 0.0
        self._lock = threading.Lock()

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"[geocoder] キャッシュ保存失敗: {e}")

    def resolve_place(self, lat: float, lng: float) -> str:
        """座標から地点フォルダ名を返す。失敗時は _地点未解決_<座標キー>。"""
        key = coord_key(lat, lng, self.cfg.get("coord_precision", 4))
        with self._lock:
            if key in self.cache and self.cache[key]:
                return self.cache[key]
        name = self._reverse_nominatim(lat, lng)
        if not name:
            return f"{UNRESOLVED_PREFIX}{key}"
        with self._lock:
            self.cache[key] = name
            self._save_cache()
        return name

    def _throttle(self) -> None:
        interval = float(self.cfg.get("min_request_interval_sec", 1.1))
        now = time.time()
        wait = self._last_call + interval - now
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _reverse_nominatim(self, lat: float, lng: float) -> str | None:
        self._throttle()
        try:
            resp = requests.get(
                self.cfg.get("nominatim_url", "https://nominatim.openstreetmap.org/reverse"),
                params={
                    "lat": lat, "lon": lng, "format": "jsonv2",
                    "addressdetails": 1,
                    "zoom": self.cfg.get("geocode_zoom", 16),
                    "accept-language": self.cfg.get("geocode_lang", "ja"),
                },
                headers={"User-Agent": self.cfg.get("user_agent", "GenbaPhotoApp/1.0")},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"[geocoder] Nominatim HTTP {resp.status_code}")
                return None
            data = resp.json()
            return _build_place_name(data)
        except Exception as e:
            print(f"[geocoder] 逆ジオコーディング失敗: {e}")
            return None


def _build_place_name(data: dict) -> str | None:
    """Nominatim応答から日本語の地点フォルダ名を組み立てる。

    例: 新宿区 + 西新宿 → 「新宿区西新宿」。POI名があれば優先利用。
    """
    addr = data.get("address", {}) or {}

    # POI/施設名があればそれを最優先（会社・施設のことが多い）
    poi = data.get("name") or addr.get("amenity") or addr.get("building") or addr.get("office")

    ward = (addr.get("city") or addr.get("town") or addr.get("city_district")
            or addr.get("county") or addr.get("village"))
    area = (addr.get("suburb") or addr.get("neighbourhood")
            or addr.get("quarter") or addr.get("hamlet"))
    block = addr.get("city_block") or addr.get("block")

    parts = [p for p in (ward, area, block) if p]
    base = "".join(parts) if parts else None

    if poi and base:
        name = f"{base}_{poi}"
    elif poi:
        name = poi
    elif base:
        name = base
    else:
        # 最後の手段: 表示名の先頭要素
        dn = data.get("display_name")
        name = dn.split(",")[0].strip() if dn else None
    return name
