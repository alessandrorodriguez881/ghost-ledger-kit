param([string]$Name, [string]$ExtraTools = '', [string]$Agent = '')
# Runs one Kiro CLI spec-mode call with the prompt in <Name>.txt and writes <Name>_out.txt, then runs ruff and pytest.
# -ExtraTools adds comma-separated tool ids (for example MCP tools) to the trusted list.
# -Agent runs the call with a workspace custom agent from .kiro/agents (for example ghost-ledger-builder).
$sp = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Split-Path -Parent $sp)  # the repository root (was the absolute path of the local clone)
$p = (Get-Content "$sp\$Name.txt" -Encoding UTF8 | Where-Object { $_ -ne '' }) -join ' '
if ($p.Contains('"')) { throw 'double quote in prompt' }
$trust = 'fs_read,fs_write,str_replace'
if ($ExtraTools) { $trust = "$trust,$ExtraTools" }
$agentArgs = @()
if ($Agent) { $agentArgs = @('--agent', $Agent) }
& "$env:LOCALAPPDATA\Kiro-Cli\kiro-cli.exe" chat --v3 --mode spec @agentArgs --trust-workspace --no-interactive "--trust-tools=$trust" $p *> "$sp\${Name}_out.txt"
"KIRO EXIT $LASTEXITCODE"
Get-Content "$sp\${Name}_out.txt" | Where-Object { $_ -notmatch '^\[tool\]|^\s*\+|^En l|CategoryInfo|FullyQualified|^kiro-cli.exe|^\[denied\]' } | Select-Object -Last 25
"----- git status"
git status --short
"----- ruff"
& .\.venv\Scripts\ruff.exe check . 2>&1 | Select-Object -Last 15
"----- pytest"
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider 2>&1 | Select-Object -Last 30
