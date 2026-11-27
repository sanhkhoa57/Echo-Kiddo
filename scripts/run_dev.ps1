<#
.SYNOPSIS
    EC - Echo Kiddo - All-in-One Development & Lab Launcher
.DESCRIPTION
    Quick-launch script for Windows 10/11:
    - Auto-generates TLS certificates & seeds database
    - Starts EC Server with HTTPS
    - Starts EC Agent with Certificate Pinning
    - Starts EC Tray UI
    - Executes Clean Recovery or Tests
#>

param (
    [Parameter(Position=0)]
    [ValidateSet("setup", "server", "agent", "tray", "test", "benchmark", "cleanup", "all")]
    [string]$Action = "setup"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# Detect Python venv
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$UvicornExe = Join-Path $ProjectRoot ".venv\Scripts\uvicorn.exe"
$PytestExe = Join-Path $ProjectRoot ".venv\Scripts\pytest.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[!] Không tìm thấy môi trường ảo .venv tại $ProjectRoot" -ForegroundColor Red
    Write-Host "    Vui lòng tạo venv: python -m venv .venv và cài requirements.txt" -ForegroundColor Yellow
    exit 1
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       EC - Echo Kiddo - LAB & DEV HUB       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

switch ($Action) {
    "setup" {
        Write-Host ">>> Đang thiết lập môi trường Lab & sinh chứng chỉ TLS..." -ForegroundColor Green
        & $PythonExe "$ProjectRoot\scripts\setup_lab.py"
    }

    "server" {
        if (-not (Test-Path "$ProjectRoot\certs\server.crt")) {
            Write-Host ">>> Chưa có chứng chỉ TLS, tự động chạy setup..." -ForegroundColor Yellow
            & $PythonExe "$ProjectRoot\scripts\setup_lab.py"
        }
        Write-Host ">>> Khởi chạy EC Server HTTPS trên 0.0.0.0:8000..." -ForegroundColor Green
        & $UvicornExe server.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile certs/server.key --ssl-certfile certs/server.crt --reload
    }

    "agent" {
        $envFile = "$ProjectRoot\certs\ogk_lab.env"
        if (Test-Path $envFile) {
            Get-Content $envFile | ForEach-Object {
                if ($_ -match "^\s*([^#=]+)\s*=\s*(.*)$") {
                    [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2])
                }
            }
        }
        Write-Host ">>> Khởi chạy EC Agent Service (Standalone Mode)..." -ForegroundColor Green
        & $PythonExe -m agent.service.win_service run
    }

    "tray" {
        Write-Host ">>> Khởi chạy EC Tray UI (Giao diện khay hệ thống)..." -ForegroundColor Green
        & $PythonExe -m agent.ui.tray_app
    }

    "test" {
        Write-Host ">>> Chạy bộ kiểm thử tự động toàn diện..." -ForegroundColor Green
        & $PytestExe -v
    }

    "benchmark" {
        Write-Host ">>> Chạy đo lường hiệu năng M4..." -ForegroundColor Green
        & $PythonExe tests/benchmark_m4.py
    }

    "cleanup" {
        Write-Host ">>> Chạy công cụ hoàn nguyên và gỡ bỏ sạch sẽ..." -ForegroundColor Yellow
        & $PythonExe agent/cleanup/ogk_cleanup.py --force
    }

    "all" {
        Write-Host ">>> Thiết lập Lab và chạy toàn bộ kiểm thử..." -ForegroundColor Green
        & $PythonExe "$ProjectRoot\scripts\setup_lab.py"
        & $PytestExe -v
        & $PythonExe tests/benchmark_m4.py
    }
}
