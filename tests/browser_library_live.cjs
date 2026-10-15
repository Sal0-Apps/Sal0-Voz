// Real uploads, edits, previews, downloads and deletion against FastAPI.
// The worker stays disabled: the WAV fixture is silence, not model output.
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
  const root=path.join(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'sal0-library-'));
  const env={...process.env,SAL0_DATA:data,SAL0_DISABLE_WORKER:'1',SAL0_AUTO_DOWNLOAD_MODELS:'0'};
  const python=process.env.SAL0_TEST_PYTHON||'python',base='http://127.0.0.1:17871';
  const seed=spawnSync(python,['-m','scripts.seed_ui_smoke'],{cwd:root,env,encoding:'utf8'});assert.equal(seed.status,0,seed.stderr);
  const server=spawn(python,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','17871'],{cwd:root,env,stdio:['ignore','pipe','pipe']});
  let logs='',browser;server.stdout.on('data',b=>logs+=b);server.stderr.on('data',b=>logs+=b);
  try{
    let ready=false;for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,100));}assert.ok(ready,logs);
    browser=await chromium.launch({headless:true,executablePath:process.env.SAL0_CHROMIUM||undefined});
    const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const tap=selector=>page.locator(selector).tap();
    async function library(pane){await tap('#tab-library');const summary=page.locator('#library-'+pane);if(!(await summary.locator('..').evaluate(x=>x.open)))await summary.tap();}
    async function screenshot(name){await page.screenshot({path:'/tmp/sal0-041-'+name+'.png',fullPage:true});}
    await page.goto(base);await page.locator('#password').fill('library-test-password');await tap('#auth-submit');
    await page.waitForFunction(()=>document.querySelector('#server-status').textContent==='Conectado');
    await library('results');
    const [download]=await Promise.all([page.waitForEvent('download'),tap('#result-list a[download]')]);
    assert.equal(download.suggestedFilename(),'Resultado de teste.wav');
    assert.equal(fs.readFileSync(await download.path()).subarray(0,4).toString(),'RIFF');
    await tap('[data-open-result="33333333333333333333333333333333"]');
    assert.equal(await page.locator('#current-result .result-heading strong').textContent(),'100%');
    assert.equal(await page.locator('#current-result .result-meta span').last().textContent(),'1 h 48 min 57 s');
    await screenshot('result-mobile');
    await library('voices');await tap('#add-voice');
    await page.locator('#character-upload').setInputFiles(path.join(data,'media/11111111111111111111111111111111.wav'));
    await page.waitForFunction(()=>document.querySelector('#character-upload-status').textContent.startsWith('Arquivo enviado'));
    await page.locator('#character-name').fill('Outra voz com um nome grande para conferir o alinhamento');
    await tap('#character-form button[type=submit]');
    await page.waitForFunction(()=>document.querySelectorAll('[data-character]').length===2);
    const existing=page.locator('#character-list [data-item-id="22222222222222222222222222222222"]');
    await existing.locator('.item-more>summary').tap();await tap('[data-character="22222222222222222222222222222222"]');
    assert.equal(await page.locator('#character-form-title').textContent(),'Editar voz');
    await page.locator('#character-name').fill('Voz editada');await tap('#character-form button[type=submit]');
    await page.waitForFunction(()=>!document.querySelector('#voice-dialog').open&&document.querySelector('#character-list').textContent.includes('Voz editada'));
    await existing.locator('.item-more>summary').tap();await tap('[data-reference-text="22222222222222222222222222222222"]');await page.locator('#log-dialog').waitFor({state:'visible'});
    assert.equal(await page.locator('#job-log').textContent(),'Referência para testar a interface.');await tap('#close-log');
    await tap('[data-preview="voice-22222222222222222222222222222222"]');
    await page.locator('#preview-voice-22222222222222222222222222222222 audio').evaluate(audio=>audio.play());
    await page.waitForFunction(()=>document.querySelector('#preview-voice-22222222222222222222222222222222 audio').currentTime>0);
    await tap('[data-preview="voice-22222222222222222222222222222222"]');
    assert.equal(await page.locator('#preview-voice-22222222222222222222222222222222 audio').evaluate(a=>a.paused),true);
    await tap('[data-selection-start="characters"]');await tap('[data-select-all="characters"]');
    await tap('[data-delete-selected="characters"]');await tap('#delete-cancel');
    await tap('[data-clear-selection="characters"]');
    assert.equal(await page.locator('[data-select-kind="characters"]:visible').count(),0);
    await screenshot('library-mobile');
    await tap('[data-use-voice="22222222222222222222222222222222"]');assert.equal(await page.locator('#character').inputValue(),'22222222222222222222222222222222');
    await screenshot('create-mobile');
    await library('media');await tap('[data-use-media="11111111111111111111111111111111"]');
    assert.equal(await page.locator('#source-media').inputValue(),'11111111111111111111111111111111');
    assert.equal(await page.locator('[data-mode="dub"]').getAttribute('aria-selected'),'true');
    await screenshot('dubbing-mobile');
    await library('media');
    await page.locator('#media-import').setInputFiles({name:'texto da biblioteca.txt',mimeType:'text/plain',buffer:Buffer.from('Texto da biblioteca. Preservar exatamente!')});
    await page.waitForFunction(()=>[...document.querySelectorAll('[data-use-media]')].some(x=>x.textContent==='Usar texto'));
    await page.locator('[data-use-media]').filter({hasText:'Usar texto'}).tap();
    assert.equal(await page.locator('#script').inputValue(),'Texto da biblioteca. Preservar exatamente!');
    await tap('#tab-settings');
    const telegram=page.locator('.settings-section').filter({has:page.locator('#telegram-form')});
    await telegram.locator('summary').first().tap();await page.locator('#telegram-token').fill('rascunho preservado');
    await tap('#collapse-settings');assert.equal(await page.locator('.settings-section[open]').count(),0);
    await telegram.locator('summary').first().tap();assert.equal(await page.locator('#telegram-token').inputValue(),'rascunho preservado');
    await tap('#collapse-settings');await screenshot('settings-mobile');
    await tap('#theme');assert.ok(await page.locator('body').evaluate(x=>x.classList.contains('light')));await screenshot('settings-light');await tap('#theme');
    await tap('#open-help');assert.equal(await page.locator('#help-dialog').evaluate(x=>x.open),true);await tap('#close-help');
    await tap('#queue-toggle');assert.equal(await page.locator('#queue-panel').evaluate(x=>x.open),true);await screenshot('queue-mobile');await tap('#queue-close');
    // Layout invariants cover all screens, not only the library, at narrow,
    // tablet and desktop widths. Native touch controls keep a usable height.
    for(const width of [320,390,768,1366]){
      await page.setViewportSize({width,height:900});
      for(const view of ['create','settings','library']){
        await tap('#tab-'+view);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,view+' overflow at '+width);
        const heights=await page.locator('.header-actions>button').evaluateAll(items=>items.map(x=>Math.round(x.getBoundingClientRect().height)));
        assert.equal(new Set(heights).size,1,'header button alignment at '+width);assert.ok(heights.every(x=>x>=44));
      }
    }
    await library('voices');
    await existing.locator('.item-more>summary').tap();await tap('[data-delete-one="22222222222222222222222222222222"]');await tap('#delete-confirm');
    await page.waitForFunction(()=>!document.querySelector('[data-character="22222222222222222222222222222222"]'));
    assert.equal(await page.locator('[data-character]').count(),1);
    await page.reload();await page.waitForFunction(()=>document.querySelector('#server-status').textContent==='Conectado');
    await library('voices');assert.equal(await page.locator('[data-character]').count(),1);
    assert.deepEqual(errors,[]);
    console.log('PASS: real API touch actions, upload/edit/reference playback/transcript, selected voice/media, WAV download, confirm/cancel deletion, reload, preserved settings, four screen sizes and equal button heights');
  }catch(error){console.error(logs);throw error;}
  finally{await browser?.close();server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve));fs.rmSync(data,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
