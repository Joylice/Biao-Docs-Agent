# 修复 git 上游跟踪引用（refs/remotes/origin/master）丢失/失效问题
# 背景：8-26 两次 push 前均发现 git fetch/update-ref 写入 refs/remotes 异常（目录为空），
#        push 报 "upstream 丢失/not found"；当时手动 mkdir + printf 写入引用后恢复。
#        本脚本固化该操作：远端读取真实 SHA -> 本地引用比对 -> 缺失/过期时重建。
# 用法：
#   powershell -ExecutionPolicy Bypass -File deploy\repair-upstream.ps1
# 适用场景：git status / git push 提示 upstream 缺失或与远端不一致，
#           且 git fetch 后 refs/remotes/origin/master 仍未恢复时。
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$remote = "origin"
$branch = "master"
$refPath = ".git\refs\remotes\$remote\$branch"

# 1. 读取远端实际 SHA（只读操作，不修改远端）
$ls = git ls-remote $remote "refs/heads/$branch"
if ($LASTEXITCODE -ne 0) { throw "ls-remote 失败：无法访问远端 $remote（检查 SSH/网络）" }
$remoteSha = ($ls -split "\s+")[0]
if (-not $remoteSha) { throw "远端不存在分支 refs/heads/$branch" }

# 2. 本地引用比对（loose ref 优先于 packed-refs，直接读文件即可；缺失时按失效处理）
$refFile = Join-Path $root $refPath
$localSha = ""
if (Test-Path $refFile) {
    $localSha = (Get-Content $refFile -Raw).Trim()
}
if ($localSha -eq $remoteSha) {
    Write-Host "upstream 引用正常：$remote/$branch = $remoteSha（无需修复）" -ForegroundColor Green
    exit 0
}
if ($localSha) {
    Write-Host "upstream 引用过期：本地 $localSha -> 远端 $remoteSha" -ForegroundColor Yellow
} else {
    Write-Host "upstream 引用缺失：$refPath（8-26 手工修复同类问题）" -ForegroundColor Yellow
}

# 3. 重建引用目录 + 写入（等效手动 mkdir + printf）
New-Item -ItemType Directory -Force -Path (Split-Path $refFile) | Out-Null
Set-Content -Path $refFile -Value $remoteSha -NoNewline -Encoding Ascii
Write-Host "已写入 $refPath = $remoteSha" -ForegroundColor Green

# 4. 验证：show-ref 与 status 均正常即修复完成
git show-ref --verify "refs/remotes/$remote/$branch"
if ($LASTEXITCODE -ne 0) { throw "引用写入后 show-ref 验证失败" }
Write-Host "upstream 修复完成 ✓（后续 git push 可直接使用 origin $branch）" -ForegroundColor Green
