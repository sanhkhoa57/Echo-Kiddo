"""Tray menu 'Thoát': guarded by the parent PIN while OGK-Service is running."""
from agent.ui.tray_app import TrayApplication


class _Icon:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _DeadClient:
    def send_envelope(self, envelope):
        return None


class _LiveClient:
    def send_envelope(self, envelope):
        class _R:
            payload = {"challenge_token": "t"}
        return _R()


def test_exit_closes_tray_when_no_service_is_running():
    app = TrayApplication(ipc_client=_DeadClient(), headless=True)
    app.tray_icon = _Icon()
    app.request_exit()
    assert app.tray_icon.stopped and not app.running


def test_exit_needs_parent_pin_while_service_is_running():
    app = TrayApplication(ipc_client=_LiveClient(), headless=True)
    app.tray_icon = _Icon()
    app.request_exit()  # headless: PIN dialog is not shown, so nothing is authorised
    assert not app.tray_icon.stopped


def test_wrong_pin_is_never_authorised_without_service():
    app = TrayApplication(ipc_client=_DeadClient(), headless=True)
    assert app._verify_parent_pin("123456") is False
    assert app._verify_parent_pin("") is False
