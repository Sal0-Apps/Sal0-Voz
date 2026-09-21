const $ = (id) => document.getElementById(id);
const state = {mode:"tts", projectId:null, characterId:null, models:[], characters:[], media:[], projects:[], jobs:[], cues:[], configured:false, user:{}};
let events, toastTimer, saveTimer, recorder;
const escapeHTML = (s) => String(s ?? "").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const bytes = n => (n/1024**3).toFixed(1)+" GB";
function toast(text){ $("toast").textContent=text; $("toast").hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$("toast").hidden=true,7000); }
async function api(path, options={}){
  const headers=options.body instanceof FormData ? {} : {"Content-Type":"application/json"};
  const response=await fetch("/api"+path,{...options,headers:{...headers,...options.headers}});
  if(!response.ok){
    if(response.status===401 && !path.startsWith("/auth/")){ await start(); }
    const data=await response.json().catch(()=>({detail:"Falha de conexão."}));
    throw Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail));
  }
  return response.json();
}
const post=(path,body={})=>api(path,{method:"POST",body:JSON.stringify(body)});
function safe(fn){return async(...args)=>{try{await fn(...args);}catch(e){toast(e.message);}};}
function view(name){
  document.querySelectorAll(".view").forEach(x=>x.hidden=x.id!=="view-"+name);
  document.querySelectorAll(".nav").forEach(x=>x.classList.toggle("active",x.dataset.view===name));
  $("breadcrumb").textContent="Estúdio / "+({create:"Criar voz",characters:"Personagens",projects:"Projetos",library:"Biblioteca",settings:"Ajustes"}[name]);
  if(name==="settings") safe(async()=>{await loadDiagnostics();await loadTelegram();await loadUsers();})();
  if(name==="library") renderResults();
}
document.querySelectorAll("[data-view]").forEach(x=>x.addEventListener("click",()=>view(x.dataset.view)));
function setMode(mode){
  if(mode==="convert"){toast("Conversão direta de voz aguarda integração e validação em CPU. Não será substituída por transcrição + TTS.");return;}
  state.mode=mode;
  document.querySelectorAll("[data-mode]").forEach(x=>x.classList.toggle("selected",x.dataset.mode===mode));
  $("script-fields").hidden=mode!=="tts"; $("source-fields").hidden=mode==="tts"; $("dub-fields").hidden=mode!=="dub";
  $("engine-label").hidden=mode==="asr"; $("asr-label").hidden=mode!=="asr"; $("rate-label").hidden=mode==="asr"; $("format-label").hidden=mode!=="tts";
  $("editor-title").textContent={tts:"Seu roteiro",asr:"Áudio para transcrever",dub:"Roteiro e linha do tempo"}[mode];
  $("generate").textContent={tts:"✦ Gerar voz",asr:"≡ Gerar legendas",dub:"▷ Gerar dublagem"}[mode];
  modelNotice();
}
document.querySelectorAll("[data-mode]").forEach(x=>x.addEventListener("click",()=>setMode(x.dataset.mode)));
document.querySelectorAll("[data-editor]").forEach(x=>x.addEventListener("click",()=>{
  document.querySelectorAll("[data-editor]").forEach(y=>y.classList.toggle("active",y===x));$("direction-tools").hidden=x.dataset.editor!=="detailed";
}));
document.querySelectorAll("[data-insert]").forEach(x=>x.addEventListener("click",()=>{
  const area=$("script");area.setRangeText(x.dataset.insert,area.selectionStart,area.selectionEnd,"end");area.dispatchEvent(new Event("input"));area.focus();
}));
function payload(){
  return {name:$("project-name").value.trim()||"Projeto sem título",mode:state.mode,text:$("script").value,language:$("language").value,engine:$("engine").value,asr_engine:$("asr-engine").value,character_id:$("character").value||null,media_id:$("source-media").value||null,background_id:$("background-media").value||null,rate:Number($("rate").value),format:$("format").value,cues:state.cues};
}
function saveDraft(){
  $("char-count").textContent=$("script").value.length.toLocaleString("pt-BR")+" caracteres";
  $("save-state").textContent=state.projectId?"Alterações salvas no servidor após uma breve pausa":"Salve o projeto no servidor para manter o rascunho";
  clearTimeout(saveTimer);
  if(state.projectId) saveTimer=setTimeout(safe(async()=>{await saveProject(false);}),1500);
}
$("project-form").addEventListener("input",saveDraft);
$("project-form").addEventListener("change",saveDraft);
async function saveProject(message=true){
  clearTimeout(saveTimer);
  const project=await api(state.projectId?"/projects/"+state.projectId:"/projects",{method:state.projectId?"PUT":"POST",body:JSON.stringify(payload())});
  state.projectId=project.id;$("save-state").textContent="Projeto salvo no servidor";
  state.projects=await api("/projects");renderProjects();
  if(message)toast("Projeto salvo.");
  return project;
}
$("save-project").addEventListener("click",safe(()=>saveProject()));
$("project-form").addEventListener("submit",safe(async event=>{
  event.preventDefault();$("generate").disabled=true;
  try{const project=await saveProject(false);await post("/projects/"+project.id+"/generate");$("queue-panel").hidden=false;toast("Trabalho adicionado à fila.");await loadJobs();}finally{$("generate").disabled=false;}
}));
$("validate-script").addEventListener("click",safe(async()=>{const result=await post("/script/validate",payload());toast(result.segments.length+" trechos válidos. Pausas e metadados não serão falados.");}));
$("rate").addEventListener("input",()=>{$("rate-value").textContent=Number($("rate").value).toFixed(2)+"×";});
function modelNotice(){
  const ident=state.mode==="asr"?$("asr-engine").value:$("engine").value;
  const model=state.models.find(x=>x.id===ident);
  const download=model?.download;
  $("model-notice").textContent=model?((model.available?"":download?.status==="downloading"?"Baixando no servidor. ":download?.status==="queued"?"Aguardando download no servidor. ":"Não instalado. ")+model.notice):"";
}
$("engine").addEventListener("change",modelNotice);$("asr-engine").addEventListener("change",modelNotice);
function fillOptions(element,items,placeholder,label){
  const selected=element.value;element.innerHTML=(placeholder!==null?'<option value="">'+escapeHTML(placeholder)+'</option>':"")+items.map(x=>'<option value="'+escapeHTML(x.id)+'">'+escapeHTML(label(x))+'</option>').join("");
  if(items.some(x=>x.id===selected))element.value=selected;
}
function refreshSelectors(){
  fillOptions($("character"),state.characters,"Escolha um personagem",x=>x.name+" · v"+x.version);
  fillOptions($("source-media"),state.media.filter(x=>x.type==="media"),"Selecione na biblioteca",x=>x.name);
  for(const id of ["character-reference","background-media"])fillOptions($(id),state.media.filter(x=>x.audio&&!x.video),id==="background-media"?"Sem ambiente separado":"Selecione uma referência",x=>x.name);
}
async function loadModels(){
  const selectedEngine=$("engine").value||"qwen-0.6b";
  state.models=await api("/models");
  fillOptions($("engine"),state.models.filter(x=>x.kind==="tts"),null,x=>x.name+(x.available?"":" · não instalado"));
  fillOptions($("asr-engine"),state.models.filter(x=>x.kind==="asr"),null,x=>x.name+(x.available?"":" · não instalado"));
  $("engine").value=selectedEngine;
  modelNotice();
}
function loadProject(p){
  clearTimeout(saveTimer);state.projectId=p.id||null;state.cues=p.cues||[];
  for(const [key,id] of Object.entries({name:"project-name",text:"script",language:"language",engine:"engine",asr_engine:"asr-engine",character_id:"character",media_id:"source-media",background_id:"background-media",rate:"rate",format:"format"})){
    if(p[key]!==undefined)$(id).value=p[key]??"";
  }
  setMode(p.mode||"tts");renderCues();$("rate-value").textContent=Number($("rate").value).toFixed(2)+"×";
  $("char-count").textContent=$("script").value.length+" caracteres";view("create");$("save-state").textContent=p.id?"Projeto carregado":"Rascunho local";
}
function renderProjects(){
  $("project-list").innerHTML=state.projects.length?state.projects.map(p=>'<article class="card item-card"><span class="badge">'+escapeHTML({tts:"Texto para voz",asr:"Legendas",dub:"Dublagem"}[p.mode])+'</span><h3 class="section-title">'+escapeHTML(p.name)+'</h3><p>Revisão '+p.revision+' · '+new Date(p.updated*1000).toLocaleDateString("pt-BR")+'</p><div class="item-actions"><button class="secondary" data-open="'+p.id+'">Abrir projeto</button><button class="quiet" data-duplicate="'+p.id+'">Duplicar</button></div></article>').join(""):'<div class="empty">Seu próximo projeto começa em Criar voz.</div>';
  document.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>loadProject(state.projects.find(p=>p.id===b.dataset.open)));
  document.querySelectorAll("[data-duplicate]").forEach(b=>b.onclick=()=>{const p={...state.projects.find(p=>p.id===b.dataset.duplicate),id:null};p.name+=" · cópia";loadProject(p);});
}
function renderCharacters(){
  $("character-list").innerHTML=state.characters.length?state.characters.map(c=>'<article class="card item-card"><div class="avatar">'+escapeHTML(c.name.slice(0,2).toUpperCase())+'</div><h3>'+escapeHTML(c.name)+'</h3><span class="badge">Versão '+c.version+' · '+escapeHTML(c.language)+'</span><p>'+escapeHTML(c.description||"Sem descrição")+'</p>'+(c.reference_id?'<audio controls preload="none" src="/api/media/'+c.reference_id+'/file"></audio>':'<p class="hint">Adicione uma referência para clonagem.</p>')+'<button class="secondary" data-character="'+c.id+'">Editar / criar nova versão</button></article>').join(""):'<div class="empty">Seu elenco começa aqui.<br>Importe uma amostra na Biblioteca e crie o primeiro personagem.</div>';
  document.querySelectorAll("[data-character]").forEach(b=>b.onclick=()=>{
    const c=state.characters.find(x=>x.id===b.dataset.character);state.characterId=c.id;$("character-form-title").textContent="Editar personagem · v"+c.version;
    for(const [key,id] of Object.entries({name:"character-name",description:"character-description",origin:"character-origin",language:"character-language",reference_id:"character-reference",reference_text:"reference-text"}))$(id).value=c[key]||"";
  });
}
$("new-character").onclick=()=>{state.characterId=null;$("character-form").reset();$("character-form-title").textContent="Novo personagem";};
$("character-form").addEventListener("submit",safe(async e=>{
  e.preventDefault();const data={name:$("character-name").value,description:$("character-description").value,origin:$("character-origin").value,language:$("character-language").value,reference_id:$("character-reference").value||null,reference_text:$("reference-text").value};
  await api(state.characterId?"/characters/"+state.characterId:"/characters",{method:state.characterId?"PUT":"POST",body:JSON.stringify(data)});
  state.characters=await api("/characters");renderCharacters();refreshSelectors();toast("Personagem salvo com versão preservada.");$("new-character").click();
}));
async function upload(file){
  const form=new FormData();form.append("file",file);
  $("upload-progress").textContent="Importando "+file.name+"…";
  const result=await api("/media",{method:"POST",body:form});
  state.media.unshift(result);refreshSelectors();renderMedia();$("upload-progress").textContent="Importação concluída.";
  return result;
}
$("media-import").addEventListener("change",safe(async e=>{for(const file of e.target.files)await upload(file);e.target.value="";}));
$("script-import").addEventListener("change",safe(async e=>{
  if(!e.target.files[0])return;
  const m=await upload(e.target.files[0]);
  if(m.cues){state.cues=m.cues;setMode("dub");renderCues();toast("SRT importado. Confira os tempos e atribua o elenco.");}
  else{$("script").value=m.text;setMode("tts");}
  saveDraft();e.target.value="";
}));
function renderMedia(){
  $("media-list").innerHTML=state.media.length?state.media.map(m=>'<article class="card item-card"><span class="badge">'+escapeHTML(m.video?"Vídeo":m.audio?"Áudio":"Roteiro")+'</span><h3 class="section-title">'+escapeHTML(m.name)+'</h3><p>'+(m.size/1024**2).toFixed(1)+' MB'+(m.duration?' · '+m.duration.toFixed(1)+' s':"")+'</p>'+(m.audio?(m.video?'<video':'<audio')+' controls preload="none" src="/api/media/'+m.id+'/file"></'+(m.video?"video":"audio")+'>':'')+'<div class="item-actions"><a href="/api/media/'+m.id+'/file" download>Baixar original</a></div></article>').join(""):'<div class="empty">Sua biblioteca está pronta para os primeiros arquivos.</div>';
}
function renderCues(){
  $("cue-editor").innerHTML=state.cues.map((c,i)=>'<div class="cue"><div class="cue-times"><label>Início (segundos)<input type="number" min="0" step="0.001" value="'+c.start_ms/1000+'" data-cue="'+i+'" data-key="start_ms"></label><label>Fim (segundos)<input type="number" min="0" step="0.001" value="'+c.end_ms/1000+'" data-cue="'+i+'" data-key="end_ms"></label><button type="button" data-remove-cue="'+i+'" aria-label="Remover fala '+(i+1)+'">×</button></div><label>Fala '+(i+1)+'<textarea rows="2" data-cue="'+i+'" data-key="text">'+escapeHTML(c.text)+'</textarea></label><label>Personagem<select data-cue="'+i+'" data-key="character_id"><option value="">Usar personagem principal</option>'+state.characters.map(x=>'<option value="'+x.id+'"'+(c.character_id===x.id?" selected":"")+'>'+escapeHTML(x.name)+'</option>').join("")+'</select></label></div>').join("");
  document.querySelectorAll("[data-cue]").forEach(x=>x.oninput=()=>{
    state.cues[Number(x.dataset.cue)][x.dataset.key]=x.dataset.key.endsWith("_ms")?Math.round(Number(x.value)*1000):x.value;saveDraft();
  });
  document.querySelectorAll("[data-remove-cue]").forEach(x=>x.onclick=()=>{state.cues.splice(Number(x.dataset.removeCue),1);renderCues();saveDraft();});
}
$("add-cue").onclick=()=>{const end=state.cues.at(-1)?.end_ms||0;state.cues.push({start_ms:end,end_ms:end+3000,text:""});renderCues();saveDraft();};
const statuses={queued:"Aguardando",running:"Processando",paused:"Pausado",completed:"Concluído",cancelled:"Cancelado",failed:"Falhou"};
function outputHTML(job){
  return (job.outputs||[]).map((out,i)=>'<a href="/api/jobs/'+job.id+'/output/'+i+'" download>'+escapeHTML(out.name)+'</a>').join(" · ");
}
function renderJobs(){
  $("queue-count").textContent=state.jobs.filter(x=>["queued","running"].includes(x.status)).length;
  $("queue-list").innerHTML=state.jobs.length?state.jobs.map(j=>'<article class="card"><span class="badge">'+statuses[j.status]+'</span><h3>'+escapeHTML(j.name)+'</h3><p class="hint">'+escapeHTML(j.stage)+'</p><progress max="100" value="'+j.progress+'" aria-label="'+j.progress+'%"></progress><div class="item-actions">'+(["queued","running"].includes(j.status)?'<button class="secondary" data-job="'+j.id+'" data-action="pause">Pausar</button>':"")+(["paused","failed","cancelled"].includes(j.status)?'<button class="secondary" data-job="'+j.id+'" data-action="resume">Retomar</button>':"")+(["queued","running","paused","failed"].includes(j.status)?'<button class="quiet" data-job="'+j.id+'" data-action="cancel">Cancelar</button>':"")+'<button class="quiet" data-log="'+j.id+'">Diagnóstico</button></div>'+(j.outputs?.length?'<div class="item-actions">'+outputHTML(j)+'</div>':"")+(j.cues?.length?'<button class="text-button" data-review="'+j.id+'">Revisar legendas</button>':"")+'</article>').join(""):'<div class="empty">Nenhum trabalho por aqui.<br>Crie sua primeira voz.</div>';
  document.querySelectorAll("[data-job]").forEach(b=>b.onclick=safe(async()=>{await post("/jobs/"+b.dataset.job+"/"+b.dataset.action);await loadJobs();}));
  document.querySelectorAll("[data-log]").forEach(b=>b.onclick=safe(async()=>{$("job-log").textContent=(await api("/jobs/"+b.dataset.log+"/log")).text;$("log-dialog").showModal();}));
  document.querySelectorAll("[data-review]").forEach(b=>b.onclick=safe(async()=>{
    const job=state.jobs.find(j=>j.id===b.dataset.review);const project=await api("/projects/"+job.project_id);
    project.cues=job.cues;project.mode="dub";project.id=null;project.name+=" · revisão";loadProject(project);$("queue-panel").hidden=true;toast("Legendas carregadas em uma cópia. Salve as alterações antes de gerar.");
  }));
  renderResults();
}
async function loadJobs(){state.jobs=await api("/jobs");renderJobs();}
function renderResults(){
  const completed=state.jobs.filter(x=>x.status==="completed");
  $("result-list").innerHTML=completed.length?completed.map(j=>{
    const playable=j.outputs.findIndex(x=>["audio","video"].includes(x.type));const type=playable>=0?j.outputs[playable].type:null;
    return '<article class="card item-card"><h3>'+escapeHTML(j.name)+'</h3><span class="badge">Concluído · revisão recomendada</span>'+(type?'<'+type+' controls preload="none" src="/api/jobs/'+j.id+'/output/'+playable+'"></'+type+'>':"")+'<div class="item-actions">'+outputHTML(j)+'</div></article>';
  }).join(""):'<div class="empty">Os resultados concluídos aparecem aqui.</div>';
}
function renderModelList(){
  const active=state.models.filter(m=>m.download&&["queued","downloading"].includes(m.download.status)).length;
  $("model-auto-status").textContent=active?active+" download(s) em andamento no servidor.":"Os arquivos permanecem no volume /data do servidor.";
  $("model-list").innerHTML=state.models.map(m=>{
    const d=m.download||{}, busy=["queued","downloading"].includes(d.status);
    const action=m.available?"":busy?'<button class="quiet" data-model-cancel="'+m.id+'">Cancelar</button>':'<button class="secondary" data-model-download="'+m.id+'">Baixar no servidor</button>';
    const label=m.available?"Instalado":d.status==="failed"?"Falhou":busy?(d.status==="downloading"?"Baixando":"Na fila"):"Não instalado";
    return '<div class="model-row"><span class="badge">'+label+'</span><h3>'+escapeHTML(m.name)+'</h3><p>'+escapeHTML(m.notice)+'</p><p>'+escapeHTML(m.license)+' · '+escapeHTML(m.revision?m.revision.slice(0,12):"Revisão ainda não baixada")+'</p><div class="item-actions">'+action+'</div></div>';
  }).join("");
  document.querySelectorAll("[data-model-download]").forEach(b=>b.onclick=safe(async()=>{await post("/models/"+b.dataset.modelDownload+"/download",{accept_license:true});toast("Download iniciado no servidor.");await loadModels();await loadDiagnostics();}));
  document.querySelectorAll("[data-model-cancel]").forEach(b=>b.onclick=safe(async()=>{await post("/models/"+b.dataset.modelCancel+"/cancel");await loadModels();await loadDiagnostics();}));
}
async function loadDiagnostics(){
  const d=await api("/diagnostics");$("version").textContent=d.version;
  $("diagnostics").innerHTML='<div class="card stat"><strong>'+bytes(d.memory_available)+'</strong><small>RAM disponível no sistema</small></div><div class="card stat"><strong>'+bytes(d.disk_free)+'</strong><small>Disco disponível</small></div><div class="card stat"><strong>'+d.threads+' threads</strong><small>Processamento em CPU</small></div>';
  renderModelList();
}
$("refresh-models").onclick=safe(async()=>{await loadModels();await loadDiagnostics();toast("Modelos atualizados.");});
async function loadTelegram(){const cfg=await api("/telegram");$("telegram-token").value=cfg.telegram_token||"";$("telegram-chat").value=cfg.telegram_chat_id||"";}
async function loadUsers(){if(state.user.role!=="admin")return;$("users-card").hidden=false;const users=await api("/users");$("users-list").innerHTML=users.map(u=>'<div class="item-actions"><span>'+escapeHTML(u.username)+' · '+escapeHTML(u.role)+'</span>'+(u.username===state.user.username?"":'<button class="quiet" data-delete-user="'+escapeHTML(u.username)+'">Excluir</button>')+'</div>').join("");document.querySelectorAll("[data-delete-user]").forEach(b=>b.onclick=safe(async()=>{await api("/users/"+encodeURIComponent(b.dataset.deleteUser),{method:"DELETE"});await loadUsers();}));}
$("telegram-form").addEventListener("submit",safe(async e=>{e.preventDefault();const cfg=await api("/telegram",{method:"PUT",body:JSON.stringify({telegram_token:$("telegram-token").value,telegram_chat_id:$("telegram-chat").value})});$("telegram-token").value=cfg.telegram_token||"";$("telegram-status").textContent="Configuração salva no servidor.";toast("Telegram configurado.");}));
$("user-form").addEventListener("submit",safe(async e=>{e.preventDefault();await api("/users",{method:"POST",body:JSON.stringify({username:$("new-username").value,password:$("new-password").value,role:$("new-role").value})});e.target.reset();await loadUsers();toast("Usuário criado.");}));
$("queue-toggle").onclick=()=>$("queue-panel").hidden=!$("queue-panel").hidden;
$("queue-close").onclick=()=>$("queue-panel").hidden=true;
$("close-log").onclick=()=>$("log-dialog").close();
$("theme").onclick=()=>{document.body.classList.toggle("light");localStorage.setItem("sal0-theme",document.body.classList.contains("light")?"light":"dark");};
if(localStorage.getItem("sal0-theme")==="light")document.body.classList.add("light");
$("logout").onclick=safe(async()=>{await post("/auth/logout");events?.close();await start();});
for(const [id,kind,key,render] of [["more-projects","projects","projects",renderProjects],["more-media","media","media",renderMedia],["more-jobs","jobs","jobs",renderJobs]]){
  $(id).onclick=safe(async()=>{const next=await api("/"+kind+"?offset="+state[key].length);state[key].push(...next);render();if(!next.length)toast("Todos os registros foram carregados.");});
}
$("record").onclick=safe(async()=>{
  if(recorder?.state==="recording"){recorder.stop();return;}
  if(!navigator.mediaDevices?.getUserMedia)throw Error("O microfone exige HTTPS ou localhost. Você também pode importar uma gravação do dispositivo.");
  const stream=await navigator.mediaDevices.getUserMedia({audio:true});const chunks=[];
  recorder=new MediaRecorder(stream);recorder.ondataavailable=e=>chunks.push(e.data);
  recorder.onstop=safe(async()=>{stream.getTracks().forEach(t=>t.stop());$("record").textContent="● Gravar microfone";const mime=recorder.mimeType;const extension=mime.includes("mp4")?"m4a":mime.includes("ogg")?"ogg":"webm";await upload(new File(chunks,"gravacao-"+Date.now()+"."+extension,{type:mime}));});
  recorder.start();$("record").textContent="■ Parar e salvar";toast("Gravando o microfone deste dispositivo.");
});
$("auth-form").addEventListener("submit",async e=>{
  e.preventDefault();$("auth-submit").disabled=true;$("auth-error").textContent="";
  try{await post(state.configured?"/auth/login":"/auth/setup",{username:$("username").value.trim()||"admin",password:$("password").value});$("password").value="";await start();}
  catch(e){$("auth-error").textContent=e.message;}finally{$("auth-submit").disabled=false;}
});
async function start(){
  events?.close();
  const auth=await api("/auth/status");state.configured=auth.configured;
  $("auth").hidden=auth.authenticated;$("app").hidden=!auth.authenticated;
  state.user={username:auth.username||"admin",role:auth.role||"admin"};
  $("auth-description").textContent=auth.configured?"Bem-vindo de volta ao seu estúdio.":"Crie o primeiro usuário administrador para abrir seu estúdio local.";
  $("auth-submit").textContent=auth.configured?"Entrar no estúdio":"Criar meu estúdio";
  if(!auth.authenticated)return;
  [state.characters,state.media,state.projects]=await Promise.all([api("/characters?limit=100"),api("/media?limit=100"),api("/projects")]);
  await loadModels();refreshSelectors();renderCharacters();renderProjects();renderMedia();await loadJobs();
  events=new EventSource("/api/events/stream");events.onmessage=e=>{state.jobs=JSON.parse(e.data);renderJobs();};
}
safe(start)();


$("export-srt").onclick=safe(async()=>{const p=await saveProject(false);const link=document.createElement("a");link.href="/api/projects/"+p.id+"/subtitles/srt";link.download="legendas.srt";link.click();});
$("new-project").onclick=()=>{clearTimeout(saveTimer);state.projectId=null;state.cues=[];$("project-form").reset();$("engine").value="qwen-0.6b";setMode("tts");renderCues();view("create");saveDraft();};
