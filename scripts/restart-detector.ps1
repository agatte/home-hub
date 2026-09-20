# RETIRED: individual detector restarts bypass unified supervisor ownership.
# This filename is retained so old commands fail safely rather than killing or
# launching an unmanaged activity-detector process.

Write-Error @"
restart-detector.ps1 is retired.
Do not restart activity_detector independently.
Use scripts\restart-agents.ps1 for an identity-safe unified supervisor restart.
"@
exit 1
