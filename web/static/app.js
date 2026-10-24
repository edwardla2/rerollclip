(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const projectId = (() => {
    const old = localStorage.getItem('clipthat_demo_id');
    if (old && /^[0-9a-f]{32}$/.test(old)) return old;
    const v = crypto.randomUUID().replace(/-/g, '');
    localStorage.setItem('clipthat_demo_id', v);
    return v;
  })();
  let clips = [];
  let selected = null;
  let busy = false;
  let latestDownloadUrl = '';

  function toast(message) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.remove('is-hidden');
    clearTimeout(window.clipThatToastTimeout);
    window.clipThatToastTimeout = setTimeout(() => el.classList.add('is-hidden'), 4500);
  }
  function openEditor() {
    $('#landing').classList.add('is-hidden');
    document.querySelectorAll('.section, main footer').forEach((el) => el.classList.add('is-hidden'));
    $('#editor').classList.remove('is-hidden');
    scrollTo({ top: 0, behavior: 'instant' });
    $('#nav-workspace').textContent = 'Editor';
  }
  function openHome() {
    $('#landing').classList.remove('is-hidden');
    document.querySelectorAll('.section, main footer').forEach((el) => el.classList.remove('is-hidden'));
    $('#editor').classList.add('is-hidden');
    $('#nav-workspace').textContent = 'Workspace';
    scrollTo({ top: 0, behavior: 'instant' });
  }
  document.querySelectorAll('.nav-start').forEach((btn) => btn.addEventListener('click', openEditor));
  document.querySelectorAll('.nav-home').forEach((btn) => btn.addEventListener('click', openHome));
  $('#nav-workspace').addEventListener('click', openEditor);
  $('#nav-features').addEventListener('click', () => { openHome(); $('#features').scrollIntoView({ behavior: 'smooth' }); });
  $('#how-it-works').addEventListener('click', () => $('#features').scrollIntoView({ behavior: 'smooth' }));
  $('#back-home').addEventListener('click', openHome);
  $('#desktop-info').addEventListener('click', () => toast('The Tauri desktop companion is being developed separately.'));
  $('#tool-styles').addEventListener('click', () => { $('#preset-select').focus(); toast('Pick a style on the right. Advanced effects are still in development.'); });
  $('#tool-export').addEventListener('click', () => $('#render-button').focus());

  function selectedClip() { return clips.find((clip) => clip.id === selected); }
  function formatTime(seconds) {
    const n = Math.round(Number(seconds) || 0);
    return String(Math.floor(n/60)).padStart(2, '0') + ':' + String(n % 60).padStart(2, '0');
  }
  function currentDuration(clip) {
    return Math.min(120, Math.max(0.1, Number(clip.duration) - Number(clip.start)));
  }
  function setStatus(text, type = '') {
    const el = $('#render-status');
    el.textContent = text;
    el.classList.toggle('error', type === 'error');
    el.classList.toggle('success', type === 'success');
  }
  function hideOutput() {
    latestDownloadUrl = '';
    $('#download-button').classList.add('is-hidden');
    $('#download-button').removeAttribute('href');
  }
  function updatePreview() {
    const clip = selectedClip();
    const video = $('#preview-video');
    if (!clip) {
      video.pause(); video.removeAttribute('src'); video.load();
      video.classList.add('is-hidden'); $('#preview-empty').classList.remove('is-hidden');
      $('#clip-start').disabled = true; $('#clip-duration').disabled = true;
      return;
    }
    video.src = clip.url;
    video.classList.remove('is-hidden');
    $('#preview-empty').classList.add('is-hidden');
    $('#clip-start').disabled = false;
    $('#clip-duration').disabled = false;
    $('#clip-start').value = clip.start;
    $('#clip-start').max = Math.max(0, clip.duration - 0.1);
    $('#clip-duration').value = currentDuration(clip);
    $('#clip-duration').max = Math.min(120, clip.duration - clip.start);
  }
  function showClips() {
    const list = $('#media-list');
    const track = $('#clip-track');
    list.replaceChildren(); track.replaceChildren();
    $('#media-count').textContent = `${clips.length} ${clips.length === 1 ? 'clip' : 'clips'}`;
    $('#total-duration').textContent = formatTime(clips.reduce((sum, clip) => sum + currentDuration(clip), 0)) + ' total';
    if (!clips.length) {
      const message = document.createElement('div'); message.className = 'empty-library'; message.textContent = 'Your uploaded clips will appear here.'; list.append(message);
      const empty = document.createElement('div'); empty.className = 'empty-track'; empty.textContent = 'Your clips will appear on the timeline.'; track.append(empty);
    }
    clips.forEach((clip, index) => {
      const item = document.createElement('div'); item.className = 'media-item' + (clip.id === selected ? ' selected' : '');
      const indexEl = document.createElement('span'); indexEl.className='media-number'; indexEl.textContent = String(index + 1).padStart(2,'0');
      const info = document.createElement('div'); info.className='media-desc';
      const name = document.createElement('strong'); name.textContent = clip.file.name;
      const desc = document.createElement('span'); desc.textContent = `${formatTime(currentDuration(clip))} · ${clip.remote ? 'Uploaded' : 'Local'}`;
      info.append(name, desc);
      const remove = document.createElement('button'); remove.className='media-delete'; remove.title='Remove clip'; remove.textContent='×';
      remove.addEventListener('click', (e) => { e.stopPropagation(); URL.revokeObjectURL(clip.url); clips = clips.filter((c) => c.id !== clip.id); if (selected === clip.id) selected=clips[0]?.id || null; hideOutput(); showClips(); updatePreview(); });
      item.append(indexEl, info, remove); item.addEventListener('click', () => { selected=clip.id; showClips(); updatePreview(); }); list.append(item);
      const block = document.createElement('div'); block.className='track-clip'+(selected===clip.id?' selected':'');
      block.addEventListener('click', () => { selected=clip.id; showClips(); updatePreview(); });
      const blockName = document.createElement('strong'); blockName.textContent=clip.file.name;
      const controls = document.createElement('div'); controls.className='track-actions';
      const time = document.createElement('small'); time.textContent=formatTime(currentDuration(clip));
      for (const [label, change] of [['↑',-1],['↓',1]]) {
        const btn=document.createElement('button'); btn.textContent=label; btn.title=change<0?'Move left':'Move right';
        btn.disabled = index+change<0 || index+change>=clips.length;
        btn.addEventListener('click', (e) => {e.stopPropagation(); const j=index+change; [clips[index],clips[j]]=[clips[j],clips[index]]; hideOutput(); showClips(); }); controls.append(btn);
      }
      block.append(blockName,time,controls); track.append(block);
    });
    if (clips.length) setStatus('Ready to create a montage. Select clips to trim or reorder.');
    else setStatus('Add a clip to begin.');
  }
  async function importFiles(files) {
    const accepted = [...files].filter((f) => /\.(mp4|mov|webm|mkv)$/i.test(f.name));
    if (!accepted.length) { toast('Choose an MP4, MOV, WebM, or MKV file.'); return; }
    const allowed=accepted.filter(f=>f.size<=250*1024*1024);
    if (allowed.length !== accepted.length) toast('Some files exceeded the 250 MB limit and were skipped.');
    for (const file of allowed) {
      const id = crypto.randomUUID();
      const url = URL.createObjectURL(file);
      const clip = { id, file, url, remote: null, start: 0, duration: 0, knownDuration: false };
      clips.push(clip); if (!selected) selected = id;
      const probe = document.createElement('video'); probe.preload = 'metadata'; probe.src = url;
      probe.onloadedmetadata = () => {
        clip.duration = Number.isFinite(probe.duration) && probe.duration > 0 ? probe.duration : 5;
        clip.knownDuration = true;
        showClips(); if (selected===clip.id) updatePreview();
      };
      probe.onerror = () => { clip.duration=5; clip.knownDuration=false; showClips(); };
    }
    hideOutput(); showClips(); updatePreview();
    $('#file-input').value='';
  }
  $('#file-input').addEventListener('change', (e) => importFiles(e.target.files));
  const drop=$('#drop-target');
  drop.addEventListener('click',()=>$('#file-input').click());
  drop.addEventListener('keydown',(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('#file-input').click();}});
  for(const evt of ['dragenter','dragover']) drop.addEventListener(evt,(e)=>{e.preventDefault();drop.classList.add('dragging');});
  for(const evt of ['dragleave','drop']) drop.addEventListener(evt,(e)=>{e.preventDefault();drop.classList.remove('dragging');});
  drop.addEventListener('drop',(e)=>importFiles(e.dataTransfer.files));
  $('#clip-start').addEventListener('change',(e)=>{
    const c=selectedClip();if(!c)return;
    c.start=Math.max(0,Math.min(c.duration-.1,Number(e.target.value)||0));hideOutput();showClips();updatePreview();
  });
  $('#clip-duration').addEventListener('change',(e)=>{
    const c=selectedClip();if(!c)return;
    // Store user selected trim separately from original total media duration.
    c.trim=Math.max(.1,Math.min(120,c.duration-c.start,Number(e.target.value)||1));
    hideOutput();showClips(); $('#clip-duration').value=c.trim;
  });
  // CurrentDuration uses the explicit length when present; declared below so edits stay predictable.
  const originalDuration = currentDuration;
  currentDuration = (clip) => Math.min(120,Math.max(.1, Math.min(clip.trim ?? Number.POSITIVE_INFINITY, Number(clip.duration)-Number(clip.start))));

  async function render() {
    if (busy) return;
    if (!clips.length){toast('Upload at least one clip to create an edit.');return;}
    if (clips.some((c)=>!c.knownDuration)) { toast('Wait until your browser has read every video’s duration.'); return; }
    busy = true;hideOutput();
    $('#render-button').disabled = true;$('#render-top').disabled=true;
    try {
      const manifest=[];
      for (let i=0;i<clips.length;i++) {
        const clip=clips[i];
        if(!clip.remote){
          setStatus(`Uploading clip ${i+1} of ${clips.length} to your local render server…`);
          const form = new FormData(); form.append('file',clip.file,clip.file.name);
          const response=await fetch(`/api/projects/${projectId}/clips`,{method:'POST',body:form});
          const data=await response.json();
          if (!response.ok) throw new Error(data.detail || 'Upload failed');
          clip.remote=data.file;
        }
        manifest.push({file:clip.remote,start_seconds:clip.start,duration_seconds:currentDuration(clip)});
      }
      setStatus('Rendering your montage locally with FFmpeg. This may take a moment.');
      const response=await fetch(`/api/projects/${projectId}/render`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clips:manifest,style:$('#preset-select').value,layout:$('#layout-select').value,size:$('#quality-select').value})});
      const data=await response.json();
      if (!response.ok) throw new Error(data.detail || 'Rendering failed');
      latestDownloadUrl=data.url;
      const btn=$('#download-button');btn.href=latestDownloadUrl;btn.classList.remove('is-hidden');
      setStatus('Your MP4 is ready. Open or download the finished montage.', 'success');
      toast('Montage exported successfully.');
    } catch(error) {
      setStatus(String(error?.message||error), 'error');
      toast('Could not create the montage. See the error in the settings panel.');
    } finally {busy=false;$('#render-button').disabled=false;$('#render-top').disabled=false;showStatusAfterRender();}
  }
  function showStatusAfterRender(){
    if (latestDownloadUrl) setStatus('Your MP4 is ready. Download below.', 'success');
  }
  $('#render-button').addEventListener('click', render);
  $('#render-top').addEventListener('click', () => { openEditor(); render(); });
  showClips();
})();
