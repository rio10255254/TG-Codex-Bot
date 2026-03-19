$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Get-ChildItem -LiteralPath $root -Recurse -File -Filter 'install_bridge_gui.ps1' | Select-Object -First 1 -ExpandProperty FullName

if (-not $target) {
    throw "Could not locate install_bridge_gui.ps1 next to this launcher."
}

& $target
