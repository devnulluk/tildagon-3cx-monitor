# Prepare and launch the pinned official simulator from this checkout.
[CmdletBinding()]
param(
    [ValidateSet('weather', 'rain', 'clock', 'moon', 'meteors', 'advent')][string]$Page = 'weather',
    [ValidateSet('original', 'christmas', 'easter', 'anniversary', 'birthday_self', 'birthday_partner', 'cyberpunk', 'lcars', 'kitty', 'photo', 'noir', 'ocean', 'retro')][string]$Theme = 'original',
    [string]$DemoDate,
    [ValidateSet('original', 'celestial', 'tokyoflash', 'radar', 'flip', 'analogue', 'corpus')][string]$ClockStyle = 'original',
    [ValidateSet('clear', 'day', 'night', 'rain', 'rain-night', 'heavy', 'snow', 'storm', 'fog', 'stale')][string]$WeatherKind = 'clear',
    [ValidateSet('info', 'success', 'warning', 'failure', 'progress')][string]$Notification,
    [switch]$Screenshot,
    [Alias('Video')][string]$Record,
    [ValidateRange(1, 60)][double]$Seconds = 24,
    [ValidateRange(5, 30)][int]$VideoFps = 15,
    [ValidateSet('lcd', 'window')][string]$RecordView = 'lcd',
    [ValidateSet('idle', 'tour', 'calls', 'themes', 'clocks', 'sky', 'notifications')][string]$Showcase = 'tour',
    [string]$OutputPath,
    [ValidateRange(0, 600)][int]$CaptureFrames = 0,
    [ValidateSet('A', 'B', 'C', 'D', 'E', 'F', 'S', 'N', 'ENTER', 'SPACE', 'UP', 'DOWN', 'LEFT', 'RIGHT')][string]$Action,
    [switch]$PartnerDemo,
    [switch]$MatrixDemo,
    [switch]$GalleryStills,
    [string]$PythonPath,
    [string]$SimRoot
)
$ErrorActionPreference = 'Stop'
if ($Screenshot -and $Record) { throw 'Choose either Screenshot or Record.' }
if ($OutputPath -and -not $Screenshot) { throw 'OutputPath requires Screenshot.' }
if ($GalleryStills -and -not $Record) { throw 'GalleryStills requires Record.' }
$offlineCapture = $Screenshot -or [bool]$Record
if (-not $SimRoot) { $SimRoot = $env:TILDAGON_SIM_ROOT }
if (-not $SimRoot) { $SimRoot = Join-Path $PSScriptRoot '.simulator' }
$SimRoot = [System.IO.Path]::GetFullPath($SimRoot)
$setup = Join-Path $PSScriptRoot 'tools\prepare_simulator.py'
$simLaunch = Join-Path $PSScriptRoot 'simulator\launch.py'
$manifest = Join-Path $SimRoot 'runtime.json'
$simPython = $null
if (Test-Path -LiteralPath $manifest) {
    $runtime = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    if (Test-Path -LiteralPath $runtime.python) { $simPython = $runtime.python }
}
if (-not $simPython -or -not (Test-Path -LiteralPath (Join-Path $SimRoot 'firmware\sim\run.py'))) {
    $setupArguments = @($setup, '--sim-root', $SimRoot)
    if ($PythonPath) {
        & $PythonPath @setupArguments
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.10 @setupArguments
    } elseif (Get-Command python3.10 -ErrorAction SilentlyContinue) {
        & python3.10 @setupArguments
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python @setupArguments
    } else {
        throw 'Git and CPython3.10 are required. See simulator/README.md, or pass -PythonPath.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Local simulator setup failed. See simulator/README.md.' }
    $runtime = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    $simPython = $runtime.python
}
# Check the pinned checkout, WASM and dependency versions before executing it.
$verification = & $simPython $setup --sim-root $SimRoot --check
if ($LASTEXITCODE -ne 0) { throw 'Simulator verification failed. See simulator/README.md.' }
$simArguments = @($simLaunch, '--keyboard', '--idle-page', $Page, '--weather-kind', $WeatherKind, '--theme', $Theme, '--clock-style', $ClockStyle)
if ($DemoDate) { $simArguments += @('--demo-date', $DemoDate) }
if ($Notification) { $simArguments += @('--notification', $Notification) }
if ($PartnerDemo) { $simArguments += '--partner-demo' }
if ($MatrixDemo) { $simArguments += '--matrix-demo' }
if ($GalleryStills) { $simArguments += '--gallery-stills' }
if ($Record) { $simArguments += @('--record', $Record, '--seconds', [string]$Seconds, '--video-fps', [string]$VideoFps, '--record-view', $RecordView, '--showcase', $Showcase) }
if ($Action) { $simArguments += @('--action', $Action) }
if ($CaptureFrames -gt 0) { $simArguments += @('--capture-frames', [string]$CaptureFrames) }
if ($Screenshot) {
    if (-not $OutputPath) { $OutputPath = Join-Path $PSScriptRoot ('docs\simulator-' + $Page + '-' + $WeatherKind + '.png') }
    $simArguments += @('--screenshot', '--output', $OutputPath)
}
$previousDriver = $env:SDL_VIDEODRIVER
$previousRoot = $env:TILDAGON_SIM_ROOT
try {
    $env:TILDAGON_SIM_ROOT = $SimRoot
    if ($offlineCapture) {
        $env:SDL_VIDEODRIVER = 'dummy'
        & $simPython @simArguments
        if ($LASTEXITCODE -ne 0) { throw 'The simulator capture failed.' }
        if ($Screenshot) { Write-Host ('Synthetic DEMO screenshot saved to ' + $OutputPath) }
        if ($Record) { Write-Host ('Official simulator DEMO recording saved to ' + $Record + ' (plus GIF, poster and contact sheet)') }
    } else {
        Remove-Item Env:SDL_VIDEODRIVER -ErrorAction SilentlyContinue
        $guiPython = Join-Path (Split-Path -Parent $simPython) 'pythonw.exe'
        if (-not (Test-Path -LiteralPath $guiPython)) { $guiPython = $simPython }
        $quotedArguments = foreach ($argument in $simArguments) {
            '"' + (($argument -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
        }
        $launch = @{ FilePath = $guiPython; ArgumentList = $quotedArguments; WorkingDirectory = $PSScriptRoot }
        if ($env:OS -eq 'Windows_NT') { $launch.WindowStyle = 'Normal' }
        Start-Process @launch
    }
} finally {
    if ($null -eq $previousDriver) { Remove-Item Env:SDL_VIDEODRIVER -ErrorAction SilentlyContinue }
    else { $env:SDL_VIDEODRIVER = $previousDriver }
    if ($null -eq $previousRoot) { Remove-Item Env:TILDAGON_SIM_ROOT -ErrorAction SilentlyContinue }
    else { $env:TILDAGON_SIM_ROOT = $previousRoot }
}
if (-not $offlineCapture) {
    Write-Host 'Official simulator opened with synthetic DEMO data. Left/Right: browse; N: notification inbox; Enter: dismiss notification or next demo call; Space: back; S: settings; T: theme; K: clock; A-F: badge buttons; Esc: exit.'
}
