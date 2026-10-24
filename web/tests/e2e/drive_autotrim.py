"""Browser check of Auto-trim all. Generate clips with planted moments first:
python3 -c "from pathlib import Path; from tests.test_analysis import make_clip; make_clip(Path('m/1.mp4'),24,[17.0]); make_clip(Path('m/2.mp4'),20,[5.0])"
then: python3 web/tests/e2e/drive_autotrim.py m <shots-dir>   (server on :8765)
"""
import sys
import glob
from playwright.sync_api import sync_playwright
S = (sys.argv[2] if len(sys.argv) > 2 else '.') + '/'
files=sorted(glob.glob((sys.argv[1] if len(sys.argv) > 1 else 'moments') + '/*.mp4'))
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':1440,'height':900})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e))); pg.on('console', lambda m: errs.append(m.text) if m.type=='error' else None)
    pg.goto('http://127.0.0.1:8765/studio')
    pg.set_input_files('#file-input', files)
    pg.wait_for_function("document.querySelectorAll('#track .item').length === 2", timeout=30000)
    pg.click('#auto-trim-all')
    pg.wait_for_function("document.querySelectorAll('#track .item.is-suggested').length === 2", timeout=60000)
    pg.wait_for_timeout(400)
    print('timeline:', pg.inner_text('#tl-count'))
    for i in range(2):
        pg.locator('#track .item').nth(i).click(position={'x':10,'y':40}); pg.wait_for_timeout(150)
        print(pg.inner_text('#clip-name')[:22], 'start', pg.input_value('#f-start'), 'end', pg.input_value('#f-end'))
    print('toast:', pg.inner_text('#toast'))
    pg.screenshot(path=S+'studio-autotrim.png')
    print('errors:', errs); b.close()
