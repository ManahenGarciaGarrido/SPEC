<#
.SYNOPSIS
    Read-only check of the development prerequisites on Windows.

.DESCRIPTION
    Installs nothing and changes nothing. It only runs version commands
    (rustc --version, node --version, ...), reads registry values and queries
    WMI/CIM. Compatible with Windows PowerShell 5.1 and PowerShell 7.

    Exit code: 0 when every required item is present, 1 otherwise,
    2 when not running on Windows.

.PARAMETER Json
    Print the results as JSON (handy to paste them into a conversation).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1 -Json
#>
[CmdletBinding()]
param(
    [switch]$Json
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Continue'

# rustup proxies (rustc, cargo) may auto-install a missing toolchain; this
# script must never install anything. Process-scoped: the user's environment
# is untouched.
$env:RUSTUP_AUTO_INSTALL = '0'

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    Write-Error 'Este script solo funciona en Windows.'
    exit 2
}

# Minimum versions (verified on 2026-10-04, see docs/PLAN.md section 3).
$MinRust = [version]'1.90.0'     # MSRV of tauri 2.12.1
$MinNode = [version]'22.12.0'    # required by Vite 8
$RecommendedNodeMajor = 24       # current LTS line
$TargetPython = '3.12'
$MinFreeDiskGB = 30              # build caches + a ~20 GB GGUF

$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [Parameter(Mandatory)] [string]$Item,
        [Parameter(Mandatory)] [ValidateSet('OK', 'FALTA', 'AVISO', 'INFO')] [string]$Status,
        [string]$Detail = '',
        [string]$Hint = '',
        [bool]$Required = $true
    )
    $results.Add([pscustomobject]@{
            Item     = $Item
            Status   = $Status
            Detail   = $Detail
            Hint     = $Hint
            Required = $Required
        })
}

# Runs an external command and returns its first output line and exit code.
# Returns $null when the command is not on PATH.
function Invoke-Probe {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [string[]]$Arguments = @('--version')
    )
    $cmd = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { return $null }
    # The Microsoft Store "App Execution Alias" stubs are not real installs.
    if ($cmd.Source -like '*\WindowsApps\*') { return $null }
    try {
        $output = & $cmd.Source @Arguments 2>&1
        $code = $LASTEXITCODE
    }
    catch {
        return [pscustomobject]@{ Text = [string]$_; ExitCode = -1; Path = $cmd.Source; Lines = @() }
    }
    $lines = @($output | ForEach-Object { [string]$_ } | Where-Object { $_.Trim() -ne '' })
    $first = ''
    if ($lines.Count -gt 0) { $first = $lines[0].Trim() }
    return [pscustomobject]@{ Text = $first; ExitCode = $code; Path = $cmd.Source; Lines = $lines }
}

function Get-VersionFromText {
    param([string]$Text, [string]$Pattern = '(\d+)\.(\d+)\.(\d+)')
    if (-not $Text) { return $null }
    $m = [regex]::Match($Text, $Pattern)
    if (-not $m.Success) { return $null }
    return [version]('{0}.{1}.{2}' -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value)
}

function Get-RegistryValue {
    param([Parameter(Mandatory)] [string]$Path, [Parameter(Mandatory)] [string]$Name)
    try {
        $item = Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop
        return $item.$Name
    }
    catch {
        return $null
    }
}

# --- Operating system ------------------------------------------------------
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$build = [int]$os.BuildNumber
$arch = $env:PROCESSOR_ARCHITECTURE
$osDetail = '{0} (build {1}, {2})' -f $os.Caption, $build, $arch
if ($build -ge 17763 -and $arch -eq 'AMD64') {
    Add-Result -Item 'Windows' -Status 'OK' -Detail $osDetail
}
else {
    Add-Result -Item 'Windows' -Status 'FALTA' -Detail $osDetail -Hint 'Se necesita Windows 10 1809 o posterior, x64.'
}

