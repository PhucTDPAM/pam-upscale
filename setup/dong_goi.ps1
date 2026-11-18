# Dong goi Pam Upscale thanh file zip de cai tren may khac (khong kem .venv)
$App = Split-Path -Parent $PSScriptRoot
$out = Join-Path (Split-Path -Parent $App) "PamUpscale.zip"
$skip = @(".venv", ".git", "__pycache__", "upscaled", "settings.json", "Pam Upscale.lnk")
$items = Get-ChildItem $App -Force | Where-Object { $skip -notcontains $_.Name -and $_.Name -notlike "*.part*" }
if (Test-Path $out) { Remove-Item $out -Force }
$stage = Join-Path $env:TEMP "PamUpscale_pkg\Pam Upscale"
if (Test-Path (Split-Path $stage)) { Remove-Item (Split-Path $stage) -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
$items | Copy-Item -Destination $stage -Recurse -Force
Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Compress-Archive -Path $stage -DestinationPath $out
Remove-Item (Split-Path $stage) -Recurse -Force
Write-Host ("Da tao: " + $out + "  (" + [math]::Round((Get-Item $out).Length / 1MB) + " MB)") -ForegroundColor Green
Write-Host "Tren may khac: giai nen -> chay cai_dat.bat"
