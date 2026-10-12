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
    let downloads = 0;
    const models = [
      { id: 'diagnostic', name: 'Voz simples', kind: 'tts', available: true },
      { id: 'qwen-1.7b', name: 'Maior fidelidade', kind: 'tts', available: true, source: 'bundled' },
      { id: 'qwen-0.6b', name: 'Mais leve', kind: 'tts', available: false },
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
      if (pathname === '/health') return json({ worker: true, version: '0.3.2' });
      if (pathname === '/api/auth/status') return json({ configured: true, authenticated: true, username: 'admin', role: 'admin' });
      if (pathname === '/api/events/stream') return route.fulfill({ contentType: 'text/event-stream', body: '' });
      if (pathname === '/api/models') return json(models);
      if (pathname === '/api/reactions') return json(JSON.parse(fs.readFileSync(path.join(__dirname, '../app/assets/reactions/catalog.json'), 'utf8')));
      if (pathname === '/api/models/prepare') return json({ status: 'queued' });
      if (pathname === '/api/models/qwen-0.6b/download') {
        downloads++;
        models.find(model => model.id === 'qwen-0.6b').download = { status: 'queued', progress: 0 };
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
        return json(job);
      }
      if (pathname === '/api/jobs') return json(jobs);
      if (pathname === '/api/items/delete') {
        const {kind,ids}=request.postDataJSON(),items={media,characters,results:jobs}[kind];
        const deleted=[];for(let i=items.length-1;i>=0;i--)if(ids.includes(items[i].id)){deleted.push(items[i].id);items.splice(i,1);}
        return json({deleted,blocked:[],missing:[],cleanup_pending:false});
      }
      if (pathname === '/api/diagnostics') return json({ version: '0.3.0', memory_available: 12 * 1024**3, disk_free: 20 * 1024**3, threads: 4 });
      if (pathname === '/api/telegram') return json({});
      if (pathname === '/api/users') return json([{ username: 'admin', role: 'admin' }]);
      unexpected.push(`${method} ${pathname}`);
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Unexpected fixture request"}' });
    });
    await page.goto('http://sal0-voz.test');
    await page.waitForFunction(() => document.querySelector('#preparation-text').textContent.startsWith('Pronto'));
    assert.equal(await page.locator('#engine').inputValue(), 'qwen-1.7b');
    assert.equal(await page.locator('#asr-engine').inputValue(), 'whisper-large-v3-turbo');
    assert.equal(await page.locator('.voice-options').evaluate(element => element.open), false);
    assert.equal(await page.locator('#engine').isVisible(), true);
    assert.deepEqual(await page.locator('#project-form .flow-step').evaluateAll(items=>items.map(x=>x.id)),['voice-step','content-step','model-step','generate-step']);
    await page.locator('#reference-language').selectOption('en-US');
    await page.locator('#reference-upload').setInputFiles({ name: 'reference.wav', mimeType: 'audio/wav', buffer: Buffer.from('fixture audio') });
    await page.locator('#script').fill('O texto novo deve continuar intacto.');
    await page.locator('#generate').click();
    await page.waitForFunction(() => !document.querySelector('#current-result').hidden);
    assert.equal(characters[0].language, 'en-US');
    assert.equal(characters[0].reference_text, '');
    assert.equal(generated[0].language, 'pt-BR');
    assert.equal(generated[0].text, 'O texto novo deve continuar intacto.');
    assert.equal(generated[0].engine, 'qwen-1.7b');
    assert.equal(generated[0].asr_engine, 'whisper-large-v3-turbo');
    assert.equal(generated[0].audio_name, '');
    assert.equal(generated[0].adaptive_memory, true);
    await page.locator('#character').focus();
    await page.waitForTimeout(5400);
    assert.equal(await page.locator('#character').inputValue(), 'voice-1');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'character');
    await page.locator('#add-another').click();
    await page.waitForFunction(() => document.querySelector('#script').value === '');
    assert.equal(await page.locator('#current-result').isVisible(), false);
    assert.equal(await page.locator('#running-notice').isVisible(), true);
    assert.equal(jobs[0].status, 'running');
    assert.equal(await page.locator('#character').inputValue(), 'voice-1');
    assert.equal(await page.locator('#reference-language').inputValue(), 'en-US');
    await page.locator('[data-editor="detailed"]').click();
    await page.locator('#reaction-choice').selectOption('gemido');
    await page.locator('#insert-reaction').click();
    assert.equal(await page.locator('#script').inputValue(), '[reacao=gemido]');
    assert.equal(await page.locator('#reaction-choice option').count(), 33);
    await page.locator('#output-options > summary').click();
    await page.locator('#audio-name').fill('Cena de teste');
    await page.locator('#save-project').click();
    await page.waitForFunction(() => document.querySelector('#save-state').textContent === 'Projeto salvo no servidor');
    assert.equal(projects.at(-1).audio_name, 'Cena de teste');
    await page.locator('nav [data-view="characters"]').click();
    await page.locator('#character-upload').setInputFiles({name:'uploaded-video.mkv',mimeType:'application/octet-stream',buffer:Buffer.from('fixture video')});
    await page.waitForFunction(() => document.querySelector('#character-upload-status').textContent.startsWith('Arquivo enviado'));
    assert.equal(await page.locator('#character-reference').inputValue(), 'ref-2');
    assert.equal(await page.locator('#character-name').inputValue(), 'uploaded-video');
    await page.locator('#character-form summary').filter({hasText:'Reações com esta voz'}).click();
    await page.locator('#character-reaction').selectOption('gemido');
    await page.locator('#reaction-upload').setInputFiles({name:'my-reaction.mp4',mimeType:'video/mp4',buffer:Buffer.from('fixture reaction')});
    await page.waitForFunction(() => document.querySelector('#reaction-upload-status').textContent.startsWith('Som enviado'));
    await page.locator('#character-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelectorAll('[data-character]').length === 2);
    assert.equal(characters[1].reference_id, 'ref-2');
    assert.deepEqual(characters[1].reactions, {gemido:'ref-3'});
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
    assert.equal(await page.locator('#generate').innerText(),'▷ Gerar vídeo dublado');
    await page.locator('#source-upload').setInputFiles({name:'audio-to-dub.wav',mimeType:'audio/wav',buffer:Buffer.from('fixture audio')});
    await page.waitForFunction(()=>document.querySelector('#source-status').textContent.includes('fundo simples'));
    await page.locator('#generate').click();await page.waitForFunction(()=>!document.querySelector('#generate').disabled);
    assert.equal(generated.at(-1).media_id,'ref-4');
    for (const width of [1366, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const view of ['create', 'characters', 'projects', 'library', 'settings']) {
        await page.locator(`nav [data-view="${view}"]`).click();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `${view}: overflow at ${width}`);
        assert.equal(await page.locator('#theme').isVisible(), true);
        assert.equal(await page.locator('#logout').isVisible(), true);
      }
    }
    assert.equal(await page.locator('.settings-section').first().evaluate(element => element.open), false);
    await page.locator('nav [data-view="create"]').click();
    await page.locator('[data-mode="tts"]').click();
    await page.locator('#engine').selectOption('qwen-0.6b');
    await page.locator('#retry-preparation').click();
    await page.waitForFunction(() => document.querySelector('#preparation-text').textContent.includes('Preparando no servidor'));
    assert.equal(downloads, 1);
    await page.locator('#script-import').setInputFiles({name:'texto.txt',mimeType:'text/plain',buffer:Buffer.from('Texto importado intacto.')});
    await page.waitForFunction(()=>document.querySelector('#script').value==='Texto importado intacto.');
    assert.equal(await page.locator('[data-mode="tts"]').evaluate(x=>x.classList.contains('selected')),true);
    await page.locator('nav [data-view="characters"]').click();
    await page.locator('[data-select-all="characters"]').click();
    await page.locator('[data-delete-selected="characters"]').click();
    assert.equal(await page.locator('#delete-dialog').isVisible(),true);
    await page.locator('#delete-cancel').click();assert.equal(characters.length,2);
    await page.locator('[data-delete-selected="characters"]').click();await page.locator('#delete-confirm').click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-character]').length===0);
    assert.equal(characters.length,0);
    await page.locator('nav [data-view="library"]').click();
    await page.locator('[data-select-all="media"]').click();
    await page.locator('[data-delete-selected="media"]').click();await page.locator('#delete-confirm').click();
    await page.waitForFunction(()=>document.querySelectorAll('#media-list [data-select-id]').length===0);
    assert.equal(media.length,0);
    jobs.push({id:'completed-1',name:'Resultado 1',status:'completed',outputs:[],updated:Date.now()/1000},{id:'completed-2',name:'Resultado 2',status:'failed',stage:'Teste',outputs:[],updated:Date.now()/1000});
    await page.waitForFunction(()=>document.querySelectorAll('#result-list [data-select-id]').length===2);
    await page.locator('[data-select-all="results"]').click();
    await page.waitForTimeout(5200);
    assert.equal(await page.locator('#result-list [data-select-id]:checked').count(),2);
    await page.locator('[data-delete-selected="results"]').click();await page.locator('#delete-confirm').click();
    await page.waitForFunction(()=>document.querySelectorAll('#result-list [data-select-id]').length===0);
    assert.equal(jobs.length,3);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log('PASS: four creation steps, TXT import, audio/video dubbing without SRT, bulk selection and deletion, persistent selections during polling, desktop and mobile views');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
