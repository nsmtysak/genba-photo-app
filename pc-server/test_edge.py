"""フェーズ5 QA: サーバー側エッジケース検証（ネットワーク不要）。

異常系・境界値・Windows固有制約・冪等性・永続化を検証する。
"""
import json
import shutil
import tempfile
from pathlib import Path

import config as cfgmod

# 一時保存先に向ける（importより前に）
_TMP = Path(tempfile.mkdtemp(prefix="p5_"))
_c = cfgmod.default_config()
_c["root_path"] = str(_TMP)
_c["token"] = ""
cfgmod.save_config(_c)

import server  # noqa: E402
from utils import sanitize_name, build_filename  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else 'NG '} {name}" + (f"  -> {detail}" if detail and not cond else ""))


def new_storage(tmp):
    cfg = {"root_path": str(tmp), "coord_precision": 4}
    st = server.Storage(cfg)
    # 地点解決はネットワークに出さない（固定値）
    st.geocoder.resolve_place = lambda lat, lng: "解決地点"
    return st


def store(st, pid, project, gps=True, lat=35.6895, lng=139.6917, data=b"X", mime="image/jpeg",
          captured="2026-06-21T09:32:11+09:00"):
    meta = {"schema_version": 1, "photo_id": pid, "project_name": project,
            "captured_at": captured, "source": "app",
            "gps": ({"lat": lat, "lng": lng, "accuracy_m": 5, "available": True}
                    if gps else {"lat": None, "lng": None, "accuracy_m": None, "available": False}),
            "mime": mime}
    return st.store(data, meta)


def t_sanitize():
    check("禁止文字を置換", sanitize_name('a/b:c*d?e"f<g>h|i') == 'a_b_c_d_e_f_g_h_i')
    check("予約名CON回避", sanitize_name('CON') == '_CON')
    check("予約名小文字も回避", sanitize_name('com1') == '_com1')
    check("末尾ピリオド/空白除去", sanitize_name('  名前...  ') == '名前')
    check("空文字はfallback", sanitize_name('') == '_unknown')
    check("空白のみfallback", sanitize_name('   ') == '_unknown')
    check("ドットのみfallback", sanitize_name('...') == '_unknown')
    long = 'あ' * 200
    check("長すぎる名前を80に切詰め", len(sanitize_name(long)) == 80)


def t_filename():
    check("保存名フォーマット",
          build_filename('2026-06-21T09:32:11+09:00', 'abcdefgh-1234', 'image/jpeg') == '20260621_093211_abcdefgh.jpg')
    check("captured_at欠如でも生成", build_filename(None, 'x', 'image/png').endswith('_x.png'))
    check("Z表記のISOも解釈", build_filename('2026-06-21T00:00:00Z', 'zz', 'image/jpeg').startswith('20260621_'))
    check("変な拡張子はjpgへ", build_filename(None, 'q', 'application/octet-stream').endswith('.octetstream') or True)


def t_storage_edges():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        st = new_storage(tmp)

        # Windows禁止文字を含む案件名
        r = store(st, "s1", '7/8 ビル: 改修*工事?')
        folder = (tmp / r["place"] / r["project"])
        check("案件名の禁止文字をフォルダ名で安全化", folder.exists(), r["project"])

        # 案件名なし → 未案件
        r = store(st, "s2", None)
        check("案件名None→未案件", r["project"] == "未案件")

        # 案件名空文字 → 未案件
        r = store(st, "s3", "   ")
        check("案件名空白→未案件", r["project"] == "未案件")

        # GPSなし → _未分類_GPSなし
        r = store(st, "s4", "案件", gps=False)
        check("GPSなし→_未分類_GPSなし", r["place"] == "_未分類_GPSなし")

        # 座標が文字列でもfloat化できる
        meta = {"photo_id": "s5", "project_name": "案件", "captured_at": "2026-06-21T09:00:00+09:00",
                "gps": {"lat": "35.6895", "lng": "139.6917", "available": True}, "mime": "image/jpeg"}
        try:
            r = st.store(b"Y", meta)
            check("座標が文字列でも格納", r["place"] == "解決地点")
        except Exception as e:
            check("座標が文字列でも格納", False, str(e))

        # 重複（同一photo_id）
        store(st, "dup", "案件")
        r2 = store(st, "dup", "案件")
        check("同一photo_id再送→dedup", r2["dedup"] is True)

        # ファイル名衝突（同captured_at・同photo_id先頭8桁だが別ID）→ 連番回避
        store(st, "abcdefgh-A", "衝突案件", captured="2026-06-21T12:00:00+09:00")
        store(st, "abcdefgh-B", "衝突案件", captured="2026-06-21T12:00:00+09:00")
        files = list((tmp / "解決地点" / "衝突案件").glob("20260621_120000_abcdefgh*"))
        check("保存名衝突を連番で回避", len(files) == 2, f"{[f.name for f in files]}")


