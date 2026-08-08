@echo off
rem Emits credentials for git from environment - never on argv, never on disk.
echo %1 | findstr /I "Username" >nul && (echo %EDCS_GIT_USER%& exit /b 0)
echo %1 | findstr /I "Password" >nul && (echo %EDCS_GIT_TOKEN%& exit /b 0)
