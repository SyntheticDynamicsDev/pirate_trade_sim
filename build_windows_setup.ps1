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

Write-Host "Building Pirate Trade game bundle..."
Invoke-Checked "powershell" "-ExecutionPolicy" "Bypass" "-File" ".\build_windows_exe.ps1"

$iscc = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
if (-not $iscc) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            $iscc = Get-Item $candidate
            break
        }
    }
}

if (-not $iscc) {
    throw "Inno Setup 6 was not found. Install it from https://jrsoftware.org/isinfo.php, then run this script again."
}

$isccPath = $iscc.Source
if (-not $isccPath) {
    $isccPath = $iscc.FullName
}

Write-Host "Building Windows installer..."
Invoke-Checked $isccPath ".\installer\PirateTrade.iss"

Write-Host ""
Write-Host "Installer complete:"
Write-Host "installer_output\PirateTradeSetup-0.1.0.exe"
