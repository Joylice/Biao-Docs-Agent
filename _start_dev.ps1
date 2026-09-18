# 一键启动开发服务：uvicorn(8000) + arq worker（独立进程 + 日志文件）
$ErrorActionPreference = "Stop"

# 相对路径化：基于脚本所在目录解析，兼容任意安装位置
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$backend = Join-Path $scriptDir "backend"
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"
$logs = Join-Path $backend "_logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# 1. 清理旧实例（仅限本项目服务进程；worker 实际以 -m worker.run_worker 启动）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn\.run|app\.main:app|worker\.run_worker" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
# 1b. 兜底清理 --reload 孤儿子进程：父进程被杀后 multiprocessing spawn 子进程仍监听 8000，
#     命令行不含 uvicorn 字样，上面的匹配杀不掉，按端口持有者补杀。
#     （netstat 不在 PATH 的异常机器上跳过，不阻塞启动）
$portPids = @()
try {
    $portPids = (netstat -ano | Select-String ":8000\s.*LISTENING" |
        ForEach-Object { ($_ -split '\s+')[-1] }) | Sort-Object -Unique
} catch { Write-Output "WARN: netstat unavailable, skip port cleanup" }
foreach ($p in $portPids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# 2. 启动后端 API 与 Arq Worker：
#    uvicorn 0.52 在 Windows 上不再走 set_event_loop_policy，必须通过 loop= 参数
#    显式传 SelectorEventLoop 工厂，否则 psycopg3 异步连接池报 ProactorEventLoop 错。
#    worker 自身在 run_worker.py 中已设置 WindowsSelectorEventLoopPolicy，直接 -m 启动即可。
function Start-AppProcess {
    param([string[]]$ArgList, [string]$Tag, [string]$OutLog, [string]$ErrLog)
    try {
        Start-Process -FilePath $venvPy -ArgumentList $ArgList -WorkingDirectory $backend `
            -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog `
            -WindowStyle Hidden | Out-Null
        Write-Output "STARTED $Tag (Start-Process)"
    } catch {
        Write-Output "WARN: $Tag Start-Process 失败（$($_.Exception.Message)），降级 Process.Start"
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $venvPy
        $psi.Arguments = ($ArgList -join ' ')
        $psi.WorkingDirectory = $backend
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $p = [System.Diagnostics.Process]::Start($psi)
        Write-Output "STARTED $Tag (Process.Start) pid=$($p.Id)"
    }
}

# uvicorn: 用 -c 内联脚本启动，通过 loop= 传 SelectorEventLoop 工厂
$uvicornScript = @"
import asyncio, selectors
import uvicorn
uvicorn.run(app='app.main:app', host='0.0.0.0', port=8000, loop=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
"@
Start-AppProcess @("-c", $uvicornScript) `
    "uvicorn" (Join-Path $logs "uvicorn.out.log") (Join-Path $logs "uvicorn.err.log")
Start-AppProcess @("-m", "worker.run_worker", "worker.WorkerSettings") `
    "worker" (Join-Path $logs "arq.out.log") (Join-Path $logs "arq.err.log")

Start-Sleep -Seconds 5

# 4. 验证
$health = "FAIL"
try { $r = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5; $health = $r.status } catch { $health = "FAIL: $_" }
Write-Output "HEALTH=$health"
Write-Output "--- alive processes ---"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn\.run|app\.main:app|worker\.run_worker" } |
    ForEach-Object { Write-Output "ALIVE pid=$($_.ProcessId) $($_.CommandLine -replace '.*python\.exe\s+','-m ')" }
