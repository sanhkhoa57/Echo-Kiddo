# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

OGK (Open Guardian for Kids) is a university Computer Networks course project (spec: `DoAn01.docx`, plain-text copy in `docs/DoAn01_extracted.txt`). It has two parts:
- A Windows 10/11 agent that enforces screen time and filters apps and websites through a local DNS proxy.
- A FastAPI server that issues HMAC-signed policies and serves a parent dashboard.

The docs, UI text and README are written in Vietnamese. Keep user-facing strings in Vietnamese.

Positioning drives many design decisions: "a companion, not stalkerware". That rules out:
- any stealth mode,
- screenshots,
- logging full URLs.

Events have exactly 7 fields (`ts, device_id, child_id, type, subject, duration_sec, policy_id`). `subject` holds only an exe name or an eTLD+1 domain. If the tray cannot be shown, the service goes to `UNPROTECTED_HALT` instead of running invisibly.

## Commands

Use the project venv (`.venv\Scripts\python.exe`); `python` is not on PATH in Git Bash.

```powershell
pip install -r server/requirements.txt -r agent/requirements.txt
python demo/seed_demo.py                                   # demo data: parent@ogk.local / AdminPassword123!
uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
python agent/service/win_service.py run                    # agent in console mode (admin needed for real DNS lock)
python agent/ui/tray_app.py                                # tray UI alone
python agent/cleanup/ogk_cleanup.py --pin <PIN>            # restore adapter DNS + browser registry (--force in tests/admin)

pytest -q                                                  # full suite
pytest tests/test_dns_hardening.py::test_sinkhole_matches_query_type -q   # single test
python tests/benchmark_m4.py                               # M4 benchmark -> docs/benchmark_m4_results.md (OGK_BENCH_OFFLINE=1 without Internet)
python scripts/gen_baocao.py; python scripts/gen_baocao_mang.py   # regenerate docs/BaoCao.docx and docs/BaoCaoKyThuatMang.pdf
.\scripts\run_dev.ps1 setup|server|agent|tray|all          # TLS cert + lab launcher (setup_lab.py prints OGK_PINNED_CERT_FINGERPRINT)
```

If you change behaviour, test counts, or the features a report describes, update `README.md` and the text in `scripts/gen_baocao*.py`, then regenerate the reports.

## Test-mode safety

`tests/conftest.py` sets `OGK_TESTING=1`. In that mode:
- `agent/platform/network_guard.py` (`system_changes_allowed()`, `_netsh`) and `browser_policy.py` never touch the real network adapters or the registry.
- The server skips its background retention worker.

Setting `OGK_ALLOW_SYSTEM_CHANGES=1` disables that guard, so don't set it in tests. Any new code that runs `netsh`, `icacls` or writes to the registry must go through the same guard, because the suite may be run from an admin shell.

## Architecture

### Agent (`agent/`)

**Processes.** The agent runs as two processes that talk over a named pipe (`agent/ipc/pipe_protocol.py`, `IpcEnvelope`):
- `OGKServiceCore` in `agent/service/win_service.py` runs as LocalSystem in Session 0 and owns all enforcement.
- The tray in `agent/ui/tray_app.py` runs in the user session. It:
  - polls for session status,
  - reports idle and lock state back to the service,
  - calls `LockWorkStation` for hard locks, since Session 0 cannot lock the user's desktop.

**DNS ordering.** `agent/dns/dns_proxy.py` serves 127.0.0.1:53 and [::1]:53 over UDP and TCP, using `DomainPolicyEngine` from `domain_engine.py` (HashSet + suffix trie, SafeSearch CNAME map, DoH canary). The order matters: adapters are pointed at loopback by `NetworkDnsGuard.lock_dns_to_loopback` only after `dns_proxy.start()` succeeds, via `_lock_dns_to_proxy`. Never reorder this. Locking first leaves the PC with no DNS if the proxy fails to start. The proxy falls back to the network's original resolvers, taken from the DNS snapshot through `original_upstreams()`.

**Snapshot and rollback.** Every system change is snapshotted into `agent.db` (`agent/core/agent_db.py`, SQLite, secrets encrypted AES-256-GCM with a DPAPI-wrapped key) and restored on stop or uninstall. Adapter DNS is read from the registry, not by parsing `netsh` output, so it doesn't depend on the Windows display language.

**Enforcement.**
- Screen time lives in `agent/core/screen_time.py`:
  - 7×48 half-hour schedule matrix,
  - per-category budgets (negative means unlimited),
  - trusted time from a monotonic `GetTickCount64` offset plus server drift, to defeat clock tampering.
- `agent/core/app_controller.py` kills blocked or over-budget processes, only outside Session 0 and never on the whitelisted system exes.

**Sync.** `agent/sync/server_client.py` handles:
- HTTPS with certificate pinning (`OGK_PINNED_CERT_FINGERPRINT`),
- a 60 s heartbeat and policy pull,
- a WebSocket channel for emergency commands (`LOCK_NOW`, `UNLOCK`, `ADD_TIME_15M`, pause),
- offline event batches with idempotency keys.

**Policy verification.** `agent/core/policy_verifier.py` rejects any policy whose HMAC does not match the one signed in `server/services/policy_service.py`.

### Server (`server/`)

- **Stack.** FastAPI + SQLAlchemy 2.0 on SQLite WAL (`OGK_DATABASE_URL`). Routers in `server/routers/` are the REST API v1, plus `ws.py` and `services/command_hub.py` for real-time commands.
- **Dashboard.** `server/routers/web.py` serves Jinja2 templates from `dashboard/templates/`; static files and plain JS come from `dashboard/static/` (no build step).
- **Auth** (`server/auth/`):
  - Argon2id passwords.
  - JWT session tokens carry a `jti`, and logout revokes it (`models/revoked_session.py`).
  - Double-submit CSRF on forms; slowapi rate limits.
  - Anti-IDOR helpers in `dependencies.py` (`get_child_for_parent`).
- **Roles.** `parent`, `child-view` and `admin`. A child-view session (started from `/child-view/start`) is scoped to a single child, read-only, and replaces the parent session.
- **Seed data.** `server/seeds/domain_catalog.json` is the categorised domain catalogue that `demo/seed_demo.py` and the tests rely on.

## UI work

`PRODUCT.md` and `.impeccable/` hold the dashboard's design context. The visual world is a calm mint-and-sage companion app (modelled on the lecturer's prototype screenshots): pale cool gradient ground, rounded white cards, a sage-green app bar, a left sidebar on desktop and a bottom tab bar on phones, amber for weekends, red only for destructive actions, Be Vietnam Pro throughout. Rules for changes:
- Keep the existing tokens in `dashboard/static/styles.css`.
- Put hover styles inside the `@media (hover: hover)` block.
- The UI must work at phone width (390 px).
- The child's tray dialogs (`agent/ui/tray_app.py`) share one look through `agent/ui/theme.py` (same colour values as the CSS tokens, pill buttons, no emoji). Add new dialogs with `make_window`/`PillButton` rather than raw Tk widgets.
