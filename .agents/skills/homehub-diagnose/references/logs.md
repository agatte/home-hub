# Logs

Use bounded `journalctl --user` windows on the Latitude. Start with the service
that owns the symptom and warning-or-higher priority; widen only when needed.

Primary units include `home-hub.service`, `home-hub-tunnel.service`,
`home-hub-guest-gateway.service`, and `home-hub-latitude-streaming.service`.
Do not assume ambient is active; inspect it only when the symptom concerns that
lane.

Prefer tracebacks, ERROR/WARNING lines, restart boundaries, health failures,
circuit-breaker transitions, and repeated state changes. Treat expected
transient reconnect noise as evidence only when it correlates with the symptom.

For a named pattern, use a bounded literal/escaped search and keep the returned
window small enough to preserve chronology.

Report timestamp, unit, severity, concise evidence, likely owner/cause, and the
next focused check. Log inspection is read-only.