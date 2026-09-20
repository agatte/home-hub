# RETIRED: the activity detector is managed by the unified Home Hub Agent Supervisor.
# This filename is retained only so old notes/commands fail safely instead of
# recreating an obsolete standalone Scheduled Task.

Write-Error @"
setup-detector-task.ps1 is retired.
Do not create a separate Home Hub PC Activity Detector task.
Use scripts\setup-supervisor-task.ps1 to install/rebuild the unified
'Home Hub Agent Supervisor' task.
"@
exit 1
