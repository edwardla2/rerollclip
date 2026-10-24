"""Browser end-to-end check of the studio (Playwright + Chromium).

Usage: start the server (python3 -m uvicorn web.server:app --port 8765), generate clips with
desktop/scripts/make_test_clips.sh <dir>, then:  python3 web/tests/e2e/drive_studio.py <dir> <shots-dir>
Uploads three clips, splits, trims by dragging a handle, reorders by dragging, plays, exports,
and probes the downloaded MP4.
"""
import sys
import glob, json, subprocess, time
from playwright.sync_api import sync_playwright
CLIPS = sys.argv[1] if len(sys.argv) > 1 else 'test-clips'
S = (sys.argv[2] if len(sys.argv) > 2 else '.') + '/'
files=sorted(glob.glob(CLIPS + '/*.mp4'))
with sync_playwright() as p:
    b=p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
    pg=b.new_page(viewport={'width':1440,'height':900})
    errs=[]; pg.on('console', lambda m: errs.append(m.text) if m.type=='error' else None); pg.on('pageerror', lambda e: errs.append('PAGEERROR '+str(e)))
    pg.goto('http://127.0.0.1:8765/studio'); pg.wait_for_timeout(500)
    pg.screenshot(path=S+'studio-empty.png')
    pg.set_input_files('#file-input', files)
    pg.wait_for_function("document.querySelectorAll('#track .item').length === 3", timeout=30000)
    pg.wait_for_timeout(800)
    print('items:', pg.eval_on_selector_all('#track .item', 'els => els.map(e => e.style.width)'))
    print('timeline label:', pg.inner_text('#tl-count'), '| total tc:', pg.inner_text('#tc-total'))
    pg.screenshot(path=S+'studio-loaded.png')

    # split: click into first clip at ~6s, press S
    track=pg.locator('#track').bounding_box(); zoom=36
    pg.mouse.click(track['x']+6*zoom, track['y']+40)
    pg.keyboard.press('s'); pg.wait_for_timeout(300)
    print('after split:', pg.locator('#track .item').count(), 'clips, total', pg.inner_text('#tc-total'))

    # trim: drag right handle of the selected (2nd half) item left by 2s
    sel=pg.locator('#track .item.is-selected .handle-r').bounding_box()
    pg.mouse.move(sel['x']+5, sel['y']+20); pg.mouse.down(); pg.mouse.move(sel['x']+5-2*zoom, sel['y']+20, steps=8); pg.mouse.up()
    pg.wait_for_timeout(300)
    print('after trim: total', pg.inner_text('#tc-total'), '| selected length field:', pg.input_value('#f-length'))

    # reorder: drag last item to the front
    names_before=pg.eval_on_selector_all('#track .item', 'els => els.map(e => e.title.slice(0,8))')
    last=pg.locator('#track .item').last.bounding_box()
    pg.mouse.move(last['x']+last['width']/2, last['y']+40); pg.mouse.down()
    pg.mouse.move(track['x']+5, last['y']+40, steps=15); pg.mouse.up(); pg.wait_for_timeout(300)
    names_after=pg.eval_on_selector_all('#track .item', 'els => els.map(e => e.title.slice(0,8))')
    print('order before:', names_before); print('order after: ', names_after)

    # play a bit: the playhead must advance through the sequence
    pg.keyboard.press('Home'); pg.wait_for_timeout(300)
    pg.click('#play'); pg.wait_for_timeout(2500)
    tnow=pg.inner_text('#tc-now'); pg.screenshot(path=S+'studio-playing.png'); pg.click('#play')
    print('timecode after 2.5s playing:', tnow)

    # crop layout + 720 output, then export
    pg.click('.rail-btn[data-pane="format"]'); pg.click('.seg [data-layout="center_crop"]'); pg.click('#size-seg [data-size="720"]')
    pg.click('#export-open')
    pg.wait_for_selector('#download:not([hidden])', timeout=180000)
    pg.wait_for_timeout(1500)
    pg.screenshot(path=S+'studio-exported.png')
    href=pg.get_attribute('#download','href')
    print('result meta:', pg.inner_text('#result-meta'))
    data=pg.request.get('http://127.0.0.1:8765'+href).body()
    open(S+'studio-export.mp4','wb').write(data)
    print('console errors:', errs)
    b.close()
probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',S+'studio-export.mp4'],capture_output=True,text=True)
print(probe.stdout)
