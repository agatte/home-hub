import React, { useMemo } from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
} from "remotion";

/**
 * Gaming mode background — neon pixel cityscape with LoL-inspired
 * minion waves, projectiles, and spell effects.
 *
 * Features:
 *  - Deep purple sky with nebula glow patches
 *  - Twinkling stars
 *  - City skyline with multi-color windows, antennae, blinking lights
 *  - Stronger neon bloom along skyline edge
 *  - Perspective grid floor with depth
 *  - Minion waves marching across the ground with health bars
 *  - Projectile orbs and impact bursts
 *  - Data streams, floating particles, CRT scanlines
 *
 * 480×270 pixel art scaled 4× to 1920×1080.
 * 30fps, 20 seconds (600 frames), seamless loop.
 */

const PW = 480;
const PH = 270;
const HORIZON_Y = 0.62;

// --- Palette ---
const SKY_DARK = "#05010d";
const SKY_MID = "#0d0428";
const NEBULA_PURPLE = "#4c1d95";
const NEBULA_PINK = "#7c3aed";
const NEON_PRIMARY = "#a855f7";
const NEON_ACCENT = "#c084fc";
const NEON_HOT = "#e879f9";
const NEON_BLUE = "#6366f1";
const NEON_CYAN = "#22d3ee";
const BUILDING_DARK = "#08030f";
const BUILDING_MID = "#0c0518";
const GRID_COLOR = "#7c3aed";

// Window color palette — multi-color
const WINDOW_COLORS = {
  purple: { lit: "#a855f7", dim: "#1a0a35" },
  blue: { lit: "#6366f1", dim: "#0f0a2a" },
  pink: { lit: "#e879f9", dim: "#1a0a25" },
  warm: { lit: "#fbbf24", dim: "#1a1408" },
};
const WINDOW_TYPES = Object.keys(WINDOW_COLORS) as Array<keyof typeof WINDOW_COLORS>;

