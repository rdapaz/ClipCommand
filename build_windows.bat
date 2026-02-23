@echo off
REM build_windows.bat — build ClipCommand for Windows distribution
REM Run from the project root in a venv-activated terminal

echo === ClipCommand Windows Build ===

REM Install/upgrade build deps
pip install --upgrade pyinstaller

REM Clean previous build
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Build
pyinstaller clipcommand.spec

REM Package for distribution
echo.
echo === Packaging ===
cd dist
powershell Compress-Archive -Path ClipCommand -DestinationPath ClipCommand-windows.zip
cd ..

echo.
echo === Done ===
echo Distribute:  dist\ClipCommand-windows.zip
echo Contents:    dist\ClipCommand\
echo.
echo Recipients unzip and run: ClipCommand\ClipCommand.exe