# --- Hardware (informational; drives the suggested profile) ---------------
$ramGB = [math]::Round((Get-CimInstance -ClassName Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
Add-Result -Item 'RAM' -Status 'INFO' -Detail ('{0} GB' -f $ramGB) -Required $false

$videoNames = @(Get-CimInstance -ClassName Win32_VideoController | ForEach-Object { $_.Name })
Add-Result -Item 'Gráficas' -Status 'INFO' -Detail ($videoNames -join '; ') -Required $false

$vramGB = 0
$smi = Invoke-Probe -Name 'nvidia-smi' -Arguments @('--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits')
if ($smi -and $smi.ExitCode -eq 0 -and $smi.Text) {
    $parts = $smi.Text.Split(',') | ForEach-Object { $_.Trim() }
    if ($parts.Count -ge 3) {
        $vramGB = [math]::Round([double]$parts[1] / 1024, 1)
        $detail = '{0}, {1} GB VRAM, driver {2}' -f $parts[0], $vramGB, $parts[2]
        $driver = Get-VersionFromText -Text ($parts[2] + '.0') -Pattern '(\d+)\.(\d+)\.(\d+)'
        if ($driver -and $driver -lt [version]'551.61.0') {
            Add-Result -Item 'GPU NVIDIA' -Status 'AVISO' -Detail $detail -Hint 'El build CUDA 12.4 de llama.cpp necesita driver >= 551.61.' -Required $false
        }
        else {
            Add-Result -Item 'GPU NVIDIA' -Status 'OK' -Detail $detail -Required $false
        }
    }
    else {
        Add-Result -Item 'GPU NVIDIA' -Status 'AVISO' -Detail $smi.Text -Required $false
    }
}
else {
    Add-Result -Item 'GPU NVIDIA' -Status 'INFO' -Detail 'nvidia-smi no disponible (sin GPU NVIDIA o sin driver)' -Required $false
}

if ($vramGB -ge 7 -and $ramGB -ge 28) { $suggestedProfile = 'gpu-hibrido' }
elseif ($vramGB -ge 7) { $suggestedProfile = 'gpu-pequeno' }
else { $suggestedProfile = 'cpu' }
Add-Result -Item 'Perfil sugerido' -Status 'INFO' -Detail $suggestedProfile -Required $false

# --- Rust ------------------------------------------------------------------
$rustc = Invoke-Probe -Name 'rustc'
$rustVersion = $null
if ($rustc) { $rustVersion = Get-VersionFromText -Text $rustc.Text }
if (-not $rustVersion) {
    Add-Result -Item 'Rust (rustc)' -Status 'FALTA' -Hint 'Instala rustup desde https://rustup.rs (toolchain stable MSVC).'
}
elseif ($rustVersion -lt $MinRust) {
    Add-Result -Item 'Rust (rustc)' -Status 'FALTA' -Detail $rustc.Text -Hint ('Se necesita >= {0}: rustup update stable' -f $MinRust)
}
else {
    Add-Result -Item 'Rust (rustc)' -Status 'OK' -Detail $rustc.Text
}

$rustup = Invoke-Probe -Name 'rustup' -Arguments @('show', 'active-toolchain')
if (-not $rustup) {
    Add-Result -Item 'Toolchain MSVC' -Status 'AVISO' -Detail 'rustup no encontrado' -Hint 'Se recomienda gestionar Rust con rustup.'
}
elseif ($rustup.Text -match 'x86_64-pc-windows-msvc') {
    Add-Result -Item 'Toolchain MSVC' -Status 'OK' -Detail $rustup.Text
}
else {
    Add-Result -Item 'Toolchain MSVC' -Status 'FALTA' -Detail $rustup.Text -Hint 'rustup default stable-x86_64-pc-windows-msvc'
}

# --- MSVC Build Tools and Windows SDK --------------------------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vcPath = $null
if (Test-Path $vswhere) {
    $vcPath = & $vswhere -latest -products '*' -requires 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64' -property installationPath 2>$null |
        Select-Object -First 1
    $vcName = & $vswhere -latest -products '*' -requires 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64' -property displayName 2>$null |
        Select-Object -First 1
}
if ($vcPath) {
    Add-Result -Item 'MSVC (C++ Build Tools)' -Status 'OK' -Detail ('{0} en {1}' -f $vcName, $vcPath)
}
else {
    Add-Result -Item 'MSVC (C++ Build Tools)' -Status 'FALTA' -Hint 'Visual Studio Build Tools con la carga "Desarrollo para el escritorio con C++".'
}

$sdkVersion = Get-RegistryValue -Path 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Microsoft SDKs\Windows\v10.0' -Name 'ProductVersion'
if (-not $sdkVersion) {
    $sdkVersion = Get-RegistryValue -Path 'HKLM:\SOFTWARE\Microsoft\Microsoft SDKs\Windows\v10.0' -Name 'ProductVersion'
}
if ($sdkVersion) {
    Add-Result -Item 'Windows SDK' -Status 'OK' -Detail $sdkVersion
}
else {
    Add-Result -Item 'Windows SDK' -Status 'FALTA' -Hint 'Se instala con la carga de C++ de Visual Studio Build Tools.'
}

# --- WebView2 Runtime ------------------------------------------------------
$webviewGuid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
$webviewKeys = @(
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$webviewGuid",
    "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$webviewGuid",
    "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$webviewGuid"
)
$webviewVersion = $null
foreach ($key in $webviewKeys) {
    $pv = Get-RegistryValue -Path $key -Name 'pv'
    if ($pv -and $pv -ne '0.0.0.0') { $webviewVersion = $pv; break }
}
if ($webviewVersion) {
    Add-Result -Item 'WebView2 Runtime' -Status 'OK' -Detail $webviewVersion
}
else {
    Add-Result -Item 'WebView2 Runtime' -Status 'FALTA' -Hint 'Instala el "Evergreen Runtime" de Microsoft Edge WebView2.'
}

# --- Node.js ---------------------------------------------------------------
$node = Invoke-Probe -Name 'node'
$nodeVersion = $null
if ($node) { $nodeVersion = Get-VersionFromText -Text $node.Text }
if (-not $nodeVersion) {
    Add-Result -Item 'Node.js' -Status 'FALTA' -Hint ('Instala Node.js {0} LTS.' -f $RecommendedNodeMajor)
}
elseif ($nodeVersion -lt $MinNode) {
    Add-Result -Item 'Node.js' -Status 'FALTA' -Detail $node.Text -Hint ('Vite 8 necesita >= {0}; recomendado {1} LTS.' -f $MinNode, $RecommendedNodeMajor)
}
elseif ($nodeVersion.Major -lt $RecommendedNodeMajor) {
    Add-Result -Item 'Node.js' -Status 'OK' -Detail $node.Text -Hint ('Funciona; recomendado {0} LTS.' -f $RecommendedNodeMajor)
}
else {
    Add-Result -Item 'Node.js' -Status 'OK' -Detail $node.Text
}

$npm = Invoke-Probe -Name 'npm.cmd'
if ($npm -and $npm.Text) {
    Add-Result -Item 'npm' -Status 'OK' -Detail $npm.Text
}
else {
    Add-Result -Item 'npm' -Status 'FALTA' -Hint 'Se instala con Node.js.'
}

# --- uv and Python ---------------------------------------------------------
$uv = Invoke-Probe -Name 'uv'
if ($uv -and $uv.ExitCode -eq 0) {
    Add-Result -Item 'uv' -Status 'OK' -Detail $uv.Text
}
else {
    Add-Result -Item 'uv' -Status 'FALTA' -Hint 'winget install --id=astral-sh.uv -e   (instalación de usuario)'
}

# "py -0p" only lists installed runtimes. Launching "py -3.12" could make the
# new Python install manager download a missing runtime.
$pythonDetail = $null
$py = Invoke-Probe -Name 'py' -Arguments @('-0p')
if ($py -and $py.ExitCode -eq 0) {
    $pyLine = $py.Lines | Where-Object { $_ -match "(^|[^\d.])$([regex]::Escape($TargetPython))([^\d]|$)" } | Select-Object -First 1
    if ($pyLine) { $pythonDetail = '{0} (lanzador py)' -f $pyLine.Trim() }
}
if (-not $pythonDetail -and $uv -and $uv.ExitCode -eq 0) {
    $uvPy = Invoke-Probe -Name 'uv' -Arguments @('python', 'find', $TargetPython)
    if ($uvPy -and $uvPy.ExitCode -eq 0 -and $uvPy.Text) {
        $pythonDetail = '{0} (gestionado por uv)' -f $uvPy.Text
    }
}
# Only when there is no "py": with the install manager, "python" is an alias
# that could also trigger an install.
if (-not $pythonDetail -and -not $py) {
    $python = Invoke-Probe -Name 'python'
    if ($python -and $python.ExitCode -eq 0 -and $python.Text -match "^Python $([regex]::Escape($TargetPython))\.\d+") {
        $pythonDetail = '{0} ({1})' -f $python.Text, $python.Path
    }
}
if ($pythonDetail) {
    Add-Result -Item ('Python {0}' -f $TargetPython) -Status 'OK' -Detail $pythonDetail
}
elseif ($uv -and $uv.ExitCode -eq 0) {
    Add-Result -Item ('Python {0}' -f $TargetPython) -Status 'AVISO' -Detail 'No encontrado' -Hint ('uv puede instalarlo a nivel de usuario: uv python install {0}' -f $TargetPython)
}
else {
    Add-Result -Item ('Python {0}' -f $TargetPython) -Status 'FALTA' -Hint ('Instala uv y luego: uv python install {0}' -f $TargetPython)
}

# --- Git -------------------------------------------------------------------
$git = Invoke-Probe -Name 'git'
if ($git -and $git.ExitCode -eq 0) {
    Add-Result -Item 'Git' -Status 'OK' -Detail $git.Text
}
else {
    Add-Result -Item 'Git' -Status 'FALTA' -Hint 'Instala Git for Windows.'
}

# --- Optional items --------------------------------------------------------
$devMode = Get-RegistryValue -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name 'AllowDevelopmentWithoutDevLicense'
if ($devMode -eq 1) {
    Add-Result -Item 'Modo de desarrollador' -Status 'OK' -Detail 'Activado (los tests de symlinks se ejecutarán)' -Required $false
}
else {
    Add-Result -Item 'Modo de desarrollador' -Status 'AVISO' -Detail 'Desactivado' -Hint 'Opcional: sin él, los tests de enlaces simbólicos se saltan (los de junctions no).' -Required $false
}

$longPaths = Get-RegistryValue -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name 'LongPathsEnabled'
if ($longPaths -eq 1) {
    Add-Result -Item 'Rutas largas' -Status 'OK' -Detail 'LongPathsEnabled = 1' -Required $false
}
else {
    Add-Result -Item 'Rutas largas' -Status 'INFO' -Detail 'Desactivadas' -Hint 'Opcional; ayuda con rutas profundas al compilar.' -Required $false
}

$dataDrive = (Split-Path -Qualifier $env:LOCALAPPDATA).TrimEnd(':')
$drive = Get-PSDrive -Name $dataDrive -ErrorAction SilentlyContinue
if ($drive) {
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    $diskDetail = '{0} GB libres en {1}:' -f $freeGB, $dataDrive
    if ($freeGB -ge $MinFreeDiskGB) {
        Add-Result -Item 'Disco libre' -Status 'OK' -Detail $diskDetail -Required $false
    }
    else {
        Add-Result -Item 'Disco libre' -Status 'AVISO' -Detail $diskDetail -Hint ('Recomendado >= {0} GB (compilación + modelo GGUF).' -f $MinFreeDiskGB) -Required $false
    }
}

$sandboxExe = Join-Path $env:windir 'System32\WindowsSandbox.exe'
if (Test-Path $sandboxExe) {
    Add-Result -Item 'Windows Sandbox' -Status 'OK' -Detail 'Disponible (para la prueba sin conexión de la Fase 6)' -Required $false
}
elseif ($os.Caption -match 'Pro|Enterprise|Education') {
    Add-Result -Item 'Windows Sandbox' -Status 'INFO' -Detail 'No activado' -Hint 'Tu edición lo admite; se activa en "Características de Windows" cuando lleguemos a la Fase 6.' -Required $false
}
else {
    Add-Result -Item 'Windows Sandbox' -Status 'INFO' -Detail ('No disponible en {0}' -f $os.Caption) -Hint 'Para la Fase 6 hará falta una VM sin red.' -Required $false
}

# --- Output ----------------------------------------------------------------
$missing = @($results | Where-Object { $_.Required -and $_.Status -eq 'FALTA' })

if ($Json) {
    $results | ConvertTo-Json -Depth 3
}
else {
    Write-Host ''
    Write-Host 'Requisitos de desarrollo (comprobación de solo lectura)' -ForegroundColor Cyan
    Write-Host ''
    foreach ($r in $results) {
        switch ($r.Status) {
            'OK' { $color = 'Green' }
            'FALTA' { $color = 'Red' }
            'AVISO' { $color = 'Yellow' }
            default { $color = 'Gray' }
        }
        Write-Host ('[{0,-5}] {1,-24} {2}' -f $r.Status, $r.Item, $r.Detail) -ForegroundColor $color
        if ($r.Hint) { Write-Host ('        -> {0}' -f $r.Hint) -ForegroundColor DarkGray }
    }
    Write-Host ''
    if ($missing.Count -eq 0) {
        Write-Host 'Todo lo obligatorio está presente.' -ForegroundColor Green
    }
    else {
        Write-Host ('Faltan {0} requisito(s) obligatorio(s).' -f $missing.Count) -ForegroundColor Red
    }
}

if ($missing.Count -eq 0) { exit 0 } else { exit 1 }
