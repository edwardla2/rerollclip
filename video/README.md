# Launch video scenes (Remotion)

`PhoneStackScene`: the four plays of the vertical edit (renders/v007) rising in as phone screens,
built on snapcn's Phone Stack (`src/components/snap-cn/phone-stack`, MIT, see LICENSE-snapcn.txt;
copied from github.com/snapcndev/snapcn, same file `npx shadcn@latest add @snapcn/phone-stack` adds).

    npm install
    # clips: four segments of renders/v007/edit.mp4 cut to public/clips/play1..4.mp4 (not committed)
    npx remotion studio
    npx remotion render PhoneStackScene out/phone-stack.mp4

The rest of the launch video (type scenes, the app, the edit, end card) is composited with
ffmpeg; this scene is spliced in after "Reroll that".
