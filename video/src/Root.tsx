import "./fonts";
import { Composition } from "remotion";
import { PHONE_SCENE_FRAMES, PhoneStackScene } from "./scenes/PhoneStackScene";

export const Root: React.FC = () => (
  <>
    <Composition id="PhoneStackScene" component={PhoneStackScene} durationInFrames={PHONE_SCENE_FRAMES}
                 fps={30} width={1920} height={1080} />
  </>
);
