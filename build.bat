@echo off
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
where cl >nul 2>nul
if errorlevel 1 (
    if not exist "%VSWHERE%" exit /b 1
    for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do call "%%I\Common7\Tools\VsDevCmd.bat" -arch=amd64 >nul
)
where cl >nul 2>nul
if errorlevel 1 exit /b 1
if not exist build mkdir build
cl /nologo /O2 /std:c++17 /EHsc /W4 /Fe:build\fusion_vm.exe src\vm.cpp /Fo:build\vm.obj
exit /b %errorlevel%
