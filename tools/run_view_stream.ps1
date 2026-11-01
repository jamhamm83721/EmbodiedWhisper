param(
    [string]$HostIp = "0.0.0.0",
    [int]$Port = 9090
)

$ErrorActionPreference = "Stop"

Write-Host "Local IPv4 addresses from ipconfig:"
ipconfig | Select-String "IPv4"
Write-Host ""
Write-Host "The ESP32 firmware must connect to this PC's WLAN IPv4 address on port $Port."
Write-Host "If Windows Firewall asks, allow Python on private networks."
Write-Host ""

python "$PSScriptRoot\view_tcp_stream.py" --host $HostIp --port $Port
