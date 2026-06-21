"""フェーズ3 ローカル検証（ネットワーク不要）。

外部APIには触れず、格納ロジック・重複排除・地点名組み立て・証明書生成・
FastAPIエンドポイントを検証する。Nominatim呼び出しはキャッシュ事前投入で回避。
"""
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import server
from geocoder import Geocoder, _build_place_name, NO_GPS_FOLDER
from utils import sanitize_name, build_filename, coord_key, unique_path


def test_utils():
    assert sanitize_name('A/B:C*?') == 'A_B_C__'
    assert sanitize_name('') == '_unknown'
    assert sanitize_name('   ') == '_unknown'
    assert sanitize_name('CON') == '_CON'
    fn = build_filename('2026-06-21T09:32:11+09:00', '8c9523c7-8dac-4310', 'image/jpeg')
    assert fn == '20260621_093211_8c9523c7.jpg', fn
    assert coord_key(35.689487, 139.691706, 4) == '35.6895,139.6917'
    print('  utils OK:', fn)


def test_build_place_name():
    sample = {"address": {"city": "新宿区", "suburb": "西新宿", "road": "○○通り"}}
    assert _build_place_name(sample) == '新宿区西新宿'
    poi = {"name": "○○建設", "address": {"city": "新宿区", "suburb": "西新宿"}}
    assert _build_place_name(poi) == '新宿区西新宿_○○建設'
    empty = {"address": {}, "display_name": "Somewhere, Tokyo"}
    assert _build_place_name(empty) == 'Somewhere'
    print('  build_place_name OK')


def test_storage_and_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {"root_path": tmp, "coord_precision": 4}
        st = server.Storage(cfg)
        # Nominatim呼び出しを避けるためキャッシュ事前投入
        st.geocoder.cache[coord_key(35.6895, 139.6917, 4)] = '新宿区西新宿'

        meta = {"photo_id": "id-001", "project_name": "○○ビル改修", "captured_at": "2026-06-21T09:32:11+09:00",
                "gps": {"lat": 35.6895, "lng": 139.6917, "available": True}, "mime": "image/jpeg"}
        r1 = st.store(b"JPEGDATA", meta)
        assert r1["dedup"] is False
        assert r1["place"] == "新宿区西新宿"
        assert r1["project"] == "○○ビル改修"
        saved = Path(tmp) / r1["saved_path"]
        assert saved.exists()
        assert saved.parts[-3:] == ("新宿区西新宿", "○○ビル改修", saved.name)

        # 同一photo_id再送 → dedup
        r2 = st.store(b"JPEGDATA", meta)
        assert r2["dedup"] is True, r2

        # GPSなし → _未分類_GPSなし、案件名なし → 未案件
        meta2 = {"photo_id": "id-002", "project_name": None, "captured_at": "2026-06-21T10:00:00+09:00",
                 "gps": {"available": False, "lat": None, "lng": None}, "mime": "image/jpeg"}
        r3 = st.store(b"X", meta2)
        assert r3["place"] == NO_GPS_FOLDER
        assert r3["project"] == "未案件"
        assert (Path(tmp) / NO_GPS_FOLDER / "未案件").exists()
        print('  storage/dedup OK:', r1["saved_path"])


def test_cert():
    import gen_cert
    crt, key = gen_cert.generate()
    assert crt.exists() and key.exists()
    data = crt.read_bytes()
    assert b"BEGIN CERTIFICATE" in data
    print('  cert OK:', crt.name)


def test_endpoints():
    # STATEのstorageを一時ディレクトリへ差し替え
    tmp = tempfile.mkdtemp()
    server.STATE.cfg["root_path"] = tmp
    server.STATE.cfg["token"] = ""  # 認証なしでテスト
    server.STATE.rebuild_storage()
    server.STATE.storage.geocoder.cache[coord_key(35.6895, 139.6917, 4)] = '新宿区西新宿'

    client = TestClient(server.app)

    # ping
    p = client.get("/api/ping")
    assert p.status_code == 200, p.text
    assert p.json()["status"] == "ok"
    assert p.json()["version"] == server.VERSION

    # photos（multipart）
    meta = {"photo_id": "ep-001", "project_name": "Eテスト", "captured_at": "2026-06-21T09:32:11+09:00",
            "gps": {"lat": 35.6895, "lng": 139.6917, "available": True}, "mime": "image/jpeg"}
    resp = client.post(
        "/api/photos",
        files={"file": ("ep-001.jpg", b"BYTES", "image/jpeg")},
        data={"meta": json.dumps(meta)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok" and body["place"] == "新宿区西新宿", body
    assert (Path(tmp) / "新宿区西新宿" / "Eテスト").exists()

    # config
    c = client.get("/api/config")
    assert c.status_code == 200 and c.json()["root_path"] == tmp
    print('  endpoints OK:', body["saved_path"])


def test_auth():
    server.STATE.cfg["token"] = "secret123"
    client = TestClient(server.app)
    assert client.get("/api/ping").status_code == 401
    ok = client.get("/api/ping", headers={"Authorization": "Bearer secret123"})
    assert ok.status_code == 200
    server.STATE.cfg["token"] = ""
    print('  auth OK')


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"[RUN] {name}")
            fn()
    print("\nALL TESTS PASSED")
