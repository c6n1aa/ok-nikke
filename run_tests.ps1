$pythonExe = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }

# 与 CI 一致：冻结真实 OCR（部分机器会因 CPU 差异执行到非法指令直接崩掉进程）。
# 需要跑真实 OCR 时，用 dev_tools/check_real_ocr.py。
$env:OK_NIKKE_NO_REAL_OCR = '1'

Get-ChildItem -Path ".\tests\*.py" | ForEach-Object {
  Write-Host "Running tests in $($_.FullName)"
  try {
      # Run the Python unittest command
      & $pythonExe -m unittest $_.FullName

      # Check if the previous command succeeded
      if ($LASTEXITCODE -ne 0) {
          throw "Tests failed in $($_.FullName)"
      }
  } catch {
      # Stop the loop and return the error
      Write-Error $_
      exit 1
  }
}