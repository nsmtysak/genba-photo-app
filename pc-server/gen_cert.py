"""自己署名証明書を生成する。

PWA(HTTPS)からLAN内PCへ通信するため、PC側もHTTPSが必要（mixed-content回避）。
SANに advertised_hostname（既定 genba-photo.local）・localhost・検出したLAN IP を含める。
スマホ側はこの証明書を一度だけ信頼インストールする（セットアップガイド参照）。

生成物: certs/server.crt, certs/server.key
"""
from __future__ import annotations

import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from config import CERT_DIR, CERT_FILE, KEY_FILE, load_config
from utils import get_local_ips


def ensure_cert() -> tuple[Path, Path]:
    """証明書が無ければ生成して (crt, key) のパスを返す。"""
    if CERT_FILE.exists() and KEY_FILE.exists():
        return CERT_FILE, KEY_FILE
    return generate()


def generate() -> tuple[Path, Path]:
    cfg = load_config()
    hostname = cfg.get("advertised_hostname", "genba-photo.local")
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    san: list[x509.GeneralName] = [
        x509.DNSName(hostname),
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    for ip in get_local_ips():
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Genba Photo App"),
    ])
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))  # 10年
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    KEY_FILE.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"[cert] 自己署名証明書を生成しました: {CERT_FILE}")
    print(f"[cert] SAN: {hostname}, localhost, {', '.join(get_local_ips()) or '(LAN IP未検出)'}")
    return CERT_FILE, KEY_FILE


if __name__ == "__main__":
    generate()
