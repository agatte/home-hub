import React from "react";
import { Composition } from "remotion";
import { GamingBackground } from "./compositions/GamingBackground";

/**
 * Root component — registers all background compositions.
 * Each composition renders a seamless looping background video
 * for a specific Home Hub mode.
 *
 * Standard settings:
 *   1920x1080, 30fps, 20 seconds (600 frames)
 *
 * Add new compositions here as you build them.
 */

const FPS = 30;
const DURATION_SECONDS = 20;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="GamingBackground"
        component={GamingBackground}
        durationInFrames={FPS * DURATION_SECONDS}
        fps={FPS}
        width={1920}
        height={1080}
      />
      {/* Add more compositions as you build them:
      <Composition
        id="WorkingBackground"
        component={WorkingBackground}
        durationInFrames={FPS * DURATION_SECONDS}
        fps={FPS}
        width={1920}
        height={1080}
      />
      */}
    </>
  );
};
