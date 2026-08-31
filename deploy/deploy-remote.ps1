# ============================================================
#  deploy-remote.ps1 - One-click deployment to test server (192.168.18.200)
#  Pipeline: build -> docker save -> gzip -> upload -> image load
#            -> retag latest -> compose up -> health check
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1
#    powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -Version 20260901
#    powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -SkipBuild
#    powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -InitInfra   # first-time only
#    powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -HealthOnly
# ============================================================
param(
    [string]$Version = "",      # image version tag; default = yyyyMMdd
    [switch]$SkipBuild,         # reuse existing local images
    [switch]$InitInfra,         # also package/upload/load infra images (pgvector/redis/minio)
    [switch]$HealthOnly,        # health check only
    [switch]$SkipCompose        # stop after load+retag (skip compose up)
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# ---------- helpers ----------
function Read-EnvFile($path) {
    $map = @{}
    if (-not (Test-Path $path)) { return $map }
    Get-Content $path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $idx = $line.IndexOf("=")
            $map[$line.Substring(0, $idx).Trim()] = $line.Substring($idx + 1).Trim()
        }
    }
    return $map
}

function Find-Python {
    if ($env:BID_PYTHON -and (Test-Path $env:BID_PYTHON)) { return $env:BID_PYTHON }
    $candidates = @(
        "C:\Users\$env:USERNAME\.workbuddy\binaries\python\envs\default\Scripts\python.exe",
        "C:\Users\24237\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $p = Get-Command python -ErrorAction SilentlyContinue
    if ($p) { return $p.Source }
    throw "Python not found. Set env BID_PYTHON or install python."
}

function Invoke-Check($cmd) {
    if ($LASTEXITCODE -ne 0) { throw "Step failed (exit $LASTEXITCODE): $cmd" }
}

function Wait-Health($url, $expectBody, $tries, $label) {
    for ($i = 0; $i -lt $tries; $i++) {
        Start-Sleep -Seconds 4
        try {
            $body = curl.exe --noproxy "*" -s --max-time 5 $url
            if ($expectBody) {
                if ($body -match $expectBody) { Write-Host "    $label OK ($url)" -ForegroundColor Green; return $true }
            } else {
                Write-Host "    $label OK ($url)" -ForegroundColor Green; return $true
            }
        } catch { }
        Write-Host "    $label not ready ($i+1/$tries)..." -ForegroundColor DarkGray
    }
    Write-Host "    $label TIMEOUT: $url" -ForegroundColor Red
    return $false
}

# ---------- config ----------
$remote = Read-EnvFile "deploy\.env.remote"
$prod   = Read-EnvFile "deploy\.env.prod"
$py     = Find-Python
$panelApi = Join-Path $PSScriptRoot "panel_api.py"

if (-not $Version) { $Version = Get-Date -Format "yyyyMMdd" }
$apiUrl  = $remote["API_HEALTH_URL"];  if (-not $apiUrl)  { $apiUrl = "http://192.168.18.200:18000/health" }
$webUrl  = $remote["WEB_URL"];         if (-not $webUrl)  { $webUrl  = "http://192.168.18.200:5173" }
$upDir   = $remote["REMOTE_UPLOAD_DIR"]; if (-not $upDir) { $upDir = "/opt" }
$cmpPath = $remote["REMOTE_COMPOSE"]
$cmpName = $remote["COMPOSE_NAME"];    if (-not $cmpName) { $cmpName = "deploy" }
$imgPre  = $remote["APP_IMAGE_PREFIX"]; if (-not $imgPre) { $imgPre = "bidagent" }
$tmpDir  = Join-Path $env:TEMP "bidagent_deploy_$Version"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

$imgBackend = "$imgPre-backend"
$imgWeb     = "$imgPre-web"

Write-Host "=== Test-Env Deploy v$Version ===" -ForegroundColor Cyan

# ---------- health only ----------
if ($HealthOnly) {
    $ok1 = Wait-Health $apiUrl "ok" 10 "API"
    $ok2 = Wait-Health $webUrl "" 5 "Web"
    if (-not ($ok1 -and $ok2)) { exit 1 }
    Write-Host "Health check passed." -ForegroundColor Green
    exit 0
}

# ---------- 0. panel session ----------
Write-Host "[0/8] Verify 1Panel session..." -ForegroundColor Cyan
& $py $panelApi health-check
if ($LASTEXITCODE -ne 0) {
    throw "1Panel session invalid. Set PANEL_API_KEY or refresh PANEL_COOKIES in deploy\.env.remote"
}

# ---------- 1. build ----------
if (-not $SkipBuild) {
    Write-Host "[1/8] Building images ($imgBackend`:$Version / $imgWeb`:$Version)..." -ForegroundColor Cyan
    docker build -t "$imgBackend`:$Version" -t "$imgBackend`:latest" backend
    Invoke-Check "docker build backend"
    docker build -t "$imgWeb`:$Version" -t "$imgWeb`:latest" frontend
    Invoke-Check "docker build frontend"
} else {
    Write-Host "[1/8] Skip build (reuse local images)..." -ForegroundColor Cyan
    docker image inspect "$imgBackend`:$Version" > $null 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    Image $imgBackend`:$Version not found; falling back to :latest" -ForegroundColor Yellow
        $Version = "latest"
    }
}

# ---------- 2. package ----------
$appTar = Join-Path $tmpDir "app_$Version.tar"
$appGz  = Join-Path $tmpDir "app_$Version.tar.gz"
Write-Host "[2/8] docker save app images -> gzip..." -ForegroundColor Cyan
docker save -o $appTar "$imgBackend`:$Version" "$imgWeb`:$Version"
Invoke-Check "docker save app"
& $py -c "import gzip,shutil,os; shutil.copyfileobj(open(r'$appTar','rb'), gzip.open(r'$appGz','wb')); os.remove(r'$appTar')"
Write-Host "    $appGz ($([math]::Round((Get-Item $appGz).Length/1MB)) MB)" -ForegroundColor Green

$infraGz = ""
if ($InitInfra) {
    $infraTar = Join-Path $tmpDir "infra.tar"
    $infraGz  = Join-Path $tmpDir "infra.tar.gz"
    Write-Host "    [InitInfra] docker save infra images..." -ForegroundColor Yellow
    docker save -o $infraTar `
        "docker.1ms.run/pgvector/pgvector:pg16" `
        "docker.1ms.run/redis:7-alpine" `
        "docker.1ms.run/minio/minio:RELEASE.2024-02-26T09-33-48Z"
    Invoke-Check "docker save infra"
    & $py -c "import gzip,shutil,os; shutil.copyfileobj(open(r'$infraTar','rb'), gzip.open(r'$infraGz','wb')); os.remove(r'$infraTar')"
    Write-Host "    $infraGz ($([math]::Round((Get-Item $infraGz).Length/1MB)) MB)" -ForegroundColor Green
}

# ---------- 3. upload ----------
Write-Host "[3/8] Upload bundle(s)..." -ForegroundColor Cyan
& $py $panelApi upload $appGz $upDir
if ($LASTEXITCODE -ne 0) { throw "upload app bundle failed" }
$appRemote = "$upDir/app_$Version.tar.gz"
if ($InitInfra) {
    & $py $panelApi upload $infraGz $upDir
    if ($LASTEXITCODE -ne 0) { throw "upload infra bundle failed" }
}

# ---------- 4. load ----------
Write-Host "[4/8] Load image(s) on server..." -ForegroundColor Cyan
& $py $panelApi load $appRemote
if ($LASTEXITCODE -ne 0) { throw "load app bundle failed" }
if ($InitInfra) {
    & $py $panelApi load "$upDir/infra.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw "load infra bundle failed" }
}

# ---------- 5. retag latest ----------
Write-Host "[5/8] Retag :$Version -> :latest (compose uses latest)..." -ForegroundColor Cyan
& $py $panelApi tag "$imgBackend`:$Version" "$imgBackend`:latest"
& $py $panelApi tag "$imgWeb`:$Version" "$imgWeb`:latest"

# ---------- 6. compose up ----------
if (-not $SkipCompose) {
    Write-Host "[6/8] Compose validate + up..." -ForegroundColor Cyan
    $testOut = & $py $panelApi compose-test --name $cmpName --path $cmpPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($testOut -match "记录已存在|ErrRecordExist") {
            Write-Host "    compose-test skipped (record exists; normal for iteration)" -ForegroundColor Yellow
        } else {
            Write-Host $testOut -ForegroundColor Red
            throw "compose validate failed"
        }
    }
    & $py $panelApi compose-up --name $cmpName --path $cmpPath
    if ($LASTEXITCODE -ne 0) { throw "compose up failed" }
    Write-Host "    compose up triggered (async)." -ForegroundColor Green
} else {
    Write-Host "[6/8] Skip compose (use 1Panel UI or run again without -SkipCompose)..." -ForegroundColor Cyan
}

# ---------- 7. wait for containers ----------
Write-Host "[7/8] Waiting for containers..." -ForegroundColor Cyan
Start-Sleep -Seconds 30
& $py $panelApi containers "deploy"
if ($LASTEXITCODE -ne 0) { Write-Host "    container list check failed" -ForegroundColor Yellow }

# ---------- 8. health check ----------
Write-Host "[8/8] Health check..." -ForegroundColor Cyan
$ok1 = Wait-Health $apiUrl "ok" 15 "API"
$ok2 = Wait-Health $webUrl "" 5 "Web"
if (-not ($ok1 -and $ok2)) {
    Write-Host "!!! Deployment FAILED health check." -ForegroundColor Red
    Write-Host "    Check logs: 1Panel -> 容器 -> deploy-api-1 -> 日志"
    Write-Host "    Rollback  : deploy\REMOTE-DEPLOY.md 章节 [回滚]"
    exit 1
}

Write-Host ""
Write-Host "=== Deploy v$Version DONE ===" -ForegroundColor Green
Write-Host "  Web : $webUrl"
Write-Host "  API : $apiUrl"
Write-Host "  Tags kept on server: $imgBackend`:$Version (rollback target)"
Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
