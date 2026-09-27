# Convenience runner for the JMeter perf test.
# Sets JAVA_HOME (auto-detects the installed OpenJDK 17) and invokes JMeter in
# non-GUI mode, producing results.jtl + an HTML dashboard in -Out.
#
# Usage (from this benchmark/ folder):
#   .\run_jmeter.ps1                          # default: loops=150, users=8, duration=60s
#   .\run_jmeter.ps1 -Users 4 -Out report_u4  # one concurrency level, separate report
#   .\run_jmeter.ps1 -Loops 30 -Users 1       # quick check
param(
  [int]$Loops = 150,
  [int]$Users = 8,
  [int]$Ramp = 8,
  [int]$Duration = 60,
  [string]$TargetHost = "localhost",
  [int]$Port = 8000,
  [string]$Out = "report"
)

$ErrorActionPreference = "Stop"

# JDK (auto-detect so a JDK patch update doesn't break the path)
$jdk = Get-ChildItem "C:\Program Files\Microsoft" -Directory -Filter "jdk-17*" -ErrorAction SilentlyContinue |
  Sort-Object Name -Descending | Select-Object -First 1
if (-not $jdk) { throw "OpenJDK 17 not found under C:\Program Files\Microsoft" }
$env:JAVA_HOME = $jdk.FullName
$env:PATH = "$($jdk.FullName)\bin;$env:PATH"

$jmeter = "C:\Users\Bhoomsiri\tools\apache-jmeter-5.6.3\bin\jmeter.bat"
if (-not (Test-Path $jmeter)) { throw "jmeter.bat not found at $jmeter" }

# JMeter refuses to overwrite an existing results file / report dir
Remove-Item "results.jtl" -ErrorAction SilentlyContinue
if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }

Write-Host "Running JMeter: loops=$Loops users=$Users ramp=$Ramp duration=${Duration}s -> $TargetHost`:$Port"
& $jmeter -n -t ods_perf.jmx -l results.jtl -e -o $Out `
  -Jhost=$TargetHost -Jport=$Port -Jprotocol=http `
  -Jloops=$Loops -Jusers=$Users -Jramp=$Ramp -Jduration=$Duration

Write-Host "`nDone. Open $Out\index.html for the dashboard."
