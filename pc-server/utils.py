"""ファイル名・フォルダ名の安全化、保存名生成などの補助関数。"""
from __future__ import annotations

import re
import socket
from datetime import datetime
from pathlib import Path

# Windowsで使用できない文字
_INVALID = r'[\\/:*?"<>|]'
# Windowsの予約名
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_name(name: str, fallback: str = "_unknown", max_len: int = 80) -> str:
    """フォルダ/ファイル名に使える安全な文字列へ変換する。"""
    if not name or not str(name).strip():
        return fallback
    s = str(name)
    s = re.sub(_INVALID, "_", s)         # 禁止文字を置換
    s = re.sub(r"[\x00-\x1f]", "", s)    # 制御文字除去
    s = s.strip().rstrip(". ")            # 前後空白・末尾ピリオド除去
    s = s[:max_len].strip()
    if not s:
        return fallback
    if s.upper() in _RESERVED:
        s = "_" + s
    return s


def build_filename(captured_at: str | None, photo_id: str, mime: str) -> str:
    """YYYYMMDD_HHMMSS_<photo_id先頭8桁>.<ext> を生成する。"""
    ext = "jpg"
    if mime and "/" in mime:
        ext = mime.split("/")[-1].lower().replace("jpeg", "jpg")
        ext = re.sub(r"[^a-z0-9]", "", ext) or "jpg"
    dt = _parse_dt(captured_at)
    ts = dt.strftime("%Y%m%d_%H%M%S")
    short = (photo_id or "00000000").replace("-", "")[:8]
    return f"{ts}_{short}.{ext}"


def _parse_dt(s: str | None) -> datetime:
    if s:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    return datetime.now()


def coord_key(lat: float, lng: float, precision: int = 4) -> str:
    """座標を量子化したキャッシュキー。"""
    return f"{round(lat, precision)},{round(lng, precision)}"


def get_local_ips() -> list[str]:
    """LAN内のIPv4を推定して返す（証明書SAN・mDNS用）。"""
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # 実送信はしない。経路上の自IPを得る
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips)


def unique_path(path: Path) -> Path:
    """同名ファイルがあれば連番を付けて衝突回避する。"""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while True:
        cand = parent / f"{stem}_{i}{suffix}"
        if not cand.exists():
            return cand
        i += 1
