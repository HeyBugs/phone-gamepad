# Starts the phone-gamepad server in a way that passes Windows Firewall.
# It runs under the system Python (which already has an inbound Allow rule)
# while using the project's venv packages via PYTHONPATH.
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = "$proj\.venv\Lib\site-packages"
Set-Location $proj
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" server.py
