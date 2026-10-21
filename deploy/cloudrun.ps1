# Triển khai chatbot lên Google Cloud Run. MẶC ĐỊNH CHỈ IN CÁC LỆNH (dry-run); thêm -Run để chạy thật.
#
#   .\deploy\cloudrun.ps1 -Project my-gcp-project                      # xem các lệnh sẽ chạy
#   .\deploy\cloudrun.ps1 -Project my-gcp-project -Run                 # triển khai, dịch vụ cần đăng nhập Google để truy cập
#   .\deploy\cloudrun.ps1 -Project my-gcp-project -Run -Public         # triển khai công khai (ai có link cũng dùng được)
#
# Điều kiện: đã cài gcloud và `gcloud auth login`; dự án bật thanh toán; đã bật Claude Opus 5.5 trong Vertex AI Model Garden
# của dự án (Anthropic Claude -> Enable) và có quota. Bản public tốn tiền mỗi lượt hỏi: giới hạn lượt/phiên và /ngày đặt
# bằng SESSION_LIMIT và DAILY_LIMIT bên dưới; --max-instances giới hạn mức mở rộng.
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Region = "asia-southeast1",          # vùng chạy Cloud Run
    [string]$VertexRegion = "global",             # vùng gọi Claude trên Vertex AI
    [string]$Service = "vinamilk-chatbot",
    [string]$Model = "claude-opus-5-5",
    [int]$SessionLimit = 15,
    [int]$DailyLimit = 300,
    [switch]$Public,
    [switch]$Run
)
$ErrorActionPreference = "Stop"
$sa = "$Service@$Project.iam.gserviceaccount.com"
$auth = if ($Public) { "--allow-unauthenticated" } else { "--no-allow-unauthenticated" }
$envVars = "ANTHROPIC_VERTEX_PROJECT_ID=$Project,CLOUD_ML_REGION=$VertexRegion,VINAMILK_MODEL=$Model,SESSION_LIMIT=$SessionLimit,DAILY_LIMIT=$DailyLimit"

$steps = @(
    "gcloud config set project $Project",
    "gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com",
    "gcloud iam service-accounts create $Service --display-name 'Vinamilk chatbot'",
    "gcloud projects add-iam-policy-binding $Project --member serviceAccount:$sa --role roles/aiplatform.user",
    # Streamlit cần WebSocket nên dùng session affinity; một instance xử lý tối đa 20 phiên đồng thời.
    "gcloud run deploy $Service --source . --region $Region --service-account $sa --memory 1Gi --cpu 1 " +
    "--concurrency 20 --max-instances 2 --timeout 900 --session-affinity $auth --set-env-vars $envVars"
)
Write-Host "Dự án: $Project | Vùng Cloud Run: $Region | Vertex: $VertexRegion | Truy cập: $(if ($Public) {'CÔNG KHAI'} else {'cần đăng nhập Google'})"
foreach ($s in $steps) {
    Write-Host "> $s"
    if ($Run) { Invoke-Expression $s; if ($LASTEXITCODE -ne 0 -and $s -notmatch "service-accounts create") { throw "Lệnh lỗi: $s" } }
}
if (-not $Run) { Write-Host "`n(Dry-run: chưa chạy gì. Thêm -Run để triển khai.)" }
