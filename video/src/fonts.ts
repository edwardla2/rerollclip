import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Reroll's face (Schibsted Grotesk, SIL OFL), from public/fonts.
export const FONT = "Schibsted Grotesk";
loadFont({ family: FONT, url: staticFile("fonts/SchibstedGrotesk-400.ttf"), weight: "400" });
loadFont({ family: FONT, url: staticFile("fonts/SchibstedGrotesk-800.ttf"), weight: "800" });
