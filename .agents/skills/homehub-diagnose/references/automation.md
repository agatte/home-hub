# Automation, Presence, and ML

Start with `/api/automation/status`, `/health`, and camera/presence freshness.

For a wrong mode, identify the current house state, activity, source, manual
or DND override, lifecycle holds, physical evidence, software/process intent,
and freshness. Explain which signal won and which alternatives were vetoed.

For presence/camera issues, distinguish person authority from localization.
YOLO-gated physical evidence outranks weak software guesses; unknown/blinded
camera evidence abstains rather than inventing a room.

For ML or autonomy questions, inspect only implicated lanes, such as behavioral
predictor, confidence fusion, audio classifier, lighting learner, music bandit,
rule engine, or relevant recent decisions. Treat shadow lanes as evidence only,
never production authority.

For override pressure, use recent read-only event data and compare repeated
manual/API/Alexa/guest corrections by mode and source rather than relying on a
single aggregate.

State uncertainty explicitly when a required signal is stale, absent, or
ambiguous.
