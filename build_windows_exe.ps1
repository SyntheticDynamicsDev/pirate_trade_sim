$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "No .venv found. Creating one..."
    Invoke-Checked "py" "-3" "-m" "venv" ".venv"
}

Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "--upgrade" "pip"
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "-r" "requirements-dev.txt"
Invoke-Checked ".venv\Scripts\python.exe" "tools\make_icon.py"

Invoke-Checked ".venv\Scripts\python.exe" "-m" "PyInstaller" `
    --noconfirm `
    --clean `
    --windowed `
    --contents-directory "." `
    --icon "assets\app_icon_level.ico" `
    --name "Pirate Trade" `
    --add-data "assets;assets" `
    --add-data "content;content" `
    main.py

Write-Host ""
Write-Host "Build complete: dist\Pirate Trade\Pirate Trade.exe"
Write-Host "To build a classic installer, run: .\build_windows_setup.ps1"
