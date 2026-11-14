$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskOllama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (!(Test-Path -LiteralPath $taskPython)) { throw 'Create the project .venv and install requirements first.' }
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'artifacts') -Force | Out-Null
try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null }
catch {
    if (!(Test-Path -LiteralPath $taskOllama)) { throw 'Install Ollama before starting the local model.' }
    Start-Process -FilePath $taskOllama -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput 'artifacts\ollama.stdout.log' -RedirectStandardError 'artifacts\ollama.stderr.log' | Out-Null
    $taskReady = $false
    for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
        try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 1 | Out-Null; $taskReady = $true; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (!$taskReady) { throw 'Ollama did not start. Check artifacts/ollama.stderr.log.' }
}
# Leave the application in the foreground so Ctrl+C cleanly stops its web server.
& $taskPython -m uvicorn main:app --host 0.0.0.0 --port 8000
