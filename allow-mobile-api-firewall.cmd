@echo off
setlocal

rem Run once as Administrator when Expo Go cannot reach Django on the same
rem trusted Private Wi-Fi/hotspot. This opens only TCP 8000 to the local subnet.

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo This file must be run as Administrator.
  echo Right-click allow-mobile-api-firewall.cmd, then choose Run as administrator.
  pause
  exit /b 1
)

rem Replace the old rule so rerunning this setup does not create duplicates.
netsh advfirewall firewall delete rule name=DengueWatchDjangoAPI8000 >nul 2>&1
netsh advfirewall firewall add rule name=DengueWatchDjangoAPI8000 dir=in action=allow protocol=TCP localport=8000 remoteip=localsubnet profile=private
if errorlevel 1 (
  echo Windows could not add the firewall rule.
  pause
  exit /b 1
)

echo.
echo Firewall access for the DengueWatch Django API was added successfully.
echo This allows phones on this computer's Private Wi-Fi or hotspot to reach TCP port 8000.
echo It does not expose the API to Public networks or the internet.
echo Keep the phone and computer on the same Private Wi-Fi or hotspot.
echo Then run PRE-MOBILE-SYSTEM\start-denguewatch-development.cmd.
pause
