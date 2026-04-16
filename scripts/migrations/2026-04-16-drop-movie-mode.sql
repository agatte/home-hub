-- Migration: drop `movie` mode, fold all rows into `watching`.
--
-- `movie` and `watching` had byte-identical lighting, multipliers, and
-- transition speed. The split is being collapsed; `watching` covers all
-- TV/video content going forward. Run this BEFORE deploying the code
-- change (which removes "movie" from VALID_MODES, so post-deploy any
-- residual rows would fail validation if anything tried to read them
-- back through a model).
--
-- Pre-deploy row counts (2026-04-16):
--   activity_events.mode='movie'          → 19
--   activity_events.previous_mode='movie' → (see verification)
--   light_adjustments.mode_at_time='movie' → 1
--   sonos_playback_events.mode_at_time='movie' → 9
--   mode_playlists, mode_scene_overrides, ml_decisions, learned_rules,
--     scene_activations: 0 (UPDATEs are no-ops, kept for completeness)

BEGIN;

UPDATE activity_events       SET mode='watching'           WHERE mode='movie';
UPDATE activity_events       SET previous_mode='watching'  WHERE previous_mode='movie';
UPDATE light_adjustments     SET mode_at_time='watching'   WHERE mode_at_time='movie';
UPDATE sonos_playback_events SET mode_at_time='watching'   WHERE mode_at_time='movie';
UPDATE scene_activations     SET mode_at_time='watching'   WHERE mode_at_time='movie';
UPDATE mode_playlists        SET mode='watching'           WHERE mode='movie';
UPDATE mode_scene_overrides  SET mode='watching'           WHERE mode='movie';
UPDATE ml_decisions          SET predicted_mode='watching' WHERE predicted_mode='movie';
UPDATE ml_decisions          SET actual_mode='watching'    WHERE actual_mode='movie';
UPDATE learned_rules         SET predicted_mode='watching' WHERE predicted_mode='movie';

COMMIT;

-- Verification (run after):
--   SELECT mode,         COUNT(*) FROM activity_events       GROUP BY mode;
--   SELECT mode_at_time, COUNT(*) FROM light_adjustments     GROUP BY mode_at_time;
--   SELECT mode_at_time, COUNT(*) FROM sonos_playback_events GROUP BY mode_at_time;
-- All should show zero rows where the value is 'movie'.
