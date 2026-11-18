# Pam Upscale - trinh cai dat tu dong (Windows 10/11)
# Tu nhan dien card do hoa va cai dung goi:
#   NVIDIA RTX 20xx tro len  -> PyTorch CUDA 12.8 (nhanh nhat)
#   NVIDIA GTX 9xx/10xx/16xx -> PyTorch CUDA 12.6
#   AMD / Intel / khong card -> ONNX Runtime DirectML (khong can PyTorch)
$ErrorActionPreference = "Stop"
$App = Split-Path -Parent $PSScriptRoot
Set-Location $App
function Step($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

# ---------------------------------------------------------------- Python
Step "1/5 Kiem tra Python"
function Find-Python {
    foreach ($c in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3"), @("python"))) {
        try {
            $v = & $c[0] $c[1..9] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]"3.10") {
                return (& $c[0] $c[1..9] -c "import sys; print(sys.executable)")
            }
        } catch {}
    }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    Write-Host "Chua co Python - dang cai Python 3.13 qua winget..."
    winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
    $py = Find-Python
    if (-not $py) { throw "Khong cai duoc Python. Hay cai Python 3.13 tu python.org roi chay lai." }
}
Write-Host "Python: $py"

# ---------------------------------------------------------------- venv + thu vien chung
Step "2/5 Tao moi truong & cai thu vien"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv }
$vpy = Join-Path $App ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip -q
& $vpy -m pip install -r requirements.txt

# ---------------------------------------------------------------- GPU
Step "3/5 Nhan dien card do hoa"
Get-CimInstance Win32_VideoController | ForEach-Object { Write-Host (" - " + $_.Name) }
$cc = $null
try { $cc = (& nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1).Trim() } catch {}
if ($cc) {
    $ccv = [version]$cc
    if ($ccv -ge [version]"7.5") { $idx = "cu128" } elseif ($ccv -ge [version]"5.0") { $idx = "cu126" } else { $idx = $null }
    if ($idx) {
        Write-Host "Card NVIDIA (compute $cc) -> cai PyTorch $idx (~3GB, vui long cho)..." -ForegroundColor Green
        try {
            # torch + torchvision PHAI cai cung luc tu index CUDA, neu khong pip se keo ban CPU de len
            & $vpy -m pip install torch torchvision --index-url "https://download.pytorch.org/whl/$idx"
            # spandrel: nap model Real-CUGAN / RealPLKSR / DAT (khong cho pip doi ban torch)
            & $vpy -m pip install spandrel --no-deps
            & $vpy -m pip install einops safetensors
            if ($ccv -ge [version]"7.5") {
                Write-Host "Card RTX -> cai NVIDIA RTX Video Super Resolution..." -ForegroundColor Green
                & $vpy -m pip install nvidia-vfx --no-deps
            }
        }
        catch { Write-Host "Cai PyTorch loi - app se dung DirectML thay the." -ForegroundColor Yellow }
    } else {
        Write-Host "Card NVIDIA qua cu cho CUDA - dung DirectML." -ForegroundColor Yellow
    }
} else {
    Write-Host "Khong co card NVIDIA -> dung DirectML (AMD/Intel) hoac CPU. Khong can PyTorch." -ForegroundColor Green
}

# ---------------------------------------------------------------- ffmpeg
Step "4/5 Kiem tra ffmpeg"
$hasFf = (Test-Path "bin\ffmpeg.exe") -or (Get-Command ffmpeg -ErrorAction SilentlyContinue)
if (-not $hasFf) {
    Write-Host "Dang tai ffmpeg (~100MB)..."
    New-Item -ItemType Directory -Force bin | Out-Null
    $zip = Join-Path $env:TEMP "ffmpeg-essentials.zip"
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip
    $tmp = Join-Path $env:TEMP "ffmpeg-essentials"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip $tmp
    Get-ChildItem $tmp -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination bin -Force
    Remove-Item $zip, $tmp -Recurse -Force
}
Write-Host "ffmpeg OK"

# ---------------------------------------------------------------- shortcut
Step "5/5 Tao shortcut"
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @($App, [Environment]::GetFolderPath("Desktop"))) {
    $lnk = $ws.CreateShortcut((Join-Path $dir "Pam Upscale.lnk"))
    $lnk.TargetPath = Join-Path $App ".venv\Scripts\pythonw.exe"
    $lnk.Arguments = "`"$App\app.py`""
    $lnk.WorkingDirectory = $App
    $lnk.IconLocation = Join-Path $App "assets\icon.ico"
    $lnk.Description = "Pam Upscale - by PAM Media"
    $lnk.Save()
}

& $vpy -c "import sys; sys.path.insert(0, '.'); from upscaler import backend as b; d = b.detect(); print('Thiet bi xu ly:', b.BACKEND_LABELS[b.resolve('auto')], '-', b.device_name(b.resolve('auto')))"
Write-Host "`nXONG! Mo 'Pam Upscale' tren Desktop de su dung." -ForegroundColor Green
