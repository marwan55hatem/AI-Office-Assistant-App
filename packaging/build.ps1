# Builds the offline Windows installer: models -> tests -> PyInstaller -> Inno Setup.
# Usage (from anywhere):  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-SkipModels] [-SkipTests] [-NoInstaller]
param(
    [switch]$SkipModels,
    [switch]$SkipTests,
    [switch]$NoInstaller
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONIOENCODING = "utf-8"

function Step($name, [scriptblock]$body) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    & $body
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

if (-not $SkipModels) {
    Step "Fetch models" { python tools/fetch_models.py }
}
Step "Check models" { python tools/fetch_models.py --check }

if (-not $SkipTests) {
    Step "pytest" { python -m pytest tests/ -q }
    Step "Database self-test" { python database/db_manager.py }
}

Step "Application icon" { python tools/make_icon.py }

Step "PyInstaller" {
    Remove-Item -Recurse -Force build, dist\OfficeAssistant -ErrorAction SilentlyContinue
    pyinstaller packaging/OfficeAssistant.spec --noconfirm --clean
}

# The developer database must never be shipped.
$leaked = Get-ChildItem dist\OfficeAssistant -Recurse -Include *.db, *.bak -ErrorAction SilentlyContinue
if ($leaked) { throw "Database files found in the bundle: $($leaked.FullName -join ', ')" }

$size = (Get-ChildItem dist\OfficeAssistant -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ("Bundle: dist\OfficeAssistant  ({0:N1} GB)" -f $size)

# Load and run every bundled model inside the frozen app, with a throw-away data folder.
Write-Host "`n=== Frozen self-check ===" -ForegroundColor Cyan
$checkData = Join-Path $env:TEMP "OfficeAssistant-selfcheck"
Remove-Item -Recurse -Force $checkData -ErrorAction SilentlyContinue
$env:OFFICE_DATA_DIR = $checkData
$check = Start-Process dist\OfficeAssistant\OfficeAssistant.exe -ArgumentList "--self-check" -PassThru -Wait
Remove-Item Env:OFFICE_DATA_DIR
Select-String -Path "$checkData\logs\app.log" -Pattern "SELF-CHECK" | ForEach-Object { $_.Line }
if ($check.ExitCode -ne 0) { throw "Frozen self-check failed ($($check.ExitCode) checks) - see $checkData\logs\app.log" }

if ($NoInstaller) { return }

Step "Inno Setup" {
    $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $iscc = @("$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
                Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $iscc) { throw "Inno Setup 6 not found: winget install -e --id JRSoftware.InnoSetup" }
    & $iscc packaging\installer.iss
}

Get-ChildItem dist\installer | Format-Table Name, @{n = "MB"; e = { [int]($_.Length / 1MB) } }
Write-Host "Done: dist\installer" -ForegroundColor Green
