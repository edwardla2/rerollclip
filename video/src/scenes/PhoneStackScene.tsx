import { AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame } from "remotion";
import { PhoneStack } from "../components/snap-cn/phone-stack";
import { FONT } from "../fonts";

/** The four plays of the finished vertical edit (renders/v007), one per phone, best play last. */
export const PLAY_CLIPS = [1, 2, 3, 4].map((n) => staticFile(`clips/play${n}.mp4`));
export const STAGGER = 36;          // frames between phones
export const PHONE_SCENE_FRAMES = 210;

const rise = (frame: number, at: number) =>
  interpolate(frame, [at, at + 18], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });

function Line({ text, at, size, weight = 800, color = "#000" }: { text: string; at: number; size: number; weight?: number; color?: string }) {
  const frame = useCurrentFrame();
  return (
    <div style={{ overflow: "hidden", paddingBottom: size * 0.08, marginBottom: -size * 0.08 }}>
      <div style={{ transform: `translateY(${rise(frame, at) * 110}%)`, fontSize: size, fontWeight: weight, color,
                    letterSpacing: weight === 800 ? "-0.05em" : 0, lineHeight: 0.95 }}>{text}</div>
    </div>
  );
}

/** Reroll's mark: a die showing two. */
function Die({ size }: { size: number }) {
  const pip = (x: number, y: number) => (
    <div style={{ position: "absolute", width: size * 0.2, height: size * 0.2, borderRadius: "50%", background: "#fff",
                  left: size * x - size * 0.1, top: size * y - size * 0.1 }} />
  );
  return (
    <div style={{ position: "relative", width: size, height: size, borderRadius: size * 0.24, background: "#000" }}>
      {pip(0.32, 0.32)}{pip(0.68, 0.68)}
    </div>
  );
}

/** "Exports vertical": the plays rise in as phone screens, each one pushing the last back. */
export const PhoneStackScene: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#fff", fontFamily: FONT }}>
    {/* The stack's own glow is clipped to its layer, so the glow is drawn here, unclipped, under it. */}
    <div style={{ position: "absolute", left: 1360 - 1100, bottom: -560, width: 2200, height: 1150, borderRadius: "50%",
                  background: "#dcdcdc", opacity: 0.55, filter: "blur(180px)" }} />
    {/* The stack is centred by design; slide the whole layer right so the words sit on the left. */}
    <AbsoluteFill style={{ transform: "translateX(400px)" }}>
      <PhoneStack videos={PLAY_CLIPS} stagger={STAGGER} background="transparent" glowColor="transparent" statusColor="#ffffff" time="9:41" />
    </AbsoluteFill>
    <div style={{ position: "absolute", left: 96, top: 0, right: 96, height: 92, borderBottom: "2px solid #000",
                  display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 22 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, fontWeight: 800, fontSize: 34, letterSpacing: "-1.2px" }}>
        <Die size={34} />reroll
      </div>
      <div style={{ color: "#6e6e6e" }}>Ready to post</div>
    </div>
    <div style={{ position: "absolute", left: 96, top: 380 }}>
      <Line text="Vertical." at={6} size={120} />
      <Line text="Ready to post." at={14} size={120} />
      <div style={{ height: 34 }} />
      <Line text="Four plays, best one last." at={40} size={34} weight={400} color="#6e6e6e" />
    </div>
  </AbsoluteFill>
);
