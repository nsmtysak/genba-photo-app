"""mDNS（Zeroconf）でPCをLANに広告する。

advertised_hostname（既定 genba-photo.local）のAレコードを公開し、
スマホが固定ホスト名でPCを発見できるようにする（IP直打ち不要）。
zeroconf が無い／登録に失敗してもサーバー本体は動作する（IP手入力で代替可）。
"""
from __future__ import annotations

import socket
from utils import get_local_ips


class Discovery:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._zc = None
        self._info = None

    def start(self) -> None:
        try:
            from zeroconf import Zeroconf, ServiceInfo
        except Exception:
            print("[discovery] zeroconf未導入のためmDNS広告は無効（IP手入力で接続可）。")
            return

        ips = get_local_ips()
        if not ips:
            print("[discovery] LAN IPを検出できずmDNS広告を見送ります。")
            return

        hostname = self.cfg.get("advertised_hostname", "genba-photo.local")
        server = hostname if hostname.endswith(".") else hostname + "."
        port = int(self.cfg.get("port", 8443))
        try:
            self._zc = Zeroconf()
            self._info = ServiceInfo(
                "_https._tcp.local.",
                "現場写真._https._tcp.local.",
                addresses=[socket.inet_aton(ip) for ip in ips],
                port=port,
                properties={"path": "/api/ping"},
                server=server,
            )
            self._zc.register_service(self._info)
            print(f"[discovery] mDNS広告開始: https://{hostname}:{port} ({', '.join(ips)})")
        except Exception as e:
            print(f"[discovery] mDNS広告に失敗（IP手入力で接続可）: {type(e).__name__}: {e!r}")
            self._zc = None

    def stop(self) -> None:
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
            if self._zc:
                self._zc.close()
        except Exception:
            pass
