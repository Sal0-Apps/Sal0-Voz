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
    const page=await browser.newPage({viewport:{width:390,height:900}}),errors=[];
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
    await page.reload();await page.locator('#retry-connection').waitFor({state:'visible'});await page.locator('#retry-connection').click();
    await page.waitForFunction(()=>document.querySelector('#retry-connection').hidden&&!document.querySelector('#current-result').hidden);
    assert.equal(await page.locator('#script').inputValue(),'Um trabalho que permanece após atualizar.');
    assert.deepEqual(errors,[]);
    console.log('PASS: real API bootstrap, queued job and saved text survive reload, manual reconnection restores the studio');
  }finally{
    await browser?.close();server.kill('SIGTERM');await new Promise(r=>{if(server.exitCode!==null)return r();server.once('exit',r);setTimeout(()=>{server.kill('SIGKILL');r();},3000).unref();});fs.rmSync(data,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
