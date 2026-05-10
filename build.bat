@echo off
chcp 65001 >nul
echo ========================================
echo   UsageTracker - Build Script
echo ========================================
echo.

:: Install PyInstaller if not present
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
    echo.
)

:: Generate app icon
echo Generating app icon...
python generate_icon.py
echo.

:: Clean previous build
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: Build
echo Building with PyInstaller...
pyinstaller app.spec --clean
echo.

if exist "dist\UsageTracker\UsageTracker.exe" (
    echo ========================================
    echo   Build SUCCESS!
    echo   Output: dist\UsageTracker\
    echo ========================================
    echo.
    echo To distribute: zip the dist\UsageTracker folder
) else (
    echo ========================================
    echo   Build FAILED!
    echo ========================================
)

pause
