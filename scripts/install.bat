@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM install.bat - intranet installer for offline-bundle
REM Reads manifest-index.json from bundle, self-checks, installs.
REM Also merges MCP servers (mcp-servers.json) into zcode config
REM via _merge_mcp.py - prompts for ask: secrets there.
REM Usage: install.bat [--bundle <dir>] [--dry-run] [--skill <name>]
REM ============================================================

REM snapshot %~dp0 BEFORE the arg-parse loop: `shift` moves %1.. into %0,
REM so any %~dp0 read after parsing resolves against CWD instead of the
REM script dir (see gotchas A6). Every later use must go through %HERE%.
set "HERE=%~dp0"
set "BUNDLE=%HERE%"
set "DRYRUN=0"
set "WANTSKILL="

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--bundle" (set "BUNDLE=%~2" & shift & shift & goto parse)
if /i "%~1"=="--dry-run" (set "DRYRUN=1" & shift & goto parse)
if /i "%~1"=="--skill" (set "WANTSKILL=%~2" & shift & shift & goto parse)
shift
goto parse
:parsed

REM strip a trailing backslash from bundle for cleaner joins (keep drive-root)
if "%BUNDLE:~-1%"=="\" set "BUNDLE=%BUNDLE:~0,-1%"

echo ============================================
echo   offline-bundle install
echo ============================================
echo bundle: %BUNDLE%
if "%DRYRUN%"=="1" echo mode:   DRY-RUN (self-check only, no install)
echo.

REM --- Step 0: environment detection ---
echo [0] environment detection
where python >nul 2>&1 || (echo   X python not found - install Python first & exit /b 1)
for /f "delims=" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo   !PYVER!
where node >nul 2>&1 || (echo   X node not found - install Node first & exit /b 1)
for /f "delims=" %%v in ('node --version 2^>^&1') do set "NODEVER=%%v"
echo   node !NODEVER!
REM detect conda env (warn if base)
python -c "import os; cp=os.environ.get('CONDA_DEFAULT_ENV',''); print(cp or 'none')" > "%TEMP%\_ob_conda.txt" 2>nul
set /p CENV=<"%TEMP%\_ob_conda.txt"
del "%TEMP%\_ob_conda.txt" 2>nul
for /f "tokens=* delims==" %%x in ("!CENV!") do set "CENV=%%x"
echo   conda env: !CENV!
if /i "!CENV!"=="base" echo   ^!! WARNING: in conda base - recommend: conda create -n zcode python=3.12 then conda activate zcode
echo.

REM --- load index ---
set "INDEX=%BUNDLE%\manifest-index.json"
if not exist "%INDEX%" (echo   X manifest-index.json not found at %INDEX% & exit /b 1)
echo [1] self-check from %INDEX%
echo.

REM --- Step 1: self-check (always; --dry-run exits after) ---
set "CHECKFAIL=0"
python "%HERE%_check_install.py" "%BUNDLE%" "%WANTSKILL%"
if errorlevel 1 set "CHECKFAIL=1"

echo.
if "%DRYRUN%"=="1" (
    echo ============================================
    echo   DRY-RUN complete. No packages installed.
    if "!CHECKFAIL!"=="1" (
        echo   result: ISSUES FOUND - fix before real install
        echo ============================================
        exit /b 1
    )
    echo   result: OK to install
    echo ============================================
    exit /b 0
)
if "!CHECKFAIL!"=="1" (
    echo   X self-check found fatal issues. Aborting. Run with --dry-run to see details.
    exit /b 1
)

echo [2] installing pip dependencies (merged, --no-index)
set "PIPWH=%BUNDLE%\wheelhouse\pip"
set "PIPDID=0"
REM list package names (top-level dist) from wheel filenames; pip resolves transitive deps from find-links
for /f "delims=" %%P in ('python -c "import os,glob;[print(os.path.basename(w).split('-')[0].replace('_','-')) for w in glob.glob(os.path.join(r'%PIPWH%','*.whl'))]"') do set "PIPLIST=!PIPLIST! %%P"
if defined PIPLIST (
    echo   installing:!PIPLIST!
    pip install --no-index --find-links "%PIPWH%"!PIPLIST!
    if errorlevel 1 (echo   X pip install failed ^& exit /b 1)
    set "PIPDID=1"
    echo   pip deps installed
) else (
    echo   no pip wheels to install
)
echo.

