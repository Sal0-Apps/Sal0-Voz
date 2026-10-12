// Real FastAPI startup and reload regression: no simulated API responses.
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');

(async()=>{
  const data=fs.mkdtempSync(path.join(os.tmpdir(),'sal0-live-'));
  const base='http://127.0.0.1:17869';
  const server=spawn(process.env.SAL0_TEST_PYTHON||'python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','17869'],{cwd:path.join(__dirname,'..'),env:{...process.env,SAL0_DATA:data,SAL0_DISABLE_WORKER:'1'},stdio:['ignore','pipe','pipe']});
  let logs='',browser;
  server.stdout.on('data',b=>logs+=b);server.stderr.on('data',b=>logs+=b);
  try{
    let ready=false;
    for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,100));}
    assert.ok(ready,logs);
    browser=await chromium.launch({headless:true,executablePath:process.env.SAL0_CHROMIUM||undefined});
    const context=await browser.newContext({viewport:{width:390,height:900}});
    const page=await context.newPage(),errors=[];
    let persistentRequests=0;
    page.on('request',r=>{if(r.url().endsWith('/api/events/stream'))persistentRequests++;});
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);
    await page.locator('#password').fill('browser-test-password');await page.locator('#auth-submit').click();
    await page.waitForFunction(()=>document.querySelectorAll('#reaction-choice option').length===33&&document.querySelector('#preparation-text').textContent!=='Conectando ao seu servidor…');
    assert.equal(await page.locator('#retry-connection').isVisible(),false);
    const samples=24000*4,wav=Buffer.alloc(44+samples*2);
    wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(24000,24);wav.writeUInt32LE(48000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(samples*2,40);
    for(let i=0;i<samples;i++)wav.writeInt16LE(Math.round(Math.sin(i/24000*180*2*Math.PI)*10000),44+i*2);
    await page.locator('#reference-upload').setInputFiles({name:'Minha voz.wav',mimeType:'audio/wav',buffer:wav});
    await page.locator('#script').fill('Um trabalho que permanece após atualizar.');await page.locator('#generate').click();
    await page.waitForFunction(()=>!document.querySelector('#current-result').hidden&&!document.querySelector('#generate').disabled);
    const before=await page.evaluate(async()=>({jobs:await(await fetch('/api/jobs')).json(),projects:await(await fetch('/api/projects')).json()}));
    assert.equal(before.jobs.length,1);
    await page.reload();
    await page.waitForFunction(()=>!document.querySelector('#current-result').hidden&&document.querySelectorAll('#reaction-choice option').length===33);
    assert.equal(await page.locator('#script').inputValue(),'Um trabalho que permanece após atualizar.');
    const after=await page.evaluate(async()=>await(await fetch('/api/jobs')).json());
    assert.equal(after[0].id,before.jobs[0].id);assert.equal(after.length,1);
    let fail=true;
    await page.route('**/api/reactions',route=>{if(fail){fail=false;return route.fulfill({status:404,contentType:'application/json',body:'{"detail":"Not Found"}'});}return route.continue();});
    await page.reload();await page.locator('#retry-connection').waitFor({state:'visible'});
    assert.equal(await page.locator('#queue-count').textContent(),'1');
    assert.equal(await page.locator('#script').inputValue(),'Um trabalho que permanece após atualizar.');
    await page.locator('#retry-connection').click();
    await page.waitForFunction(()=>document.querySelector('#retry-connection').hidden&&!document.querySelector('#current-result').hidden);
    assert.equal(await page.locator('#script').inputValue(),'Um trabalho que permanece após atualizar.');
    // A model API outage must not hide jobs; it recovers without a button click.
    let modelOutage=true;
    await page.route('**/api/models',route=>modelOutage?route.fulfill({status:503,contentType:'application/json',body:'{"detail":"temporary model catalog failure"}'}):route.continue());
    await page.reload();await page.locator('#retry-connection').waitFor({state:'visible'});
    assert.equal(await page.locator('#queue-count').textContent(),'1');
    modelOutage=false;
    await page.waitForFunction(()=>document.querySelector('#retry-connection').hidden&&!document.querySelector('#current-result').hidden,{},{timeout:12000});
    assert.equal(await page.locator('#script').inputValue(),'Um trabalho que permanece após atualizar.');
    await page.unroute('**/api/models');
    // A later outage preserves visible jobs and a typed draft, then saves it.
    let disconnected=true;
    await page.route('**/api/**',route=>disconnected?route.fulfill({status:503,contentType:'application/json',body:'{"detail":"temporary connection failure"}'}):route.continue());
    await page.locator('#script').fill('Rascunho preservado durante a queda de conexão.');
    await page.evaluate(()=>window.dispatchEvent(new Event('online')));
    await page.locator('#retry-connection').waitFor({state:'visible'});
    await page.waitForFunction(()=>document.querySelector('#save-state').textContent.includes('aguardando conexão'));
    assert.equal(await page.locator('#queue-count').textContent(),'1');
    disconnected=false;
    await page.waitForFunction(()=>document.querySelector('#retry-connection').hidden&&document.querySelector('#save-state').textContent==='Projeto salvo no servidor',{},{timeout:15000});
    assert.equal(await page.locator('#script').inputValue(),'Rascunho preservado durante a queda de conexão.');
    const saved=await page.evaluate(async()=>await(await fetch('/api/projects')).json());
    assert.equal(saved[0].text,'Rascunho preservado durante a queda de conexão.');
    await page.unroute('**/api/**');
    // More tabs than the HTTP/1.1 socket limit all remain usable.
    const tabs=await Promise.all(Array.from({length:7},()=>page.context().newPage()));
    await Promise.all(tabs.map(async tab=>{await tab.goto(base);await tab.waitForFunction(()=>document.querySelector('#queue-count').textContent==='1'&&document.querySelectorAll('#engine option').length>0,{},{timeout:15000});}));
    assert.equal(persistentRequests,0);
    await Promise.all(tabs.map(tab=>tab.close()));
    // Older clients still using EventSource receive finite snapshots too.
    await page.evaluate(()=>globalThis.legacyStreams=Array.from({length:6},()=>new EventSource('/api/events/stream')));
    assert.equal(await page.evaluate(async()=>(await fetch('/health',{signal:AbortSignal.timeout(2000)})).ok),true);
    await page.evaluate(()=>globalThis.legacyStreams.forEach(stream=>stream.close()));
    assert.deepEqual(errors,[]);
    console.log('PASS: real API/reload, partial failures preserve jobs, automatic recovery saves draft, seven tabs and legacy streams remain responsive');
  }finally{
    await browser?.close();server.kill('SIGTERM');await new Promise(r=>{if(server.exitCode!==null)return r();server.once('exit',r);setTimeout(()=>{server.kill('SIGKILL');r();},3000).unref();});fs.rmSync(data,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
