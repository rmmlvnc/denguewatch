@echo off
setlocal

rem Start the DengueWatch website and mobile API from this folder.
set "PROJECT_DIR=%~dp0"
set "PYTHON=%USERPROFILE%\django-env\Scripts\python.exe"

if not exist "%PYTHON%" set "PYTHON=%PROJECT_DIR%django-env\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%PROJECT_DIR%..\django-env\Scripts\python.exe"

if not exist "%PROJECT_DIR%manage.py" (
  echo Django manage.py was not found in:
  echo %PROJECT_DIR%
  pause
  exit /b 1
)

if not exist "%PYTHON%" (
  echo Django virtual-environment Python was not found.
  echo Checked the user and project django-env folders.
  echo Set PYTHON in this file to your environment's Scripts\python.exe.
  pause
  exit /b 1
)

"%PYTHON%" -c "import django; from PIL import Image" >nul 2>&1
if errorlevel 1 (
  echo Django or Pillow is missing from:
  echo %PYTHON%
  echo Install the dependencies using:
  echo "%PYTHON%" -m pip install -r "%PROJECT_DIR%requirements.txt"
  pause
  exit /b 1
)

cd /d "%PROJECT_DIR%"
echo.
echo Starting DengueWatch website and API at http://127.0.0.1:8000/
echo Open http://127.0.0.1:8000/login/ in this computer's browser.
echo Keep this window open while using the website or mobile app.
echo Press Ctrl+C here to stop the server.
echo.
"%PYTHON%" "%PROJECT_DIR%manage.py" runserver 0.0.0.0:8000
set "SERVER_EXIT=%ERRORLEVEL%"
echo.
echo Django stopped with exit code %SERVER_EXIT%.
echo Review the error above. If port 8000 is occupied, close its existing DengueWatch server window first.
pause
exit /b %SERVER_EXIT%
