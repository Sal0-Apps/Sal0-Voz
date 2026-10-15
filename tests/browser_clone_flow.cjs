// Real Chromium UI regression; API fixtures isolate client behavior from model inference.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.SAL0_CHROMIUM || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
    const errors = [], unexpected = [];
    page.on('pageerror', error => errors.push(error.message));
    const media = [], characters = [], projects = [], jobs = [], generated = [];
    let downloads = 0, failJobRead = false;
    async function openLibrary(pane){await page.locator('#tab-library').click();const summary=page.locator('#library-'+pane);if(!(await summary.locator('..').evaluate(x=>x.open)))await summary.click();}
    async function openOptions(){if(!(await page.locator('#personalization').evaluate(x=>x.open)))await page.locator('#personalization > summary').click();}
    async function openNames(){await openOptions();if(!(await page.locator('#audio-options').evaluate(x=>x.open)))await page.locator('#audio-options > summary').click();}
    const models = [
      { id: 'diagnostic', name: 'Voz simples', kind: 'tts', available: true },
      { id: 'qwen-1.7b', name: 'Maior fidelidade', kind: 'tts', clone: true, reference_text: true, available: true, source: 'bundled' },
      { id: 'qwen-0.6b', name: 'Mais leve', kind: 'tts', clone: true, reference_text: true, available: false },
      { id: 'chatterbox-pt-br', name: 'Expressiva · Chatterbox V3 pt-BR', kind: 'tts', clone: true, reference_text: false, expressiveness: true, available: false, download_gib: 3.0 },
      { id: 'omnivoice', name: 'Fidelidade e expressão · OmniVoice 0.6B', kind: 'tts', clone: true, reference_text: true, available: false, download_gib: 3.1 },
      { id: 'voxcpm2', name: 'Clonagem e emoções · VoxCPM2 2B', kind: 'tts', clone: true, reference_text: true, style_control: true, available: false, download_gib: 4.8 },
      { id: 'whisper-large-v3-turbo', name: 'Faster-Whisper large-v3-turbo', kind: 'asr', available: true, source: 'bundled' },
      { id: 'whisper-medium', name: 'Whisper medium', kind: 'asr', available: false },
    ].map(model => ({ license: 'Test fixture', notice: 'Modelo local', ...model }));
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      const pathname = url.pathname, method = request.method();
      const json = value => route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
      if (url.origin !== 'http://sal0-voz.test') {
        unexpected.push(request.url());
        return route.abort();
      }
      if (pathname === '/' || pathname.startsWith('/static/')) {
        const relative = pathname === '/' ? 'index.html' : pathname.slice('/static/'.length);
        const file = path.join(__dirname, '../app/static', relative);
        const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };
        return route.fulfill({ body: fs.readFileSync(file), contentType: mime[path.extname(file)] || 'application/octet-stream' });
      }
      if (pathname === '/health') return json({ worker: true, version: '0.4.1' });
      if (pathname === '/api/auth/status') return json({ configured: true, authenticated: true, username: 'admin', role: 'admin' });
      if (pathname === '/api/events/stream') return route.fulfill({ contentType: 'text/event-stream', body: '' });
      if (pathname === '/api/models') return json(models);
      if (pathname === '/api/reactions') return json(JSON.parse(fs.readFileSync(path.join(__dirname, '../app/assets/reactions/catalog.json'), 'utf8')).map(x=>({...x,native_models:['risada','suspiro'].includes(x.id)?['omnivoice','voxcpm2']:[]})));
      if (pathname === '/api/models/prepare') return json({ status: 'queued' });
      if (['/api/models/qwen-0.6b/download','/api/models/chatterbox-pt-br/download','/api/models/omnivoice/download','/api/models/voxcpm2/download'].includes(pathname)) {
        downloads++;
        models.find(model => model.id === pathname.split('/')[3]).download = { status: 'queued', progress: 0 };
        return json({ status: 'queued' });
      }
      if (pathname === '/api/media') {
        if (method === 'POST') {
          const name = request.postDataBuffer().toString().match(/filename="([^"]+)"/)[1];
          const script = /\.(txt|srt)$/i.test(name);
          const item = { id: `ref-${media.length+1}`, name, type: script?'script':'media', text:script?'Texto importado intacto.':undefined, audio:!script, video: /\.(mkv|mp4)$/i.test(name), duration: 8 };
          media.push(item);
          return json(item);
        }
        return json(media);
      }
      if (pathname === '/api/characters') {
        if (method === 'POST') {
          const item = { ...request.postDataJSON(), id: `voice-${characters.length+1}`, version: 1 };
          characters.push(item);
          return json(item);
        }
        return json(characters);
      }
      if (pathname === '/api/projects' || /^\/api\/projects\/project-\d+$/.test(pathname)) {
        if (method === 'POST' || method === 'PUT') {
          const id = method === 'PUT' ? pathname.split('/').pop() : `project-${projects.length + 1}`;
          const item = { ...request.postDataJSON(), id, revision: 1, updated: Date.now() / 1000 };
          const index = projects.findIndex(project => project.id === id);
          if (index >= 0) projects[index] = item; else projects.push(item);
          return json(item);
        }
        return json(projects);
      }
      if (/^\/api\/projects\/project-\d+\/generate$/.test(pathname)) {
        const id = pathname.split('/')[3];
        generated.push({ ...projects.find(project => project.id === id) });
        const job = { id: 'job-1', project_id: id, name: 'Clone em andamento', status: 'running', stage: 'Preparando a voz', progress: 0, started: Date.now() / 1000, outputs: [] };
        job.id='job-'+(jobs.length+1);job.updated=Date.now()/1000;jobs.push(job);
        await new Promise(resolve=>setTimeout(resolve,650));
        if(jobs.length===1)failJobRead=true;
        return json(job);
      }
      if (pathname === '/api/jobs'){if(failJobRead){failJobRead=false;return route.fulfill({status:503,contentType:'application/json',body:'{"detail":"temporary queue read failure"}'});}return json(jobs);}
      if (pathname === '/api/items/delete') {
        const {kind,ids}=request.postDataJSON(),items={media,characters,results:jobs}[kind];
        const deleted=[];for(let i=items.length-1;i>=0;i--)if(ids.includes(items[i].id)){deleted.push(items[i].id);items.splice(i,1);}
        return json({deleted,blocked:[],missing:[],cleanup_pending:false});
      }
      if (pathname === '/api/diagnostics') return json({ version: '0.4.1', memory_available: 12 * 1024**3, disk_free: 20 * 1024**3, threads: 4 });
      if (pathname === '/api/telegram') return json({});
      if (pathname === '/api/users') return json([{ username: 'admin', role: 'admin' }]);
      unexpected.push(`${method} ${pathname}`);
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Unexpected fixture request"}' });
    });
    await page.goto('http://sal0-voz.test');
    await page.waitForFunction(() => document.querySelector('#preparation-text').textContent.startsWith('Pronto'));
    assert.equal(await page.locator('#engine').inputValue(), 'qwen-1.7b');
    assert.equal(await page.locator('#asr-engine').inputValue(), 'whisper-large-v3-turbo');
    assert.equal(await page.locator('#personalization').evaluate(element => element.open),false);
    assert.equal(await page.locator('.nav-tabs [role=tab]').count(),3);
    assert.equal(await page.locator('.sidebar').count(),0);
    assert.equal(await page.locator('#engine').isVisible(), true);
    assert.equal(await page.locator('#character').isVisible(),false);
    assert.equal(await page.locator('#reference-upload').locator('..').isVisible(),true);
    assert.deepEqual(await page.locator('#project-form .flow-step').evaluateAll(items=>items.map(x=>x.id)),['voice-step','content-step','model-step']);
    await page.locator('#quick-reference details > summary').click();
    await page.locator('#reference-language').selectOption('en-US');
    await page.locator('#reference-upload').setInputFiles({ name: 'reference.wav', mimeType: 'audio/wav', buffer: Buffer.from('fixture audio') });
    await page.locator('#script').fill('O texto novo deve continuar intacto.');
    await page.locator('#generate').click();
    assert.equal(await page.locator('#creation-loading').isVisible(),true);
    assert.equal(await page.locator('#creation-editor').isVisible(),false);
    await page.waitForFunction(() => !document.querySelector('#current-result').hidden);
    assert.equal(await page.locator('#creation-editor').isVisible(),false);
    assert.equal(generated.length,1);
    await page.waitForFunction(()=>document.querySelector('#connection-notice').hidden);
    assert.match(await page.locator('#current-result .result-meta span').last().textContent(),/^\d+ h \d+ min \d+ s$/);
    assert.equal(characters[0].language, 'en-US');
    assert.equal(characters[0].reference_text, '');
    assert.equal(generated[0].language, 'pt-BR');
    assert.equal(generated[0].text, 'O texto novo deve continuar intacto.');
    assert.equal(generated[0].engine, 'qwen-1.7b');
    assert.equal(generated[0].asr_engine, 'whisper-large-v3-turbo');
    assert.equal(generated[0].audio_name, '');
    assert.equal(generated[0].adaptive_memory, true);
    await page.locator('#add-another').click();
    await page.locator('#character').focus();
    await page.waitForTimeout(5400);
    assert.equal(await page.locator('#character').inputValue(), 'voice-1');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'character');
    await page.waitForFunction(() => document.querySelector('#script').value === '');
    assert.equal(await page.locator('#current-result').isVisible(), false);
    assert.equal(await page.locator('#running-notice').isVisible(), true);
    assert.equal(jobs[0].status, 'running');
    assert.equal(await page.locator('#character').inputValue(), 'voice-1');
    assert.equal(await page.locator('#reference-language').inputValue(), 'en-US');
    await page.screenshot({path:'/tmp/voice-create-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/voice-create-mobile.png',fullPage:true});
    assert.equal(await page.locator('#voice-style-settings').isVisible(),false);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.setViewportSize({width:1366,height:900});
    await openOptions();
    await page.locator('#reaction-choice').selectOption('gemido');
    await page.locator('#insert-reaction').click();
    assert.equal(await page.locator('#script').inputValue(), '[reacao=gemido]');
    assert.equal(await page.locator('#reaction-choice option').count(), 33);
    assert.equal(await page.locator('#preview-reaction').count(),0);
    assert.ok((await page.locator('#reaction-choice option:checked').textContent()).includes('vocalização'));
    await openNames();
    await page.locator('#audio-name').fill('Cena de teste');
    await page.locator('#save-project').click();
    await page.waitForFunction(() => document.querySelector('#save-state').textContent === 'Projeto salvo no servidor');
    assert.equal(projects.at(-1).audio_name, 'Cena de teste');
    await page.locator('#tab-library').click();await openLibrary('voices');
    await page.screenshot({path:'/tmp/voice-library-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/voice-library-mobile.png',fullPage:true});
    await page.locator('#add-voice').click();
    await page.screenshot({path:'/tmp/voice-dialog-mobile.png',fullPage:true});
    assert.equal(await page.locator('#character-form details[open]').count(),0);
    await page.setViewportSize({width:1366,height:900});
    await page.locator('#character-upload').setInputFiles({name:'uploaded-video.mkv',mimeType:'application/octet-stream',buffer:Buffer.from('fixture video')});
    await page.waitForFunction(() => document.querySelector('#character-upload-status').textContent.startsWith('Arquivo enviado'));
    assert.equal(await page.locator('#character-reference').inputValue(), 'ref-2');
    assert.equal(await page.locator('#character-name').inputValue(), 'uploaded-video');
    assert.equal(await page.locator('#reaction-upload').count(),0);
    await page.locator('#character-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelectorAll('[data-character]').length === 2);
    assert.equal(characters[1].reference_id, 'ref-2');
    assert.deepEqual(characters[1].reactions, {});
    await page.locator('nav [data-view="create"]').click();
    await page.locator('[data-mode="dub"]').click();
    assert.equal(await page.locator('#dub-advanced').evaluate(x=>x.open),false);
    assert.equal(await page.locator('#script-import-label').isVisible(),false);
    await page.locator('#source-library > summary').click();
    await page.locator('#source-media').selectOption('ref-2');
    await page.locator('#generate').click();
    await page.waitForFunction(() => !document.querySelector('#generate').disabled);
    assert.equal(generated.at(-1).mode, 'dub');
    assert.deepEqual(generated.at(-1).cues, []);
    assert.equal(await page.locator('#generate').innerText(),'Gerar vídeo dublado');
    await page.locator('#add-another').click();
    assert.equal(await page.locator('[data-mode="dub"]').getAttribute('aria-selected'),'true');
    await page.locator('#source-upload').setInputFiles({name:'audio-to-dub.wav',mimeType:'audio/wav',buffer:Buffer.from('fixture audio')});
    await page.waitForFunction(()=>document.querySelector('#source-status').textContent.includes('fundo simples'));
    await page.locator('#generate').click();await page.waitForFunction(()=>!document.querySelector('#generate').disabled);
    assert.equal(generated.at(-1).media_id,'ref-3');
    for (const width of [1366, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      for (const view of ['create','library','settings']) {
        await page.locator(`nav [data-view="${view}"]`).click();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `${view}: overflow at ${width}`);
        assert.equal(await page.locator('#theme').isVisible(), true);
        assert.equal(await page.locator('#open-help').isVisible(),true);
        if(view==='library')for(const pane of ['voices','media','results','projects']){await openLibrary(pane);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
      }
    }
    assert.equal(await page.locator('.settings-section').first().evaluate(element => element.open), false);
    await page.screenshot({path:'/tmp/voice-settings-mobile.png',fullPage:true});
    await page.locator('#tab-create').focus();await page.keyboard.press('End');
    assert.equal(await page.locator('#tab-library').getAttribute('aria-selected'),'true');
    await page.keyboard.press('Home');
    await page.locator('#add-another').click();
    await page.locator('[data-mode="asr"]').click();
    assert.equal(await page.locator('#voice-step').isVisible(),false);
    assert.equal(await page.locator('#asr-engine').isVisible(),true);
    await page.locator('#source-upload').setInputFiles({name:'legendas.mp4',mimeType:'video/mp4',buffer:Buffer.from('fixture video')});
    await page.waitForFunction(()=>document.querySelector('#source-status').textContent.includes('legendas.mp4'));
    await page.locator('#generate').click();await page.waitForFunction(()=>!document.querySelector('#generate').disabled);
    assert.equal(generated.at(-1).mode,'asr');
    assert.equal(generated.at(-1).asr_engine,'whisper-large-v3-turbo');
    await page.locator('#add-another').click();
    await page.locator('[data-mode="tts"]').click();
    await page.locator('#engine').selectOption('qwen-0.6b');
    await page.locator('#download-selected-model').click();
    await page.waitForFunction(() => document.querySelector('#preparation-text').textContent.includes('aguardando download'));
    assert.equal(downloads, 1);
    await openNames();
    await page.locator('#engine').selectOption('chatterbox-pt-br');
    assert.equal(await page.locator('#expression-settings').isVisible(),true);
    assert.equal(await page.locator('#download-selected-model').isVisible(),true);
    await page.locator('#download-selected-model').click();
    await page.waitForFunction(()=>document.querySelector('#download-selected-model').hidden);
    assert.equal(downloads,2);
    await page.locator('#character').selectOption('voice-1');
    assert.equal(await page.locator('#engine').inputValue(),'chatterbox-pt-br');
    await page.locator('#expressiveness').evaluate(input=>{input.value='0.9';input.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.locator('#save-project').click();
    await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Projeto salvo no servidor');
    assert.equal(projects.at(-1).engine,'chatterbox-pt-br');
    assert.equal(projects.at(-1).expressiveness,0.9);
    for(const engine of ['omnivoice','voxcpm2']){
      await page.locator('#engine').selectOption(engine);
      assert.equal(await page.locator('#download-selected-model').isVisible(),true);
      await page.locator('#download-selected-model').click();
      await page.waitForFunction(()=>!document.querySelector('#download-selected-model').disabled);
      assert.equal(downloads,engine==='omnivoice'?3:4);
      assert.equal(await page.locator('#expression-settings').isVisible(),false);
      assert.equal(await page.locator('#voice-style-settings').isVisible(),engine==='voxcpm2');
      await page.locator('#reaction-choice').selectOption('risada');
      assert.equal(await page.locator('#reaction-choice option:checked').textContent(),'Risada');
      await page.locator('#reaction-choice').selectOption('gemido');
      assert.ok((await page.locator('#reaction-choice option:checked').textContent()).includes('vocalização'));
      await page.locator('#character').selectOption('voice-1');
      assert.equal(await page.locator('#engine').inputValue(),engine);
    }
    await page.locator('#voice-style').selectOption('happy');
    await page.locator('#save-project').click();
    await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Projeto salvo no servidor');
    assert.equal(projects.at(-1).engine,'voxcpm2');
    assert.equal(projects.at(-1).voice_style,'happy');
    await page.locator('#script-import').setInputFiles({name:'texto.txt',mimeType:'text/plain',buffer:Buffer.from('Texto importado intacto.')});
    await page.waitForFunction(()=>document.querySelector('#script').value==='Texto importado intacto.');
    assert.equal(await page.locator('[data-mode="tts"]').evaluate(x=>x.classList.contains('selected')),true);
    await page.locator('#tab-library').click();await openLibrary('voices');
    await page.locator('[data-selection-start="characters"]').click();
    await page.locator('[data-select-all="characters"]').click();
    await page.locator('[data-delete-selected="characters"]').click();
    assert.equal(await page.locator('#delete-dialog').isVisible(),true);
    await page.locator('#delete-cancel').click();assert.equal(characters.length,2);
    await page.locator('[data-delete-selected="characters"]').click();await page.locator('#delete-confirm').click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-character]').length===0);
    assert.equal(characters.length,0);
    await page.locator('nav [data-view="library"]').click();
    await openLibrary('media');
    await page.locator('[data-selection-start="media"]').click();
    await page.locator('[data-select-all="media"]').click();
    await page.locator('[data-delete-selected="media"]').click();await page.locator('#delete-confirm').click();
    await page.waitForFunction(()=>document.querySelectorAll('#media-list [data-select-id]').length===0);
    assert.equal(media.length,0);
    const activeJobs=jobs.length;
    jobs.push({id:'completed-1',name:'Resultado 1',status:'completed',outputs:[],updated:Date.now()/1000},{id:'completed-2',name:'Resultado 2',status:'failed',stage:'Teste',outputs:[],updated:Date.now()/1000});
    await page.waitForFunction(()=>document.querySelectorAll('#result-list [data-select-id]').length===2);
    await openLibrary('results');
    await page.locator('[data-selection-start="results"]').click();
    await page.locator('[data-select-all="results"]').click();
    await page.waitForTimeout(5200);
    assert.equal(await page.locator('#result-list [data-select-id]:checked').count(),2);
    await page.locator('[data-delete-selected="results"]').click();await page.locator('#delete-confirm').click();
    await page.waitForFunction(()=>document.querySelectorAll('#result-list [data-select-id]').length===0);
    assert.equal(jobs.length,activeJobs);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log('PASS: selected-voice reactions and native/vocalization labels, no recorded previews/uploads, three-tab interface, optional controls collapsed, editor/submission/job transitions, acknowledged jobs survive failed reads, voice dialog, TXT import, audio/video dubbing without SRT, bulk deletion, persistent selections, desktop and mobile views, ASR mode and keyboard navigation');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
