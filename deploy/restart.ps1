# 一键重启脚本：应用最新配置 → 重启全部容器 → 健康检查
# 用法：
#   powershell -ExecutionPolicy Bypass -File deploy\restart.ps1        # 仅重启（复用现有镜像）
#   powershell -ExecutionPolicy Bypass -File deploy\restart.ps1 -Build # 先重建 api/worker/web 镜像再重启
# 提示：git push 报 upstream 丢失/失效时，先跑 deploy\repair-upstream.ps1 修复跟踪引用（本脚本不涉及 git）。
param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Build) {
    Write-Host "[1/4] 重建镜像（api/worker/web）..." -ForegroundColor Cyan
    docker compose -f deploy/docker-compose.yml build api worker web
    if ($LASTEXITCODE -ne 0) { throw "镜像构建失败" }
} else {
    Write-Host "[1/4] 复用现有镜像..." -ForegroundColor Cyan
}

Write-Host "[2/4] 重启全部容器（应用 compose 配置变更）..." -ForegroundColor Cyan
docker compose -f deploy/docker-compose.yml up -d --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "容器启动失败" }

# api/worker 被 recreate 后容器 IP 可能变化，而 nginx 启动时缓存上游域名解析（api），
# 不重启 web 会导致 502 Bad Gateway（登录/全部 API 请求失败）。
Write-Host "    [2.1] 重启 web（刷新 nginx 上游解析，防 502）..." -ForegroundColor Cyan
docker compose -f deploy/docker-compose.yml restart web
if ($LASTEXITCODE -ne 0) { throw "web 重启失败" }

Write-Host "[3/4] 等待服务就绪..." -ForegroundColor Cyan
$apiOk = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 3
        if ($health.status -eq "ok") { $apiOk = $true; break }
    } catch { }
}
if (-not $apiOk) { throw "API 未在 60 秒内就绪" }
Write-Host "    API 就绪: http://localhost:8000/health -> ok" -ForegroundColor Green

$webOk = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 3 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $webOk = $true; break }
    } catch { }
}
if (-not $webOk) { throw "Web 未在 30 秒内就绪" }
Write-Host "    Web 就绪: http://localhost:5173" -ForegroundColor Green

Write-Host "[4/4] 容器状态:" -ForegroundColor Cyan
docker ps --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"
Write-Host "一键重启完成 ✓" -ForegroundColor Green
