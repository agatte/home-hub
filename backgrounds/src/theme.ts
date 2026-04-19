/**
 * Mode colors and config pulled from Home Hub's theme.js.
 * Keep in sync with frontend-svelte/src/lib/theme.js.
 */

export interface ModeTheme {
  label: string;
  color: string;
  secondaryColor: string;
  accentColor?: string;
}

export const MODE_THEMES: Record<string, ModeTheme> = {
  gaming: {
    label: "Gaming",
    color: "#a855f7",
    secondaryColor: "#7c3aed",
    accentColor: "#c084fc",
  },
  working: {
    label: "Working",
    color: "#3b82f6",
    secondaryColor: "#1d4ed8",
    accentColor: "#60a5fa",
  },
  watching: {
    label: "Watching",
    color: "#8b5cf6",
    secondaryColor: "#6d28d9",
  },
  social: {
    label: "Social",
    color: "#f472b6",
    secondaryColor: "#ec4899",
    accentColor: "#a855f7",
  },
  relax: {
    label: "Relax",
    color: "#fb923c",
    secondaryColor: "#f97316",
    accentColor: "#fdba74",
  },
  movie: {
    label: "Movie",
    color: "#6366f1",
    secondaryColor: "#4f46e5",
  },
  sleeping: {
    label: "Sleeping",
    color: "#1e3a8a",
    secondaryColor: "#1e1b4b",
  },
  idle: {
    label: "Idle",
    color: "#6b7280",
    secondaryColor: "#4b5563",
    accentColor: "#374151",
  },
  away: {
    label: "Away",
    color: "#475569",
    secondaryColor: "#334155",
  },
};

/** Dark background base color (from Home Hub's global.css) */
export const BG_BASE = "#08080c";
