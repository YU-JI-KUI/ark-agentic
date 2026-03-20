@echo off
REM publish.cmd — Build and upload ark-agentic (core + CLI only) on Windows (cmd)

setlocal enabledelayedexpansion

pushd "%~dp0.."
set REPO_ROOT=%CD%
popd
set DIST_DIR=%REPO_ROOT%\dist

REM Internal PyPI endpoint
if "%PYPI_REPO_URL%"=="" (
  set INTERNAL_REPO_URL=http://maven.abc.com.cn/repository/pypi/
) else (
  set INTERNAL_REPO_URL=%PYPI_REPO_URL%
)

set DRY_RUN=false
if "%1"=="--dry-run" (
  set DRY_RUN=true
)

REM Clean previous builds
if exist "%DIST_DIR%" (
  rmdir /S /Q "%DIST_DIR%"
)

REM Read version from pyproject.toml
set PYPROJECT_PATH=%REPO_ROOT%\pyproject.toml
for /f "usebackq delims=" %%v in (`python -c "import tomllib, pathlib; d = tomllib.loads(pathlib.Path(r'%PYPROJECT_PATH%').read_text()); print(d['project']['version'])"`) do (
  set VERSION=%%v
)
echo [Version] %VERSION%

REM Build Studio frontend (dist/ force-included in wheel via pyproject.toml)
set FRONTEND_DIR=%REPO_ROOT%\src\ark_agentic\studio\frontend
if exist "%FRONTEND_DIR%\package.json" (
  echo [Building] Studio frontend...
  cd /d "%FRONTEND_DIR%"
  call npm ci --ignore-scripts || goto :error
  call npm run build || goto :error
  cd /d "%REPO_ROOT%"
  echo [Done] Studio frontend built
)

REM Build ark-agentic wheel
echo [Building] ark-agentic...
cd /d "%REPO_ROOT%"
uv build --out-dir "%DIST_DIR%" || goto :error

echo.
echo [Build artifacts]
dir "%DIST_DIR%"

if "%DRY_RUN%"=="true" (
  echo [Dry run] skipping upload
  goto :eof
)

REM Upload to internal PyPI
echo [Uploading] to %INTERNAL_REPO_URL% ...
twine upload ^
  --repository-url "%INTERNAL_REPO_URL%" ^
  "%DIST_DIR%\ark_agentic-%VERSION%*" || goto :error

echo [Done] Published ark-agentic==%VERSION%
goto :eof

:error
echo Publish failed with error %errorlevel%.
exit /b %errorlevel%

