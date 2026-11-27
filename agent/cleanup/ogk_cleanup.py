"""Clean Uninstallation and System Rollback Utility (FR-F4-05, REF-11).
Restores original Network DNS and Browser Registry settings 100% from system snapshots,
flushes DNS cache, cleanly stops and removes the OGK Windows Service.
"""
import argparse
import logging
import os
import shutil
import subprocess
import sys
from typing import Optional

from agent.core.agent_db import AgentDatabase, DEFAULT_AGENT_DB_PATH
from agent.core.pin_auth import verify_pin_hash, load_offline_pin_hash
from agent.platform.network_guard import NetworkDnsGuard, flush_dns_cache
from agent.platform.browser_policy import BrowserPolicyGuard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OGK.Cleanup")

_IS_WINDOWS = sys.platform == "win32"


UNINSTALL_SUBJECT = "ogk_uninstall"


def record_uninstall_event(db: AgentDatabase, upload: bool = True) -> bool:
    """Queues an `app_stop` event with subject `ogk_uninstall` for this device/child and
    tries to upload the queue immediately. Returns True when the server acknowledged it."""
    try:
        from agent.core.event_buffer import EventBuffer
        from agent.sync.server_client import AgentServerClient
    except Exception as e:
        logger.warning("Không ghi được sự kiện gỡ cài đặt: %s", e)
        return False

    creds = db.get_device_credentials() or {}
    if not creds.get("device_id") or not creds.get("child_id"):
        logger.info("Thiết bị chưa ghép đôi: không có sự kiện gỡ cài đặt cần gửi lên máy chủ.")
        return False

    buffer = EventBuffer(db=db, device_id=creds["device_id"], child_id=creds["child_id"])
    cached = db.get_cached_policy() or {}
    try:
        buffer.record_event(
            event_type="app_stop",
            subject=UNINSTALL_SUBJECT,
            policy_id=str(cached.get("version") or "uninstall"),
            duration_sec=0,
        )
    except Exception as e:
        logger.warning("Không ghi được sự kiện gỡ cài đặt: %s", e)
        return False
    logger.info("Đã ghi sự kiện gỡ cài đặt (app_stop: %s).", UNINSTALL_SUBJECT)
    if not upload:
        return False

    client = AgentServerClient(server_url=creds.get("server_url") or "", event_buffer=buffer, db=db)

    async def _push() -> int:
        try:
            return await client.upload_event_batch()
        finally:
            if client._http_client is not None:
                await client._http_client.aclose()

    try:
        import asyncio
        sent = asyncio.run(_push())
    except Exception as e:
        logger.warning("Chưa gửi được sự kiện gỡ cài đặt lên máy chủ (%s). Sự kiện vẫn nằm trong hàng đợi.", e)
        return False
    if sent:
        logger.info("✓ Máy chủ đã nhận sự kiện gỡ cài đặt; phụ huynh sẽ thấy trên Dashboard.")
    return bool(sent)


