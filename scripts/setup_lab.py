"""Lab Environment Setup & TLS Certificate Generator for EC - Echo Kiddo.

Generates self-signed TLS certificates with SAN for localhost and LAN IP,
computes the SHA-256 fingerprint for Agent Certificate Pinning,
seeds demonstration data into SQLite, and provides complete execution instructions.
"""
import datetime
import hashlib
import ipaddress
import os
import socket
import subprocess
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
CERTS_DIR = ROOT_DIR / "certs"


def get_lan_ip() -> str:
    """Detects active LAN IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually send data over network
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def generate_self_signed_cert() -> tuple[Path, Path, str]:
    """Generates 2048-bit RSA private key and self-signed X.509 TLS certificate with SAN."""
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    key_path = CERTS_DIR / "server.key"
    crt_path = CERTS_DIR / "server.crt"
    fp_path = CERTS_DIR / "pinned_cert.sha256"
    env_path = CERTS_DIR / "ogk_lab.env"

    print("• Đang sinh khóa riêng tư RSA 2048-bit...")
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Write private key
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    hostname = socket.gethostname()
    lan_ip = get_lan_ip()

    print(f"• Cấu hình SAN (Subject Alternative Name): localhost, {hostname}, 127.0.0.1, {lan_ip}")

    # Build SAN entries
    san_list = [
        x509.DNSName("localhost"),
        x509.DNSName("127.0.0.1"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    if hostname.lower() != "localhost":
        san_list.append(x509.DNSName(hostname))

    if lan_ip != "127.0.0.1":
        try:
            san_list.append(x509.IPAddress(ipaddress.IPv4Address(lan_ip)))
            san_list.append(x509.DNSName(lan_ip))
        except Exception:
            pass

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "VN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Ho Chi Minh"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Thu Duc"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Open Guardian for Kids Lab"),
        x509.NameAttribute(NameOID.COMMON_NAME, "ogk.local"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    # Write CRT
    with open(crt_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    # Compute SHA-256 fingerprint on DER bytes
    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    sha256_fp = hashlib.sha256(der_bytes).hexdigest().lower()

    # Formatted colon fingerprint
    formatted_fp = ":".join(sha256_fp[i:i+2] for i in range(0, len(sha256_fp), 2))
    with open(fp_path, "w", encoding="utf-8") as f:
        f.write(formatted_fp + "\n")

    # Write lab environment snippet
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"OGK_SERVER_URL=https://127.0.0.1:8000\n")
        f.write(f"OGK_CA_CERT={crt_path}\n")
        f.write(f"OGK_PINNED_CERT_FINGERPRINT={formatted_fp}\n")

    return crt_path, key_path, formatted_fp


def run_demo_seeder() -> None:
    """Seeds parent account, child, device, policy, and sample events."""
    seeder_path = ROOT_DIR / "demo" / "seed_demo.py"
    if seeder_path.exists():
        print("• Nạp dữ liệu mô phỏng phòng Lab (demo/seed_demo.py)...")
        subprocess.run([sys.executable, str(seeder_path)], check=True)


def main() -> None:
    print("=" * 65)
    print("     EC - Echo Kiddo LAB SETUP: TẠO CHỨNG CHỈ TLS & KHỞI TẠO MÔI TRƯỜNG LAB    ")
    print("=" * 65)

    crt_path, key_path, fp = generate_self_signed_cert()
    lan_ip = get_lan_ip()

    print(f"✓ Đã sinh chứng chỉ TLS:  {crt_path}")
    print(f"✓ Đã sinh khóa riêng tư:  {key_path}")
    print(f"✓ SHA-256 Fingerprint:    {fp}")
    print("-" * 65)

    run_demo_seeder()

    print("=" * 65)
    print("         HƯỚNG DẪN KHỞI CHẠY PHÒNG LAB (LOCAL / LAN)             ")
    print("=" * 65)
    print("1. KHỞI CHẠY EC Server (HTTPS + WSS trên cổng 8000):")
    print(f"   .venv\\Scripts\\uvicorn server.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile certs/server.key --ssl-certfile certs/server.crt")
    print()
    print("   Truy cập Web Dashboard:")
    print("   • Localhost: https://127.0.0.1:8000/login")
    if lan_ip != "127.0.0.1":
        print(f"   • Qua LAN:   https://{lan_ip}:8000/login")
    print("   • Tài khoản: parent@ogk.local")
    print("   • Mật khẩu:  AdminPassword123!")
    print()
    print("2. KHỞI CHẠY EC Agent (Có Certificate Pinning & WSS):")
    print(f"   set OGK_SERVER_URL=https://127.0.0.1:8000")
    print(f"   set OGK_CA_CERT=certs/server.crt")
    print(f"   set OGK_PINNED_CERT_FINGERPRINT={fp}")
    print("   .venv\\Scripts\\python -m agent.service.win_service run")
    print()
    print("3. KHỞI CHẠY EC Tray UI (Giao diện khay hệ thống của trẻ):")
    print("   .venv\\Scripts\\python -m agent.ui.tray_app")
    print()
    print("4. HOÀN NGUYÊN & GỠ BỎ SẠCH SẼ (Clean Recovery):")
    print("   .venv\\Scripts\\python agent/cleanup/ogk_cleanup.py --pin 123456")
    print("=" * 65)


if __name__ == "__main__":
    main()
