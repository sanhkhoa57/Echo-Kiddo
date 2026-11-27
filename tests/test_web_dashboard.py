"""Tests for Web Dashboard HTML routes and session flows."""
import os
import pytest
from fastapi.testclient import TestClient

from sqlalchemy.orm import sessionmaker

from server.main import app
from server.models.base import Base
from server.models.database import create_ogk_engine, get_db
from server.models.user import User
from server.models.child import Child
from server.auth.security import (
    get_password_hash,
    create_jwt_token,
    SESSION_COOKIE_EXPIRE_HOURS,
)
from server.routers.web import SESSION_COOKIE_NAME, CSRF_COOKIE_NAME


@pytest.fixture(scope="module")
def web_test_client(tmp_path_factory):
    """Temp SQLite DB, so the suite never writes test accounts into server/data/server.db."""
    os.environ["OGK_TESTING"] = "1"
    engine = create_ogk_engine(f"sqlite:///{tmp_path_factory.mktemp('web') / 'web.db'}")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = SessionLocal()
    parent = User(
        id="usr_dash_01",
        email="dashboard_parent@test.com",
        password_hash=get_password_hash("ParentPass123!"),
        role="parent",
    )
    db.add(parent)
    db.commit()
    db.add(Child(id="chd_dash_01", parent_id=parent.id, display_name="Bé Minh", age_group="6-11"))
    db.commit()
    db.close()

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    engine.dispose()


def _login_form(client, email="dashboard_parent@test.com", password="ParentPass123!"):
    """Real login flow: GET /login sets the ogk_csrf cookie, the form echoes it back."""
    client.get("/login")
    token = client.cookies.get(CSRF_COOKIE_NAME)
    return {"email": email, "password": password, "csrf_token": token}


def test_login_page_renders(web_test_client):
    resp = web_test_client.get("/login")
    assert resp.status_code == 200
    assert "Đăng Nhập Phụ Huynh" in resp.text
    assert "csrf_token" in resp.text


def test_login_invalid_password(web_test_client):
    resp = web_test_client.post(
        "/login",
        data=_login_form(web_test_client, password="WrongPassword123!"),
    )
    assert resp.status_code == 200
    assert "không chính xác" in resp.text


def test_login_success_and_dashboard_access(web_test_client):
    resp = web_test_client.post(
        "/login",
        data=_login_form(web_test_client),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"
    cookies = resp.cookies
    assert SESSION_COOKIE_NAME in cookies

    # Access dashboard with cookie
    dash_resp = web_test_client.get("/dashboard", cookies=cookies)
    assert dash_resp.status_code == 200
    assert "Bé Minh" in dash_resp.text
    assert "Lệnh Điều Khiển Khẩn" in dash_resp.text
    assert "Xóa Toàn Bộ Dữ Liệu Con Tôi" in dash_resp.text


def test_child_view_and_audit_log_access(web_test_client):
    # Child view is accessible
    web_test_client.cookies.clear()
    resp = web_test_client.get("/child-view")
    assert resp.status_code == 200
    assert "Hôm nay em đã dùng gì?" in resp.text

    # Signed in: the child's own data and the no-surveillance promise are shown
    web_test_client.cookies.clear()
    resp = web_test_client.get("/child-view")
    assert "Cần đăng nhập" in resp.text
    login = web_test_client.post("/login", data=_login_form(web_test_client), follow_redirects=False)
    resp = web_test_client.get("/child-view", cookies=login.cookies)
    assert resp.status_code == 200
    assert "Chào Bé Minh" in resp.text
    assert "Không chụp ảnh màn hình" in resp.text
    assert "Giờ được dùng máy hôm nay" in resp.text

    # Audit log view is accessible
    resp_audit = web_test_client.get("/audit/view")
    assert resp_audit.status_code == 200
    assert "Nhật Ký Kiểm Toán Công Khai" in resp_audit.text


def test_logout(web_test_client):
    resp = web_test_client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_login_rejects_forged_csrf(web_test_client):
    """F5: the login form only accepts the CSRF token issued with the login page."""
    web_test_client.cookies.clear()
    resp = web_test_client.post("/login", data={
        "email": "dashboard_parent@test.com", "password": "ParentPass123!", "csrf_token": "forged",
    }, follow_redirects=False)
    assert resp.status_code == 200          # re-rendered login form, no session
    assert SESSION_COOKIE_NAME not in resp.cookies


def test_logout_revokes_session_server_side(web_test_client):
    """F5: after logout the old session token is useless even if it was copied."""
    web_test_client.cookies.clear()
    login = web_test_client.post("/login", data=_login_form(web_test_client), follow_redirects=False)
    stolen = login.cookies.get(SESSION_COOKIE_NAME)
    assert stolen
    web_test_client.cookies.clear()
    assert web_test_client.get("/dashboard", cookies={SESSION_COOKIE_NAME: stolen},
                               follow_redirects=False).status_code == 200

    out = web_test_client.get("/logout", cookies={SESSION_COOKIE_NAME: stolen}, follow_redirects=False)
    assert out.status_code == 302
    web_test_client.cookies.clear()

    again = web_test_client.get("/dashboard", cookies={SESSION_COOKIE_NAME: stolen}, follow_redirects=False)
    assert again.status_code == 302 and again.headers["location"] == "/login"
    api = web_test_client.get("/api/v1/reports/chd_dash_01", headers={"Authorization": f"Bearer {stolen}"})
    assert api.status_code == 401


def test_child_view_role_is_read_only_and_scoped(web_test_client):
    """F5: third role `child-view`: sees its own child's report/audit, never parent actions."""
    web_test_client.cookies.clear()
    login = web_test_client.post("/login", data=_login_form(web_test_client), follow_redirects=False)
    parent_cookie = login.cookies.get(SESSION_COOKIE_NAME)
    web_test_client.cookies.clear()

    page = web_test_client.get("/child-view", cookies={SESSION_COOKIE_NAME: parent_cookie})
    import re
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    start = web_test_client.post("/child-view/start", data={"child_id": "chd_dash_01", "csrf_token": csrf},
                                 cookies={SESSION_COOKIE_NAME: parent_cookie}, follow_redirects=False)
    assert start.status_code == 302
    kid_cookie = start.cookies.get(SESSION_COOKIE_NAME)
    assert kid_cookie and kid_cookie != parent_cookie
    web_test_client.cookies.clear()
    kid = {"Authorization": f"Bearer {kid_cookie}"}

    # The parent session handed over is revoked
    assert web_test_client.get("/api/v1/reports/chd_dash_01",
                               headers={"Authorization": f"Bearer {parent_cookie}"}).status_code == 401
    # Read: own report and audit log
    assert web_test_client.get("/api/v1/reports/chd_dash_01", headers=kid).status_code == 200
    assert web_test_client.get("/api/v1/audit/chd_dash_01", headers=kid).status_code == 200
    # Write: parent-only endpoints are forbidden
    assert web_test_client.get("/api/v1/policy/chd_dash_01", headers=kid).status_code == 403
    assert web_test_client.post("/api/v1/commands", headers=kid,
                                json={"child_id": "chd_dash_01", "command": "UNLOCK"}).status_code == 403
    # Dashboard redirects the child-view session to the child screen
    dash = web_test_client.get("/dashboard", cookies={SESSION_COOKIE_NAME: kid_cookie}, follow_redirects=False)
    assert dash.status_code == 302 and dash.headers["location"] == "/child-view"
    web_test_client.cookies.clear()
