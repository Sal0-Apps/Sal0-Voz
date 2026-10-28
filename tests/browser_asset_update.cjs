// Exercise a real warm Chromium HTTP cache, not Playwright routing (which
// disables caching). Old unversioned JS/CSS must not run after a UI update.
const { chromium } = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

(async()=>{
  const root=path.join(__dirname,'../app/static');
  const contents=['index.html','app.js','style.css'].map(name=>fs.readFileSync(path.join(root,name)));
  const revision=crypto.createHash('sha256').update(Buffer.concat(contents.flatMap((data,index)=>index?[Buffer.from([0]),data]:[data]))).digest('hex').slice(0,20);
  const html=contents[0].toString().replaceAll('__UI_REVISION__',revision);
  let legacy=true,legacyRequests=0;
  const assetRequests=[],errors=[];
  const server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost');
    const json=value=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(value));};
    if(url.pathname==='/'){
      res.setHeader('Content-Type','text/html');res.setHeader('Cache-Control','no-store');
      return res.end(legacy?'<!doctype html><html><head><link rel="stylesheet" href="/static/style.css"><script src="/static/app.js"></script></head><body>Previous UI</body></html>':html);
    }
    if(['/static/app.js','/static/style.css'].includes(url.pathname)){
      res.setHeader('Content-Type',url.pathname.endsWith('.js')?'text/javascript':'text/css');
      if(!url.search){legacyRequests++;res.setHeader('Cache-Control','public,max-age=31536000,immutable');return res.end(url.pathname.endsWith('.js')?'window.legacyUI=true;':'body{background:red}');}
      assetRequests.push(req.url);res.setHeader('Cache-Control','no-store');
      return res.end(fs.readFileSync(path.join(root,path.basename(url.pathname))));
    }
    if(url.pathname.startsWith('/static/')){res.end();return;}
    if(url.pathname==='/health')return json({version:'test',worker:true});
    if(url.pathname==='/api/auth/status')return json({configured:true,authenticated:true,username:'test',role:'admin'});
    if(url.pathname==='/api/models')return json([{id:'qwen-1.7b',kind:'tts',clone:true,available:true},{id:'whisper-large-v3-turbo',kind:'asr',available:true}]);
    if(url.pathname==='/api/model-access')return json({configured:false,writable:true});
    if(['/api/characters','/api/media','/api/projects','/api/jobs','/api/reactions'].includes(url.pathname))return json([]);
    res.writeHead(404);res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  try{
    browser=await chromium.launch({headless:true,executablePath:process.env.SAL0_CHROMIUM||undefined});
    const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
    page.on('pageerror',e=>errors.push(e.message));
    const base='http://127.0.0.1:'+server.address().port;
    await page.goto(base);assert.equal(await page.evaluate(()=>window.legacyUI),true);
    // Confirm the old app.js really is in cache before changing the release.
    await page.reload();assert.equal(legacyRequests,2);
    legacy=false;await page.reload();
    await page.waitForFunction(()=>document.querySelector('#server-status').textContent==='Conectado');
    assert.equal(await page.evaluate(()=>window.legacyUI),undefined);
    assert.deepEqual(assetRequests.sort(),['/static/app.js?v='+revision,'/static/style.css?v='+revision].sort());
    assert.equal(legacyRequests,2);
    await page.locator('#tab-library').click();
    await page.locator('#library-voices').click();await page.locator('#add-voice').click();
    assert.equal(await page.locator('#voice-dialog').evaluate(x=>x.open),true);
    await page.locator('#close-voice-dialog').click();
    await page.locator('#library-media').click();
    assert.equal(await page.locator('#media-import').locator('..').isVisible(),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: real legacy HTTP cache survives but is bypassed by matching HTML/JS/CSS fingerprints; touch library actions work after update');
  }finally{await browser?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
