// Real Chromium UI regression; API fixtures isolate client behavior from model inference.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true });
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
      if (pathname === '/health') return json({ worker: true, version: '0.3.0' });
      if (pathname === '/api/auth/status') return json({ configured: true, authenticated: true, username: 'admin', role: 'admin' });
      if (pathname === '/api/events/stream') return route.fulfill({ contentType: 'text/event-stream', body: '' });
      if (pathname === '/api/models') return json(models);
      if (pathname === '/api/models/prepare') return json({ status: 'queued' });
      if (pathname === '/api/models/qwen-0.6b/download') {
        downloads++;
        models.find(model => model.id === 'qwen-0.6b').download = { status: 'queued', progress: 0 };
        return json({ status: 'queued' });
      }
      if (pathname === '/api/media') {
        if (method === 'POST') {
          const item = { id: 'ref-1', name: 'reference.wav', type: 'media', audio: true, video: false, duration: 8 };
          media.push(item);
          return json(item);
        }
        return json(media);
      }
      if (pathname === '/api/characters') {
        if (method === 'POST') {
          const item = { ...request.postDataJSON(), id: 'voice-1', version: 1 };
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
        jobs.push(job);
        return json(job);
      }
      if (pathname === '/api/jobs') return json(jobs);
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
    await page.locator('.voice-options > summary').click();
    await page.locator('#engine').selectOption('qwen-0.6b');
    await page.locator('#retry-preparation').click();
    await page.waitForFunction(() => document.querySelector('#preparation-text').textContent.includes('Preparando no servidor'));
    assert.equal(downloads, 1);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log('PASS: Turbo defaults, independent reference language, upload and generation, polling, voice reuse, optional download, desktop and mobile views');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