echo [3] installing npm dependencies (global, offline)
set "NPMWH=%BUNDLE%\wheelhouse\npm"
set "NPM_SRC=%NPMWH%\node_modules"
set "NPM_DST=%ProgramData%\node-global-libs"
REM Offline npm: copy the pre-resolved node_modules tree to a global path and
REM point NODE_PATH at it. We do NOT call `npm install` here because the intranet
REM has no registry access - the tree was fully resolved at pack time.
if exist "%NPM_SRC%" (
    echo   source: %NPM_SRC%
    echo   target: %NPM_DST%
    if not exist "%NPM_DST%" mkdir "%NPM_DST%"
    xcopy /e /y /i /q "%NPM_SRC%" "%NPM_DST%" >nul
    if errorlevel 1 (echo   X copy failed ^& exit /b 1)
    setx NODE_PATH "%NPM_DST%" >nul
    set "NODE_PATH=%NPM_DST%"
    echo   npm deps copied to %NPM_DST%; NODE_PATH set
    echo   ^(open a NEW terminal for NODE_PATH to take effect^)
) else if exist "%NPMWH%\*.tgz" (
    echo   ^! only raw tarballs found ^(no node_modules tree^)
    echo     This bundle was packed by an OLD pack.py. Re-pack on the online machine
    echo     to get the full dependency tree, or run on an internet-connected machine:
    call npm install -g "%NPMWH%\*.tgz"
    if errorlevel 1 (echo   X npm install failed ^& exit /b 1)
) else (
    echo   no npm packages to install
)
echo.

echo [4] playwright browser path
if exist "%BUNDLE%\pw-browser" (
    call setx PLAYWRIGHT_BROWSERS_PATH "%BUNDLE%\pw-browser" >nul
    set "PLAYWRIGHT_BROWSERS_PATH=%BUNDLE%\pw-browser"
    echo   PLAYWRIGHT_BROWSERS_PATH set to %BUNDLE%\pw-browser
) else (
    echo   no playwright browser in this bundle
)
echo.

echo [5] landing skills into %USERPROFILE%\.agents\skills\
if not exist "%USERPROFILE%\.agents\skills" mkdir "%USERPROFILE%\.agents\skills"
REM timestamp for backups (robust: strip slashes from %date%)
set "TS=%date:~0,4%%date:~5,2%%date:~8,2%"
for /d %%D in ("%BUNDLE%\skills\*") do (
    set "SKNAME=%%~nxD"
    set "DEST=%USERPROFILE%\.agents\skills\%%~nxD"
    if exist "!DEST!" (
        REM remove any prior same-named backup, then move old aside.
        REM use move (full path) not ren - ren fails on existing target / path quirks.
        set "BAKDEST=%USERPROFILE%\.agents\skills\%%~nxD.bak.!TS!"
        if exist "!BAKDEST!" rmdir /s /q "!BAKDEST!" 2>nul
        move /Y "!DEST!" "!BAKDEST!" >nul 2>&1
        if errorlevel 1 (
            REM move failed (maybe locked) - fallback: remove old in place
            echo   ^! backup move failed for !SKNAME!, removing old
            rmdir /s /q "!DEST!" 2>nul
        ) else (
            echo   backing up existing !SKNAME! to %%~nxD.bak.!TS!
        )
    )
    echo   installing skill !SKNAME!
    xcopy /e /i /q /y "%%D" "!DEST!" >nul
    if errorlevel 1 (echo   X failed to install !SKNAME! ^& exit /b 1)
    echo   skill !SKNAME! -^> !DEST!
)
echo.

echo [6] MCP servers (zcode config merge)
if exist "%BUNDLE%\mcp-servers.json" (
    python "%HERE%_merge_mcp.py" "%BUNDLE%"
    if errorlevel 1 (echo   X MCP install failed ^& exit /b 1)
) else (
    echo   no MCP servers in this bundle
)
echo.

echo [7] tools
if exist "%BUNDLE%\tools\auto\*" (
    echo   auto tools at %BUNDLE%\tools\auto:
    for /d %%D in ("%BUNDLE%\tools\auto\*") do echo     %%~nxD ^(add to PATH: setx PATH "%%PATH%%;%%D"^)
)
if exist "%BUNDLE%\tools\manual\*.README" (
    echo   manual tools need your action:
    for %%F in ("%BUNDLE%\tools\manual\*.README") do echo     %%~nF ^(install manually^)
)
echo.

echo [8] self-test (real imports)
set "STFAIL=0"
python "%HERE%_check_install.py" "%BUNDLE%" "%WANTSKILL%" -test
if errorlevel 1 set "STFAIL=1"
echo.

echo ============================================
if "!STFAIL!"=="0" (
    echo   install complete. Restart zcode to load new skills and MCP servers.
) else (
    echo   install finished but self-test reported issues - see above.
)
echo ============================================
