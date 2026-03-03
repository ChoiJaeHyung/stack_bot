# daemon_wrapper.ps1 - bot_brain.py 단발 실행을 10초 간격으로 반복
# Python은 stdout/stderr를 내부적으로 devnull로 리다이렉트하므로
# 콘솔 출력이 없음. 파이프/리다이렉트 불필요.
#
# 시작: _restart_daemon.ps1이 이 스크립트를 WindowStyle Minimized로 실행
# 종료: _kill_bot.ps1 또는 작업 관리자에서 powershell 종료

$ErrorActionPreference = "Continue"

$ProjectDir  = $PSScriptRoot
$PythonExe   = "C:\Users\jhchoi\AppData\Local\Python\pythoncore-3.14-64\python.exe"  # Full path to avoid PATH issues
if (-not $PythonExe) { $PythonExe = "python" }
$Script      = "bot_brain.py"
$LogFile     = Join-Path $ProjectDir "bot_daemon.log"
$Interval    = 10  # 폴링 간격 (초)

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [wrapper] $msg"
    try {
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    } catch {}
}

Set-Location $ProjectDir
Write-Log "=== Daemon wrapper started (PID=$PID, interval=${Interval}s) ==="

$cycle = 0

while ($true) {
    $cycle++

    try {
        # Python 직접 실행 (출력 없음 - Python 내부에서 devnull 처리)
        & $PythonExe -u $Script
        $ec = $LASTEXITCODE

        if ($null -ne $ec -and $ec -ne 0) {
            Write-Log "bot_brain.py exited with code $ec (cycle=$cycle)"
            # Clean up stale working lock after crash
            $workingJson = Join-Path $ProjectDir "working.json"
            if (Test-Path $workingJson) {
                Remove-Item $workingJson -Force -ErrorAction SilentlyContinue
                Write-Log "Cleaned up working.json after crash"
            }
        }

    } catch {
        Write-Log "ERROR: $($_.Exception.Message)"
    }

    # 다음 폴링까지 대기
    Start-Sleep -Seconds $Interval
}
