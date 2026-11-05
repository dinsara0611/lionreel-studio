# One command for all tests. Syncs code from the Drive folder into the sandbox and
# runs there, so no test can reach production data or the Drive output folder.
#   powershell -File scripts/run_all_tests.ps1 [pytest args]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PytestArgs)

$Sandbox = 'C:\LionReel_sandbox'
$Proj = "$Sandbox\proj"
$Repo = Split-Path -Parent $PSScriptRoot

$Exclude = @('.git', '.venv', 'node_modules', 'output', 'finished', 'work', 'raw', 'own_footage',
             'data', 'logs', 'analysis', 'ui_audit', 'quarantine', 'scratch', 'screenshots',
             'test-results', 'LionReel_backup_before_ui_polish', 'LionReel_backup_before_stage_order',
             '__pycache__', '.devcontainer')
robocopy $Repo $Proj /MIR /R:1 /W:1 /NP /NFL /NDL /NJH /NJS /XD @Exclude /XF '*.pyc' 'config.json' 'web_server.lock' 'cookies_raw.json' | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Error "robocopy failed: $LASTEXITCODE"; exit 2 }
New-Item -ItemType Directory -Force "$Proj\data", "$Proj\logs", "$Proj\work", "$Proj\finished", "$Proj\output" | Out-Null

$env:LIONREEL_ROOT = $Sandbox
$env:LIONREEL_DATA_DIR = "$Sandbox\data"
$env:LIONREEL_CACHE_DIR = "$Sandbox\cache"
$env:IS_TEST = '1'
$env:NO_BROWSER = '1'
$env:PYTHONUTF8 = '1'
Set-Location $Proj
& "$Sandbox\venv\Scripts\python.exe" -m pytest @PytestArgs
exit $LASTEXITCODE
