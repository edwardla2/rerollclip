"use client";

import type { CSSProperties } from "react";
import {
  Easing,
  getRemotionEnvironment,
  interpolate,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/**
 * A "phone stack": phone screens rise out of a blur from below, one after
 * another, and each new one pushes the stack back — the older screens shrink
 * and step up so only their tops peek out above the newest, which settles in
 * front. Every screen plays its own clip under an iOS status bar.
 *
 * Proportions were measured off a two-screen reference recording (716 × 398,
 * 30fps) by tracking each screen's Dynamic Island: a screen one step back is
 * 0.83× the size and its top sits 24.6 reference px higher. The rise is the
 * reference's long ease-out. Lengths are reference pixels (`REF_W` wide) and
 * scale with the frame.
 *
 * Like `announce-title` it paints a world rather than a surface — a cream page
 * with a lavender glow — so it takes no `theme`/`mode`; its colours are props.
 */

export interface PhoneStackProps {
  /**
   * One clip per screen, in the order they arrive. Video URLs play muted;
   * images show as stills. Absolute URLs or paths under `public/`.
   */
  videos?: string[];
  /** Frames between one screen arriving and the next. */
  stagger?: number;
  /** The page. */
  background?: string;
  /** The glow the stack rises out of. */
  glowColor?: string;
  /** The status bar's ink over the clips. */
  statusColor?: string;
  /** The time in the status bar. */
  time?: string;
  speed?: number;
  className?: string;
}

/** Creator-style clips, 12s each. Absolute, because a root-relative default
 *  becomes `staticFile()` in a render and 404s in the project this file was
 *  just copied into. */
const DEFAULT_VIDEOS = [2, 3, 4, 5, 6].map(
  (n) => `https://media.snapcn.dev/demos/stock/wall-${n}.mp4`,
);

// ─── Geometry, in reference pixels ────────────────────────────────────────────
export const REF_W = 716;
const REF_H = 398;
/** The front screen at rest: width, top edge, centre line. */
export const SCREEN = { w: 240, top: 74, cx: 358, radius: 26 } as const;
/** Each step back: the size it keeps, and how far its top climbs (at scale 1). */
export const STEP_SCALE = 0.83;
export const STEP_RISE = 24.6;
/** Screens deeper than this fade out as the next one arrives. */
const DEPTH = 3;
/** An arriving screen starts below the frame, larger, blurred and clear. */
const ENTER = { top: 400, scale: 1.12, blur: 9 } as const;

// ─── Timeline (30fps frames) ──────────────────────────────────────────────────
/** One arrival or one step back. */
export const MOVE = 26;
const RISE = Easing.bezier(0.16, 1, 0.3, 1);

/** Where a screen sits `depth` steps back: scale and top edge. */
function slot(depth: number) {
  const scale = STEP_SCALE ** depth;
  let top = SCREEN.top;
  for (let d = 1; d <= depth; d++) top -= STEP_RISE * STEP_SCALE ** (d - 1);
  return { scale, top };
}

function resolveSrc(src: string): string {
  const isLocal = src.startsWith("/") && !src.startsWith("//");
  if (!isLocal || getRemotionEnvironment().isPlayer) return src;
  // A value that already came out of staticFile() carries the static base.
  const base = staticFile("_").slice(0, -2);
  if (base && src.startsWith(`${base}/`)) return src;
  try {
    return staticFile(src.replace(/^\/+/, ""));
  } catch {
    return src;
  }
}

const isVideoSrc = (src: string) => /\.(mp4|webm|mov|m4v)(?:[?#]|$)/i.test(src);

const cover: CSSProperties = {
  position: "absolute",
  inset: 0,
  width: "100%",
  height: "100%",
  maxWidth: "none",
  objectFit: "cover",
};

/** Signal, Wi-Fi and battery, drawn in `currentColor`. */
function StatusIcons({ h }: { h: number }) {
  return (
    <svg
      height={h}
      viewBox="0 0 68 12"
      fill="currentColor"
      aria-hidden
      style={{ display: "block" }}
    >
      <rect x="0" y="8" width="3" height="4" rx="1" />
      <rect x="5" y="6" width="3" height="6" rx="1" />
      <rect x="10" y="3.5" width="3" height="8.5" rx="1" />
      <rect x="15" y="1" width="3" height="11" rx="1" />
      <path d="M31 2.2c2.6 0 5 1 6.8 2.7l-1.3 1.4A7.9 7.9 0 0 0 31 4.1a7.9 7.9 0 0 0-5.5 2.2l-1.3-1.4A9.8 9.8 0 0 1 31 2.2Zm0 3.8c1.6 0 3 .6 4.1 1.6L33.8 9a3.9 3.9 0 0 0-5.6 0l-1.3-1.4A5.8 5.8 0 0 1 31 6Zm0 3.7 1.6 1.7L31 12l-1.6-1.6L31 9.7Z" />
      <rect
        x="43.5"
        y="1.5"
        width="21"
        height="9"
        rx="2.6"
        fill="none"
        stroke="currentColor"
        opacity="0.45"
      />
      <rect x="45.5" y="3.5" width="17" height="5" rx="1.3" />
      <rect x="65.5" y="4.3" width="1.6" height="3.4" rx="0.8" opacity="0.45" />
    </svg>
  );
}

export function PhoneStack({
  videos = DEFAULT_VIDEOS,
  stagger = 14,
  background = "#f3f3ee",
  glowColor = "#cdb4e6",
  statusColor = "#ffffff",
  time = "9:41",
  speed = 1,
  className,
}: PhoneStackProps) {
  const { width, height, fps } = useVideoConfig();
  const tick = (speed * 30) / fps;
  const frame = useCurrentFrame() * tick;
  const u = width / REF_W;
  const dy = (height - REF_H * u) / 2;
  const n = videos.length;

  // How far a screen has come: 0 below the frame, 1 in front, 2 one step
  // back, … — every arrival after it adds one, on the same eased curve.
  const progress = (i: number) => {
    let p = 0;
    for (let k = i; k < n; k++) {
      p += interpolate(frame, [k * stagger, k * stagger + MOVE], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: RISE,
      });
    }
    return p;
  };

  return (
    <div
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        backgroundColor: background,
      }}
    >
      {/* The glow the stack rises out of. */}
      <div
        style={{
          position: "absolute",
          left: "50%",
          bottom: -0.55 * height,
          width: 1.5 * width,
          height: 1.1 * height,
          transform: "translateX(-50%)",
          borderRadius: "50%",
          background: glowColor,
          opacity: 0.55,
          filter: `blur(${70 * u}px)`,
        }}
      />

      {videos.map((src, i) => {
        const p = progress(i);
        if (p <= 0) return null;
        // 0 → 1: the rise. Past 1: steps back, one per later arrival.
        const enter = Math.min(p, 1);
        const depth = Math.max(p - 1, 0);
        const lo = slot(Math.floor(depth));
        const hi = slot(Math.floor(depth) + 1);
        const f = depth - Math.floor(depth);
        const scale =
          enter < 1
            ? ENTER.scale + (1 - ENTER.scale) * enter
            : lo.scale + (hi.scale - lo.scale) * f;
        const top =
          enter < 1
            ? ENTER.top + (SCREEN.top - ENTER.top) * enter
            : lo.top + (hi.top - lo.top) * f;
        const blur = ENTER.blur * (1 - enter);
        const opacity =
          Math.min(1, enter * 2.5) *
          interpolate(depth, [DEPTH - 1, DEPTH], [1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
        if (opacity <= 0) return null;

        const w = SCREEN.w * scale * u;
        const h = w * (852 / 393);
        const island = { w: 0.32 * w, h: 0.094 * w, top: 0.028 * w };
        const resolved = resolveSrc(src);
        return (
          <div
            key={`${i}-${src}`}
            style={{
              position: "absolute",
              left: SCREEN.cx * u - w / 2,
              top: dy + top * u,
              width: w,
              height: h,
              borderRadius: SCREEN.radius * scale * u,
              overflow: "hidden",
              backgroundColor: "#ffffff",
              boxShadow: `0 ${8 * u}px ${28 * u}px rgba(70, 50, 110, 0.14), 0 0 0 ${0.6 * u}px rgba(255, 255, 255, 0.9)`,
              opacity,
              filter: blur > 0.05 ? `blur(${blur * u}px)` : undefined,
              zIndex: i,
            }}
          >
            {isVideoSrc(src) ? (
              <Sequence from={Math.floor((i * stagger) / tick)} layout="none">
                <OffthreadVideo src={resolved} muted style={cover} />
              </Sequence>
            ) : (
              // biome-ignore lint/performance/noImgElement: Remotion still
              <img src={resolved} alt="" style={cover} />
            )}
            {/* Status bar and Dynamic Island over the clip. */}
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                top: 0,
                height: island.top * 2 + island.h,
                background:
                  "linear-gradient(to bottom, rgba(0,0,0,0.28), rgba(0,0,0,0))",
              }}
            />
            <div
              style={{
                position: "absolute",
                left: "50%",
                top: island.top,
                width: island.w,
                height: island.h,
                transform: "translateX(-50%)",
                borderRadius: island.h / 2,
                background: "#000000",
              }}
            />
            <div
              style={{
                position: "absolute",
                left: 0.09 * w,
                top: island.top,
                height: island.h,
                display: "flex",
                alignItems: "center",
                color: statusColor,
                fontFamily:
                  '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif',
                fontWeight: 600,
                fontSize: 0.045 * w,
              }}
            >
              {time}
            </div>
            <div
              style={{
                position: "absolute",
                right: 0.07 * w,
                top: island.top,
                height: island.h,
                display: "flex",
                alignItems: "center",
                color: statusColor,
              }}
            >
              <StatusIcons h={0.034 * w} />
            </div>
          </div>
        );
      })}

      {/* The stack's foot fades into the page and the glow. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: 0.38 * height,
          background: `linear-gradient(to bottom, transparent 0%, color-mix(in srgb, ${background} 55%, transparent) 60%, ${background} 100%)`,
          zIndex: 100,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: "50%",
          bottom: -0.45 * height,
          width: 1.1 * width,
          height: 0.7 * height,
          transform: "translateX(-50%)",
          borderRadius: "50%",
          background: glowColor,
          opacity: 0.35,
          filter: `blur(${60 * u}px)`,
          zIndex: 101,
        }}
      />
    </div>
  );
}
