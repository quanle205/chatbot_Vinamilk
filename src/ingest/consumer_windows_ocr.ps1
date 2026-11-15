# Nhận ảnh PNG dạng base64 qua stdin. Mỗi dòng stdout là tọa độ từ của một trang.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1
} | Select-Object -First 1

function Wait-Result($operation, [Type] $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    return $task.GetAwaiter().GetResult()
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'No Windows OCR recognizer is installed.' }

while ($null -ne ($inputLine = [Console]::ReadLine())) {
    try {
        $stream = New-Object 'Windows.Storage.Streams.InMemoryRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime'
        $writer = New-Object 'Windows.Storage.Streams.DataWriter,Windows.Storage.Streams,ContentType=WindowsRuntime' -ArgumentList $stream
        $writer.WriteBytes([Convert]::FromBase64String($inputLine))
        $null = Wait-Result ($writer.StoreAsync()) ([UInt32])
        $null = $writer.DetachStream()
        $stream.Seek(0)
        $decoder = Wait-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $image = Wait-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Wait-Result ($engine.RecognizeAsync($image)) ([Windows.Media.Ocr.OcrResult])
        $width = $image.PixelWidth
        $height = $image.PixelHeight
        $tokens = New-Object 'System.Collections.Generic.List[object]'
        foreach ($line in $result.Lines) {
            foreach ($word in $line.Words) {
                $rect = $word.BoundingRect
                $tokens.Add(@(($rect.X / $width), ($rect.Y / $height),
                    (($rect.X + $rect.Width) / $width), (($rect.Y + $rect.Height) / $height),
                    $word.Text, 0.5))
            }
        }
        [Console]::WriteLine((ConvertTo-Json -InputObject ($tokens.ToArray()) -Compress -Depth 4))
    } catch {
        [Console]::WriteLine((ConvertTo-Json -InputObject @{error = $_.Exception.Message} -Compress))
    } finally {
        if ($null -ne $image) { $image.Dispose(); $image = $null }
        if ($null -ne $writer) { $writer.Dispose(); $writer = $null }
        if ($null -ne $stream) { $stream.Dispose(); $stream = $null }
    }
}
