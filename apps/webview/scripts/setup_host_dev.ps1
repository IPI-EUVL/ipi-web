[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$EcsSource = "",
    [string]$ChamberCtlSource = "",
    [string]$ChamberCtlFallback = "https://github.com/IPI-EUVL/chamber-ctl/archive/refs/heads/main.tar.gz"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$constraintsPath = Join-Path $projectRoot "constraints-host-dev.txt"
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $constraintsPath)) {
    throw "Host development constraints do not exist: $constraintsPath"
}

if (-not (Test-Path $venvPython)) {
    & $Python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the webview virtual environment."
    }
}

function Invoke-VenvPython {
    & $venvPython @args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $venvPython $args"
    }
}

function Find-EditableSource {
    param([string]$DistributionName)

    $probe = @'
import json
import pathlib
import sys
import urllib.parse
from importlib import metadata

try:
    direct_url = metadata.distribution(sys.argv[1]).read_text("direct_url.json")
    value = json.loads(direct_url) if direct_url else {}
    if not value.get("dir_info", {}).get("editable"):
        raise SystemExit(0)
    parsed = urllib.parse.urlparse(value.get("url", ""))
    if parsed.scheme != "file":
        raise SystemExit(0)
    path = urllib.parse.unquote(parsed.path)
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    print(pathlib.Path(path))
except metadata.PackageNotFoundError:
    pass
'@
    $result = $probe | & $Python - $DistributionName
    if ($LASTEXITCODE -ne 0 -or $null -eq $result) {
        return $null
    }
    $candidate = ($result | Select-Object -Last 1).Trim()
    if ($candidate -and (Test-Path $candidate)) {
        return (Resolve-Path $candidate).Path
    }
    return $null
}

function Install-Source {
    param(
        [string]$DistributionName,
        [string]$ExplicitSource,
        [string]$Fallback = ""
    )

    $source = $ExplicitSource
    if ([string]::IsNullOrWhiteSpace($source)) {
        $source = Find-EditableSource $DistributionName
    }
    if ([string]::IsNullOrWhiteSpace($source)) {
        $source = $Fallback
    }
    if ([string]::IsNullOrWhiteSpace($source)) {
        Write-Output "$DistributionName will be resolved from the project package index requirement."
        return
    }
    if (Test-Path $source) {
        $source = (Resolve-Path $source).Path
        Write-Output "Using editable $DistributionName source: $source"
        Invoke-VenvPython -m pip install -e $source
        return
    }
    Write-Output "Using $DistributionName fallback: $source"
    Invoke-VenvPython -m pip install $source
}

Install-Source "ipi-ecs" $EcsSource
Install-Source "ipi-chamber-ctl" $ChamberCtlSource $ChamberCtlFallback
Invoke-VenvPython -m pip install -c $constraintsPath -e "$projectRoot[dev]"
$originCheck = "import chamber_ctl, ipi_ecs, ipi_webview; print(chamber_ctl.__file__); print(ipi_ecs.__file__); print(ipi_webview.__file__)"
Invoke-VenvPython -c $originCheck

Write-Output "Host development environment ready: $venvPath"