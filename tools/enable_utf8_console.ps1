[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$PSDefaultParameterValues["Out-File:Encoding"] = "utf8"
$PSDefaultParameterValues["Set-Content:Encoding"] = "utf8"
$PSDefaultParameterValues["Add-Content:Encoding"] = "utf8"

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (Get-Command chcp.com -ErrorAction SilentlyContinue) {
    chcp.com 65001 > $null
}

Write-Host "UTF-8 console enabled in this PowerShell session."
Write-Host "InputEncoding  : $([Console]::InputEncoding.WebName)"
Write-Host "OutputEncoding : $([Console]::OutputEncoding.WebName)"
Write-Host "PYTHONUTF8     : $env:PYTHONUTF8"
Write-Host "PYTHONIOENCODING: $env:PYTHONIOENCODING"