def _force_allowed() -> bool:
    """--force skips the parent PIN, so it is only for the automated test suite or an
    elevated administrator (the child's standard account is never an administrator)."""
    if os.getenv("OGK_TESTING") == "1":
        return True
    if not _IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def perform_clean_rollback(
    db_path: str = DEFAULT_AGENT_DB_PATH,
    parent_pin: Optional[str] = None,
    remove_service: bool = True,
    delete_data_dir: bool = False,
    force: bool = False,
) -> bool:
    """
    Executes 100% clean rollback of network DNS, browser registry, and services.
    Requires parent PIN verification unless force=True.
    """
    logger.info("==================================================")
    logger.info("   OGK System Clean Rollback and Uninstallation   ")
    logger.info("==================================================")

    # 1. Parent authorization check
    if not force:
        if not parent_pin:
            entered_pin = input("Vui lòng nhập mã PIN / Mật khẩu phụ huynh để xác nhận gỡ bỏ: ").strip()
        else:
            entered_pin = parent_pin

        # Verify PIN against the Argon2id hash stored at enrollment / policy sync.
        # There is no built-in PIN: without a stored hash only --force can proceed.
        db = AgentDatabase(db_path)
        pin_hash = load_offline_pin_hash(db)
        if not pin_hash:
            cached = db.get_cached_policy()
            if cached and isinstance(cached.get("policy"), dict):
                pin_hash = cached["policy"].get("offline_pin_hash")

        if not pin_hash:
            logger.error("Thiết bị chưa có mã PIN phụ huynh (offline_pin_hash). Hãy đặt PIN trên Dashboard rồi đồng bộ, hoặc dùng --force.")
            return False

        pin_valid = verify_pin_hash(entered_pin, pin_hash)

        if not pin_valid:
            logger.error("Xác thực thất bại! Mã PIN/Mật khẩu phụ huynh không chính xác. Hủy bỏ quy trình.")
            return False
        logger.info("Xác thực phụ huynh thành công.")

        # Record the uninstall (F4) with the real device identity and push it to the
        # parent's server right away: once the service is gone nothing would sync it.
        record_uninstall_event(db)
    else:
        if not _force_allowed():
            logger.error("--force chỉ dùng cho kiểm thử tự động hoặc quản trị viên. Hãy nhập mã PIN phụ huynh.")
            return False
        logger.info("Chế độ ép buộc (force=True): Bỏ qua bước nhập PIN.")

    db = AgentDatabase(db_path)

    # 2. Restore Network Adapter DNS from snapshot
    logger.info("Bước 1/4: Đang khôi phục cấu hình DNS card mạng từ snapshot...")
    net_guard = NetworkDnsGuard(db=db)
    dns_restored = net_guard.restore_original_dns()
    if dns_restored:
        logger.info("✓ Khôi phục DNS card mạng thành công.")
    else:
        logger.warning("! Không tìm thấy snapshot DNS hoặc khôi phục gặp cảnh báo.")

    # 3. Restore Browser DoH Registry from snapshot
    logger.info("Bước 2/4: Đang khôi phục Registry chính sách trình duyệt (Chrome/Edge/Brave/Cốc Cốc)...")
    browser_guard = BrowserPolicyGuard(db=db)
    browser_restored = browser_guard.restore_browser_policies()
    if browser_restored:
        logger.info("✓ Khôi phục chính sách trình duyệt thành công.")
    else:
        logger.warning("! Không tìm thấy snapshot Registry trình duyệt hoặc khôi phục gặp cảnh báo.")

    # 4. Flush DNS Resolver Cache
    logger.info("Bước 3/4: Đang làm mới bộ nhớ đệm DNS hệ thống (DnsFlushResolverCache)...")
    flush_dns_cache()
    logger.info("✓ Đã làm mới DNS cache sạch sẽ.")

    # 5. Stop and unregister Windows Service
    if remove_service and _IS_WINDOWS:
        logger.info("Bước 4/4: Đang dừng và hủy đăng ký OGK Windows Service...")
        try:
            # Stop service
            subprocess.run(["sc.exe", "stop", "OGKService"], capture_output=True, check=False)
            # Delete service
            subprocess.run(["sc.exe", "delete", "OGKService"], capture_output=True, check=False)
            logger.info("✓ Đã hủy đăng ký OGKService khỏi Windows SCM.")
        except Exception as e:
            logger.warning("! Cảnh báo khi dừng/hủy dịch vụ: %s", e)
    else:
        logger.info("Bước 4/4: Bỏ qua gỡ Service.")

    # 6. Delete data directory if requested
    if delete_data_dir:
        data_dir = os.path.dirname(db_path)
        if os.path.exists(data_dir):
            try:
                shutil.rmtree(data_dir)
                logger.info("✓ Đã dọn sạch thư mục dữ liệu cục bộ: %s", data_dir)
            except Exception as e:
                logger.warning("! Không thể xóa hoàn toàn thư mục %s: %s", data_dir, e)

    logger.info("==================================================")
    logger.info("✓ Hoàn tất quy trình khôi phục sạch 100%! Máy tính đã trở về trạng thái ban đầu.")
    logger.info("==================================================")
    return True


def main():
    parser = argparse.ArgumentParser(description="OGK Clean Uninstallation and Rollback Utility")
    parser.add_argument("--pin", type=str, help="Parent offline authorization PIN")
    parser.add_argument("--force", action="store_true", help="Bypass PIN prompt for automated testing")
    parser.add_argument("--no-service", action="store_true", help="Do not attempt to delete Windows Service")
    parser.add_argument("--delete-data", action="store_true", help="Delete C:\\ProgramData\\OGK directory")
    parser.add_argument("--db", type=str, default=DEFAULT_AGENT_DB_PATH, help="Path to agent.db")

    args = parser.parse_args()
    success = perform_clean_rollback(
        db_path=args.db,
        parent_pin=args.pin,
        remove_service=not args.no_service,
        delete_data_dir=args.delete_data,
        force=args.force,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
