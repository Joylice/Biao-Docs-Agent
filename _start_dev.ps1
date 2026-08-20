# 一键启动开发服务：uvicorn(8000) + arq worker（独立进程 + 日志文件）
$ErrorActionPreference = "Stop"
$backend = "d:\AI\WorkBuddy\2026-08-15-17-35-34\backend"
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"
$logs = Join-Path $backend "_logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# 1. 清理旧实例（仅限本项目服务进程；worker 实际以 -m worker.run_worker 启动）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn app\.main|worker\.run_worker" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# 2. 启动后端 API（--reload 热加载）
Start-Process -FilePath $venvPy -ArgumentList @(
    "-m", "uvicorn", "app.main:app",
    "--host", "0.0.0.0", "--port", "8000", "--reload"
) -WorkingDirectory $backend `
    -RedirectStandardOutput (Join-Path $logs "uvicorn.out.log") `
    -RedirectStandardError (Join-Path $logs "uvicorn.err.log") `
    -WindowStyle Hidden

# 3. 启动 Arq Worker（异步任务消费；Windows 下用 run_worker 切换 SelectorEventLoop）
Start-Process -FilePath $venvPy -ArgumentList @(
    "-m", "worker.run_worker", "worker.WorkerSettings"
) -WorkingDirectory $backend `
    -RedirectStandardOutput (Join-Path $logs "arq.out.log") `
    -RedirectStandardError (Join-Path $logs "arq.err.log") `
    -WindowStyle Hidden

Start-Sleep -Seconds 5

# 4. 验证
$health = "FAIL"
try { $r = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5; $health = $r.status } catch { $health = "FAIL: $_" }
Write-Output "HEALTH=$health"
Write-Output "--- uvicorn.err.log ---"
Get-Content (Join-Path $logs "uvicorn.err.log") -ErrorAction SilentlyContinue | Select-Object -Last 5
Write-Output "--- arq.out.log ---"
Get-Content (Join-Path $logs "arq.out.log") -ErrorAction SilentlyContinue | Select-Object -Last 5
Write-Output "--- arq.err.log ---"
Get-Content (Join-Path $logs "arq.err.log") -ErrorAction SilentlyContinue | Select-Object -Last 5
