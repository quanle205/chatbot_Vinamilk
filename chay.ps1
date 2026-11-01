# Chạy chatbot trên máy bằng một lệnh. Dùng:  .\chay.bat   (hoặc  powershell -File .\chay.ps1 [-Port 8000] [-NoBrowser])
# Khóa Gemini được lấy lần lượt từ: biến môi trường GEMINI_API_KEY -> tệp .env -> .streamlit\secrets.toml -> hỏi một lần rồi lưu vào .env.
# Cả .env và secrets.toml đều nằm trong .gitignore nên khóa không bị đưa lên GitHub.
param([int]$Port = 8000, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Read-Key([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    $m = Select-String -Path $path -Pattern '^\s*(?:GEMINI_API_KEY|GOOGLE_API_KEY)\s*[=:]\s*"?([^"\s#]+)"?' | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value }
    return $null
}

if (-not $env:GEMINI_API_KEY) { $env:GEMINI_API_KEY = Read-Key ".env" }
if (-not $env:GEMINI_API_KEY) { $env:GEMINI_API_KEY = Read-Key ".streamlit\secrets.toml" }
if (-not $env:GEMINI_API_KEY) {
    $k = Read-Host "Dán khóa Gemini (chỉ hỏi một lần, lưu vào .env, không đưa lên git)"
    if ($k) { Set-Content -Path ".env" -Value "GEMINI_API_KEY=$($k.Trim())" -Encoding ascii; $env:GEMINI_API_KEY = $k.Trim() }
}
if ($env:GEMINI_API_KEY) { Write-Host "Đã nạp khóa Gemini." } else { Write-Host "Chưa có khóa Gemini: chỉ dùng được mục Tra cứu số liệu." }

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Cổng $Port đang được dùng (có thể chatbot đang chạy). Mở http://localhost:$Port hoặc chạy lại với -Port 8001."
    exit 1
}

python -c "import uvicorn, fastapi, duckdb, sklearn, google.genai" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Cài thư viện lần đầu..."
    python -m pip install -q -r requirements.txt uvicorn
}

$url = "http://localhost:$Port"
if (-not $NoBrowser) { Start-Job -ScriptBlock { param($u) Start-Sleep 4; Start-Process $u } -ArgumentList $url | Out-Null }
Write-Host "Chatbot chạy tại $url  (nhấn Ctrl+C để dừng)"
python -m uvicorn api.index:app --port $Port
