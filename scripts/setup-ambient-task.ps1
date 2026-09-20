# RETIRED: the ambient monitor is managed by the unified Home Hub Agent Supervisor.
# This filename is retained only so old notes/commands fail safely instead of
# recreating an obsolete standalone Scheduled Task.

Write-Error @"
setup-ambient-task.ps1 is retired.
Do not create a separate Home Hub Ambient Monitor task.
Use scripts\setup-supervisor-task.ps1 to install/rebuild the unified
'Home Hub Agent Supervisor' task.
"@
exit 1