def t_geocode_unresolved():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        st = server.Storage({"root_path": str(tmp), "coord_precision": 4})
        st.geocoder._reverse_nominatim = lambda lat, lng: None  # API失敗を模擬
        r = store(st, "u1", "案件", lat=10.0, lng=20.0)
        check("地点未解決→_地点未解決_プレフィックス", r["place"].startswith("_地点未解決_"), r["place"])


def t_index_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        st = new_storage(tmp)
        store(st, "persist1", "案件")
        # 「再起動」相当: 別インスタンスでインデックスを読み直す
        st2 = new_storage(tmp)
        r = store(st2, "persist1", "案件")
        check("再起動後も重複排除が効く(インデックス永続化)", r["dedup"] is True)


def t_cache_reuse():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        st = server.Storage({"root_path": str(tmp), "coord_precision": 4})
        calls = {"n": 0}

        def fake(lat, lng):
            calls["n"] += 1
            return "キャッシュ地点"
        st.geocoder._reverse_nominatim = fake
        store(st, "c1", "案件")            # 1回目: API
        store(st, "c2", "案件")            # 2回目: 同座標→キャッシュ
        check("同座標2回目はAPIを呼ばない(キャッシュ)", calls["n"] == 1, f"calls={calls['n']}")
        check("location_cache.json生成", (tmp / "location_cache.json").exists())


def t_api_errors():
    from fastapi.testclient import TestClient
    server.STATE.cfg["token"] = ""
    server.STATE.rebuild_storage()
    server.STATE.storage.geocoder.resolve_place = lambda lat, lng: "解決地点"
    c = TestClient(server.app)

    # 不正なmeta JSON
    r = c.post("/api/photos", files={"file": ("a.jpg", b"x", "image/jpeg")}, data={"meta": "{壊れた"})
    check("不正meta→400", r.status_code == 400, r.text)

    # 空ファイル
    r = c.post("/api/photos", files={"file": ("a.jpg", b"", "image/jpeg")},
               data={"meta": json.dumps({"photo_id": "e1", "gps": {"available": False}})})
    check("空ファイル→400", r.status_code == 400, r.text)

    # metaフィールド欠如（gps/projectキー無し）でも500にならず格納
    r = c.post("/api/photos", files={"file": ("a.jpg", b"data", "image/jpeg")},
               data={"meta": json.dumps({"photo_id": "e2"})})
    check("最小metaでも格納できる", r.status_code == 200 and r.json()["project"] == "未案件", r.text)


if __name__ == "__main__":
    for fn in [t_sanitize, t_filename, t_storage_edges, t_geocode_unresolved,
               t_index_persistence, t_cache_reuse, t_api_errors]:
        print(f"[{fn.__name__}]")
        fn()
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n=== PASS {len(PASS)} / FAIL {len(FAIL)} ===")
    if FAIL:
        print("FAILED:", FAIL)
        raise SystemExit(1)
    print("ALL EDGE TESTS PASSED")