// --- Seeded random ---
function seededRandom(seed: number) {
  let s = seed;
  return () => {
    s = (s * 16807 + 0) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

// --- Buildings: varied proportions, roof caps, sparse windows ---
interface Building {
  x: number;
  width: number;
  height: number;
  color: string;
  // Roof cap: a narrower piece sitting on top for visual variety
  roofCapWidth: number;   // 0 = no cap
  roofCapHeight: number;
  hasAntenna: boolean;
  antennaHeight: number;
  windows: Array<{
    wx: number;       // relative to building left edge
    wy: number;       // relative to building top
    lit: boolean;
    colorType: keyof typeof WINDOW_COLORS;
    toggleFrame: number;
  }>;
}

function generateSkyline(): Building[] {
  const rand = seededRandom(777);
  const buildings: Building[] = [];
  let x = 0;

  while (x < PW + 20) {
    // Wide variety: thin towers (5px) to wide blocks (30px)
    const widthType = rand();
    let width: number;
    let height: number;
    if (widthType < 0.2) {
      // Thin tower
      width = 5 + Math.floor(rand() * 5);
      height = 50 + Math.floor(rand() * 50);
    } else if (widthType < 0.5) {
      // Medium building
      width = 12 + Math.floor(rand() * 12);
      height = 30 + Math.floor(rand() * 50);
    } else if (widthType < 0.75) {
      // Wide low building
      width = 20 + Math.floor(rand() * 15);
      height = 20 + Math.floor(rand() * 30);
    } else {
      // Tall skyscraper
      width = 10 + Math.floor(rand() * 16);
      height = 60 + Math.floor(rand() * 40);
    }

    const color = rand() > 0.6 ? BUILDING_DARK : BUILDING_MID;

    // Roof cap — narrower section on top (40% of buildings)
    let roofCapWidth = 0;
    let roofCapHeight = 0;
    if (width > 10 && rand() > 0.6) {
      roofCapWidth = Math.floor(width * (0.3 + rand() * 0.3));
      roofCapHeight = 4 + Math.floor(rand() * 8);
    }

    const totalHeight = height + roofCapHeight;
    const hasAntenna = totalHeight > 55 && rand() > 0.5;
    const antennaHeight = hasAntenna ? 4 + Math.floor(rand() * 10) : 0;

    // Sparse windows — only ~10% lit, positioned inside the main body
    const windows: Building["windows"] = [];
    const windowCols = Math.floor((width - 3) / 4);
    const windowRows = Math.floor((height - 4) / 5);
    for (let row = 0; row < windowRows; row++) {
      for (let col = 0; col < windowCols; col++) {
        const lit = rand() > 0.90; // ~10% lit
        const toggleFrame = rand() > 0.96
          ? 60 + Math.floor(rand() * 480)
          : 0;
        windows.push({
          wx: 2 + col * 4,
          wy: roofCapHeight + 3 + row * 5,
          lit,
          colorType: WINDOW_TYPES[Math.floor(rand() * WINDOW_TYPES.length)],
          toggleFrame,
        });
      }
    }

    buildings.push({
      x, width, height, color,
      roofCapWidth, roofCapHeight,
      hasAntenna, antennaHeight, windows,
    });
    x += width + 1 + Math.floor(rand() * 6);
  }
  return buildings;
}

const BUILDINGS = generateSkyline();

// --- Stars ---
const STARS = (() => {
  const rand = seededRandom(123);
  return Array.from({ length: 60 }, () => ({
    x: Math.floor(rand() * PW),
    y: Math.floor(rand() * PH * 0.3),
    size: rand() > 0.9 ? 2 : 1,
    phase: rand() * Math.PI * 2,
    speed: 0.8 + rand() * 1.5,
  }));
})();

// --- Floating particles ---
const PARTICLES = Array.from({ length: 25 }, (_, i) => {
  const rand = seededRandom(i * 31 + 500);
  return {
    baseX: rand() * 100,
    startY: 55 + rand() * 30,
    wobbleAmp: 1 + rand() * 3,
    wobbleSpeed: 0.3 + rand() * 0.8,
    phase: rand() * Math.PI * 2,
    colorIdx: Math.floor(rand() * 3),
    lifetime: 150 + Math.floor(rand() * 250),
    size: 1 + Math.floor(rand() * 2),
  };
});
const PARTICLE_COLORS = [NEON_PRIMARY, NEON_ACCENT, NEON_HOT];

// --- Data streams ---
const DATA_STREAMS = Array.from({ length: 6 }, (_, i) => {
  const rand = seededRandom(i * 97 + 200);
  return {
    x: 10 + rand() * 80,
    width: 1 + Math.floor(rand() * 2),
    speed: 0.5 + rand() * 1.0,
    phase: rand() * Math.PI * 2,
    color: rand() > 0.5 ? NEON_PRIMARY : NEON_BLUE,
  };
});

// --- Minion sprite data (8×8 pixel creatures) ---
// Purple team minion — hooded caster style
const MINION_PURPLE_FRAMES = [
  // Frame 0: step left
  [
    [0,0,0,1,1,0,0,0],
    [0,0,1,1,1,1,0,0],
    [0,0,1,0,0,1,0,0],
    [0,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,0,0],
    [0,0,0,1,1,0,0,0],
    [0,0,1,0,0,1,0,0],
    [0,1,0,0,0,0,1,0],
  ],
  // Frame 1: step right
  [
    [0,0,0,1,1,0,0,0],
    [0,0,1,1,1,1,0,0],
    [0,0,1,0,0,1,0,0],
    [0,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,0,0],
    [0,0,0,1,1,0,0,0],
    [0,0,0,1,1,0,0,0],
    [0,0,1,0,0,1,0,0],
  ],
];

// Blue team minion — bulkier melee style
const MINION_BLUE_FRAMES = [
  [
    [0,0,1,1,1,1,0,0],
    [0,1,1,1,1,1,1,0],
    [0,1,0,1,1,0,1,0],
    [0,0,1,1,1,1,0,0],
    [0,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,0,0],
    [0,0,1,0,0,1,0,0],
    [0,1,0,0,0,0,1,0],
  ],
  [
    [0,0,1,1,1,1,0,0],
    [0,1,1,1,1,1,1,0],
    [0,1,0,1,1,0,1,0],
    [0,0,1,1,1,1,0,0],
    [0,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,0,0],
    [0,0,0,1,1,0,0,0],
    [0,0,1,0,0,1,0,0],
  ],
];

// --- Minion wave configs ---
interface Minion {
  startX: number;
  speed: number;
  team: "purple" | "blue";
  yOffset: number;
  health: number; // 0-1
  walkPhaseOffset: number;
}

const MINION_WAVES: Minion[] = (() => {
  const rand = seededRandom(999);
  const minions: Minion[] = [];

  // Purple team — "top lane" (closer to horizon, smaller/further away feel)
  // Spread across 3 rows with generous spacing
  for (let i = 0; i < 4; i++) {
    minions.push({
      startX: -20 - i * 40,       // wider spacing between minions
      speed: 0.22 + rand() * 0.06,
      team: "purple",
      yOffset: 10 + (i % 2) * 6 + Math.floor(rand() * 3), // rows 10-19px below horizon
      health: 0.4 + rand() * 0.6,
      walkPhaseOffset: Math.floor(rand() * 10),
    });
  }

  // Blue team — "bottom lane" (closer to camera, larger feel)
  for (let i = 0; i < 4; i++) {
    minions.push({
      startX: PW + 20 + i * 45,
      speed: -(0.22 + rand() * 0.06),
      team: "blue",
      yOffset: 35 + (i % 2) * 8 + Math.floor(rand() * 3), // rows 35-46px below horizon
      health: 0.4 + rand() * 0.6,
      walkPhaseOffset: Math.floor(rand() * 10),
    });
  }

  // Straggler purple minion in the mid lane
  minions.push({
    startX: -120,
    speed: 0.18,
    team: "purple",
    yOffset: 24 + Math.floor(rand() * 4),
    health: 0.3 + rand() * 0.3,
    walkPhaseOffset: 5,
  });

  // Straggler blue minion in the mid lane
  minions.push({
    startX: PW + 80,
    speed: -0.2,
    team: "blue",
    yOffset: 22 + Math.floor(rand() * 4),
    health: 0.6 + rand() * 0.3,
    walkPhaseOffset: 3,
  });

  return minions;
})();

// --- Projectiles ---
interface Projectile {
  startFrame: number;
  startX: number;
  startY: number;
  vx: number;
  vy: number;
  duration: number;
  color: string;
  size: number;
  impactSize: number;
}

const PROJECTILES: Projectile[] = (() => {
  const rand = seededRandom(555);
  const projs: Projectile[] = [];
  const horizonPx = PH * HORIZON_Y;
  const colors = [NEON_PRIMARY, NEON_HOT, NEON_BLUE, NEON_CYAN];

  // Generate projectiles spread across the 600-frame loop
  for (let i = 0; i < 12; i++) {
    const goingRight = rand() > 0.5;
    const baseY = horizonPx + 8 + rand() * 20;
    projs.push({
      startFrame: Math.floor(rand() * 580),
      startX: goingRight ? 50 + rand() * 150 : PW - 50 - rand() * 150,
      startY: baseY,
      vx: goingRight ? 1.5 + rand() * 2 : -(1.5 + rand() * 2),
      vy: -0.3 + rand() * 0.6,
      duration: 20 + Math.floor(rand() * 25),
      color: colors[Math.floor(rand() * colors.length)],
      size: 2 + Math.floor(rand() * 2),
      impactSize: 4 + Math.floor(rand() * 4),
    });
  }
  return projs;
})();

// --- Grid config ---
const GRID_ROWS = 14;
const GRID_COLS = 18;

export const GamingBackground: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const time = frame / fps;
  const progress = frame / durationInFrames;
  const angle = progress * Math.PI * 2;
  const horizonPx = PH * HORIZON_Y;
  const floorHeight = PH - horizonPx;

  const gridScroll = (frame * 0.4) % 30;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: PW,
          height: PH,
          transform: "scale(4)",
          transformOrigin: "top left",
          imageRendering: "pixelated",
          overflow: "hidden",
        }}
      >
        {/* === SKY === */}
        <AbsoluteFill
          style={{
            background: `linear-gradient(to bottom, ${SKY_DARK} 0%, ${SKY_MID} 40%, #150835 65%, #1a0638 100%)`,
          }}
        />

        {/* Nebula glow patches */}
        <div
          style={{
            position: "absolute",
            left: "12%",
            top: "3%",
            width: "45%",
            height: "38%",
            background: `radial-gradient(ellipse, ${NEBULA_PURPLE}45 0%, transparent 70%)`,
            opacity: interpolate(Math.sin(angle * 0.8), [-1, 1], [0.4, 0.85]),
          }}
        />
        <div
          style={{
            position: "absolute",
            left: "55%",
            top: "6%",
            width: "38%",
            height: "28%",
            background: `radial-gradient(ellipse, ${NEBULA_PINK}35 0%, transparent 70%)`,
            opacity: interpolate(Math.sin(angle * 0.6 + 1), [-1, 1], [0.3, 0.75]),
          }}
        />

        {/* Stars */}
        {STARS.map((s, i) => {
          const twinkle = Math.sin(time * s.speed + s.phase) * 0.5 + 0.5;
          if (twinkle < 0.25) return null;
          return (
            <div
              key={`star-${i}`}
              style={{
                position: "absolute",
                left: s.x,
                top: s.y,
                width: s.size,
                height: s.size,
                backgroundColor: "#fff",
                opacity: twinkle,
              }}
            />
          );
        })}

        {/* Data streams behind buildings */}
        {DATA_STREAMS.map((ds, i) => {
          const beamOpacity = interpolate(
            Math.sin(angle * ds.speed + ds.phase),
            [-1, 1],
            [0.04, 0.15]
          );
          const beamHeight = interpolate(
            Math.sin(angle * ds.speed * 0.7 + ds.phase),
            [-1, 1],
            [25, 55]
          );
          return (
            <div
              key={`ds-${i}`}
              style={{
                position: "absolute",
                left: `${ds.x}%`,
                bottom: floorHeight,
                width: ds.width,
                height: beamHeight,
                backgroundColor: ds.color,
                opacity: beamOpacity,
              }}
            />
          );
        })}

        {/* === CITY SKYLINE === */}
        {BUILDINGS.map((b, bi) => {
          const totalH = b.height + b.roofCapHeight;
          const buildingTop = horizonPx - totalH;
          const bodyTop = horizonPx - b.height; // where the main body starts
          const capLeft = b.x + Math.floor((b.width - b.roofCapWidth) / 2);

          return (
            <React.Fragment key={`bldg-${bi}`}>
              {/* Main building body */}
              <div
                style={{
                  position: "absolute",
                  left: b.x,
                  top: bodyTop,
                  width: b.width,
                  height: b.height,
                  backgroundColor: b.color,
                }}
              />
              {/* Roof accent line on main body */}
              <div
                style={{
                  position: "absolute",
                  left: b.x,
                  top: bodyTop,
                  width: b.width,
                  height: 1,
                  backgroundColor: NEON_PRIMARY,
                  opacity: 0.15,
                }}
              />

              {/* Roof cap (narrower section on top) */}
              {b.roofCapWidth > 0 && (
                <>
                  <div
                    style={{
                      position: "absolute",
                      left: capLeft,
                      top: buildingTop,
                      width: b.roofCapWidth,
                      height: b.roofCapHeight,
                      backgroundColor: b.color,
                    }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      left: capLeft,
                      top: buildingTop,
                      width: b.roofCapWidth,
                      height: 1,
                      backgroundColor: NEON_PRIMARY,
                      opacity: 0.2,
                    }}
                  />
                </>
              )}

              {/* Antenna */}
              {b.hasAntenna && (
                <>
                  <div
                    style={{
                      position: "absolute",
                      left: b.x + Math.floor(b.width / 2),
                      top: buildingTop - b.antennaHeight,
                      width: 1,
                      height: b.antennaHeight,
                      backgroundColor: "#1a0a30",
                    }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      left: b.x + Math.floor(b.width / 2),
                      top: buildingTop - b.antennaHeight - 1,
                      width: 1,
                      height: 1,
                      backgroundColor: "#ef4444",
                      opacity: Math.sin(time * 2 + bi) > 0.3 ? 0.9 : 0.15,
                    }}
                  />
                </>
              )}

              {/* Sparse windows — relative to building position */}
              {b.windows.map((w, wi) => {
                const isLit = w.toggleFrame > 0 && frame >= w.toggleFrame
                  ? !w.lit
                  : w.lit;
                if (!isLit) return null;
                const colors = WINDOW_COLORS[w.colorType];
                return (
                  <div
                    key={`w-${bi}-${wi}`}
                    style={{
                      position: "absolute",
                      left: b.x + w.wx,
                      top: buildingTop + w.wy,
                      width: 2,
                      height: 3,
                      backgroundColor: colors.lit,
                      opacity: 0.75,
                    }}
                  />
                );
              })}
            </React.Fragment>
          );
        })}

        {/* Skyline neon bloom — stronger pulsing glow */}
        <div
          style={{
            position: "absolute",
            left: 0,
            top: horizonPx - 50,
            width: PW,
            height: 60,
            background: `linear-gradient(to top, ${NEON_PRIMARY}30 0%, ${NEON_PRIMARY}10 40%, transparent 100%)`,
            opacity: interpolate(Math.sin(angle * 1.5), [-1, 1], [0.6, 1.0]),
          }}
        />

        {/* === GRID FLOOR === */}
        <div
          style={{
            position: "absolute",
            left: 0,
            top: horizonPx,
            width: PW,
            height: floorHeight,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: `linear-gradient(to bottom, #0a0320 0%, #050110 100%)`,
            }}
          />

          {/* Horizontal grid lines — exponential perspective spacing */}
          {Array.from({ length: GRID_ROWS }, (_, i) => {
            const t = (i + gridScroll / 30) / GRID_ROWS;
            const tClamped = Math.min(t, 1);
            const y = tClamped * tClamped * tClamped * floorHeight;
            const opacity = interpolate(tClamped, [0, 0.3, 1], [0.02, 0.06, 0.25]);
            return (
              <div
                key={`hline-${i}`}
                style={{
                  position: "absolute",
                  left: 0,
                  top: y,
                  width: PW,
                  height: 1,
                  backgroundColor: GRID_COLOR,
                  opacity,
                }}
              />
            );
          })}

          {/* Vertical grid lines — converge to vanishing point */}
          {Array.from({ length: GRID_COLS + 1 }, (_, i) => {
            const t = i / GRID_COLS;
            const topX = PW * 0.5 + (t - 0.5) * PW * 0.12;
            const botX = t * PW;
            const topXr = topX + 1;
            const botXr = botX + 1;
            return (
              <div
                key={`vline-${i}`}
                style={{
                  position: "absolute",
                  inset: 0,
                  backgroundColor: GRID_COLOR,
                  opacity: 0.07,
                  clipPath: `polygon(${topX}px 0px, ${topXr}px 0px, ${botXr}px ${floorHeight}px, ${botX}px ${floorHeight}px)`,
                }}
              />
            );
          })}

          {/* Horizon glow line */}
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: PW,
              height: 2,
              backgroundColor: NEON_PRIMARY,
              opacity: interpolate(Math.sin(angle * 2), [-1, 1], [0.25, 0.45]),
            }}
          />
        </div>

        {/* === MINIONS === */}
        {MINION_WAVES.map((m, mi) => {
          // Position wraps for seamless loop
          const rawX = m.startX + frame * m.speed;
          const wrapRange = PW + 80; // wider wrap so they don't pop in at edge
          const x = ((rawX % wrapRange) + wrapRange) % wrapRange - 40;

          const baseY = horizonPx + m.yOffset;
          const walkFrame = (Math.floor(frame / 10) + m.walkPhaseOffset) % 2;

          const frames = m.team === "purple" ? MINION_PURPLE_FRAMES : MINION_BLUE_FRAMES;
          const spriteData = frames[walkFrame];
          const bodyColor = m.team === "purple" ? NEON_PRIMARY : NEON_BLUE;
          const hpColor = m.team === "purple" ? "#a855f7" : "#6366f1";
          const hpBg = "#1a0a20";

          // Skip if off screen
          if (x < -10 || x > PW + 10) return null;

          const pixels = [];
          for (let py = 0; py < spriteData.length; py++) {
            for (let px = 0; px < spriteData[py].length; px++) {
              if (spriteData[py][px]) {
                pixels.push(
                  <div
                    key={`m${mi}-${py}-${px}`}
                    style={{
                      position: "absolute",
                      left: Math.floor(x) + px,
                      top: baseY + py,
                      width: 1,
                      height: 1,
                      backgroundColor: bodyColor,
                    }}
                  />
                );
              }
            }
          }

          return (
            <React.Fragment key={`minion-${mi}`}>
              {pixels}
              {/* Health bar background */}
              <div
                style={{
                  position: "absolute",
                  left: Math.floor(x) + 1,
                  top: baseY - 3,
                  width: 6,
                  height: 2,
                  backgroundColor: hpBg,
                }}
              />
              {/* Health bar fill */}
              <div
                style={{
                  position: "absolute",
                  left: Math.floor(x) + 1,
                  top: baseY - 3,
                  width: Math.max(1, Math.floor(6 * m.health)),
                  height: 2,
                  backgroundColor: m.health > 0.5 ? hpColor : "#ef4444",
                }}
              />
            </React.Fragment>
          );
        })}

        {/* === PROJECTILES === */}
        {PROJECTILES.map((p, pi) => {
          const localFrame = frame - p.startFrame;
          // Handle wrap-around for seamless loop
          const adjustedLocal = localFrame >= 0
            ? localFrame
            : localFrame + durationInFrames;

          if (adjustedLocal < 0 || adjustedLocal > p.duration + 8) return null;

          const x = p.startX + p.vx * Math.min(adjustedLocal, p.duration);
          const y = p.startY + p.vy * Math.min(adjustedLocal, p.duration);

          // Impact burst phase
          const isImpact = adjustedLocal > p.duration;
          const impactProgress = (adjustedLocal - p.duration) / 8;

          if (isImpact) {
            // Expanding ring burst
            const burstSize = p.impactSize * (1 + impactProgress * 2);
            const burstAlpha = 1 - impactProgress;
            return (
              <React.Fragment key={`proj-${pi}`}>
                <div
                  style={{
                    position: "absolute",
                    left: Math.floor(x) - Math.floor(burstSize / 2),
                    top: Math.floor(y) - Math.floor(burstSize / 2),
                    width: Math.floor(burstSize),
                    height: Math.floor(burstSize),
                    backgroundColor: p.color,
                    opacity: burstAlpha * 0.6,
                  }}
                />
                {/* Inner bright core */}
                <div
                  style={{
                    position: "absolute",
                    left: Math.floor(x) - 1,
                    top: Math.floor(y) - 1,
                    width: 2,
                    height: 2,
                    backgroundColor: "#fff",
                    opacity: burstAlpha * 0.8,
                  }}
                />
              </React.Fragment>
            );
          }

          // Flying projectile
          return (
            <React.Fragment key={`proj-${pi}`}>
              {/* Glow halo */}
              <div
                style={{
                  position: "absolute",
                  left: Math.floor(x) - p.size,
                  top: Math.floor(y) - p.size,
                  width: p.size * 3,
                  height: p.size * 3,
                  backgroundColor: p.color,
                  opacity: 0.25,
                }}
              />
              {/* Core */}
              <div
                style={{
                  position: "absolute",
                  left: Math.floor(x),
                  top: Math.floor(y),
                  width: p.size,
                  height: p.size,
                  backgroundColor: "#fff",
                  opacity: 0.9,
                }}
              />
              {/* Trail */}
              <div
                style={{
                  position: "absolute",
                  left: Math.floor(x - p.vx * 2),
                  top: Math.floor(y - p.vy * 2),
                  width: 1,
                  height: 1,
                  backgroundColor: p.color,
                  opacity: 0.4,
                }}
              />
            </React.Fragment>
          );
        })}

        {/* Floating neon particles */}
        {PARTICLES.map((p, i) => {
          const cycleFrame = frame % p.lifetime;
          const t = cycleFrame / p.lifetime;
          const x =
            (p.baseX / 100) * PW +
            Math.sin(time * p.wobbleSpeed + p.phase) * p.wobbleAmp;
          const y = (p.startY / 100) * PH - t * PH * 0.45;
          const alpha =
            t < 0.1 ? t / 0.1 : t > 0.75 ? (1 - t) / 0.25 : 1;
          if (alpha < 0.05 || y < 0) return null;
          return (
            <div
              key={`p-${i}`}
              style={{
                position: "absolute",
                left: Math.floor(x),
                top: Math.floor(y),
                width: p.size,
                height: p.size,
                backgroundColor: PARTICLE_COLORS[p.colorIdx],
                opacity: alpha * 0.7,
              }}
            />
          );
        })}

        {/* CRT scanline overlay */}
        <AbsoluteFill style={{ opacity: 0.035, mixBlendMode: "multiply" }}>
          <svg width={PW} height={PH}>
            <defs>
              <pattern
                id="scanlines"
                width="1"
                height="2"
                patternUnits="userSpaceOnUse"
              >
                <rect width="1" height="1" fill="#000" />
                <rect y="1" width="1" height="1" fill="transparent" />
              </pattern>
            </defs>
            <rect width={PW} height={PH} fill="url(#scanlines)" />
          </svg>
        </AbsoluteFill>

        {/* Top vignette */}
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: PW,
            height: PH * 0.25,
            background: `linear-gradient(to bottom, ${SKY_DARK}cc 0%, transparent 100%)`,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
