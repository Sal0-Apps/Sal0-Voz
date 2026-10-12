const $ = (id) => document.getElementById(id);
const defaultClone = "qwen-1.7b";
const defaultAsr = "whisper-large-v3-turbo";
const isClone = ident => !!state.models.find(model=>model.id===ident)?.clone;
const state = {mode:"tts", projectId:null, characterId:null, models:[], characters:[], media:[], projects:[], jobs:[], cues:[], reactions:[], characterReactions:{}, configured:false, user:{}, uploads:0, submitting:false, jobsLimit:50, mediaLimit:100, charactersLimit:100};
const selections = {media:new Set(), characters:new Set(), results:new Set()};
let deletePlan;
let toastTimer, saveTimer, recorder, modelTimer, startPromise, polling=false, needsAuthCheck=false, retryDelay=3000, restorePending=true, draftPending=false;
const pendingSections=new Set(["characters","media","projects","reactions","models","jobs","health"]);
let saveChain=Promise.resolve();
const escapeHTML = (s) => String(s ?? "").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const bytes = n => (n/1024**3).toFixed(1)+" GiB";
function toast(text){ $("toast").textContent=text; $("toast").hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$("toast").hidden=true,7000); }
function showDetails(title,text){$("log-dialog").querySelector("h2").textContent=title;$("job-log").textContent=text;$("log-dialog").showModal();}
async function api(path, options={}){
  const headers=options.body instanceof FormData ? {} : {"Content-Type":"application/json"};
  const response=await fetch("/api"+path,{...options,cache:"no-store",signal:options.signal||(!(options.body instanceof FormData)?AbortSignal.timeout(20000):undefined),headers:{...headers,...options.headers}});
  if(!response.ok){
    if(response.status===401 && !path.startsWith("/auth/")){needsAuthCheck=true;schedulePolling(0);}
    const data=await response.json().catch(()=>({detail:"Falha de conexão."}));
    const error=Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail));error.status=response.status;throw error;
  }
  return response.json();
}
const post=(path,body={})=>api(path,{method:"POST",body:JSON.stringify(body)});
function safe(fn){return async(...args)=>{try{await fn(...args);}catch(e){toast(e.message);}};}
function view(name){
  document.querySelectorAll(".view").forEach(x=>x.hidden=x.id!=="view-"+name);
  document.querySelectorAll(".nav").forEach(x=>x.classList.toggle("active",x.dataset.view===name));
  $("breadcrumb").textContent="Estúdio / "+({create:"Criar voz",characters:"Minhas vozes",projects:"Projetos",library:"Biblioteca",settings:"Ajustes"}[name]);
  if(name==="settings") safe(async()=>{await loadDiagnostics();await loadTelegram();await loadUsers();})();
  if(name==="library") renderResults();
}
document.querySelectorAll("[data-view]").forEach(x=>x.addEventListener("click",()=>view(x.dataset.view)));
function setMode(mode){
  if(mode==="convert"){toast("Conversão direta de voz aguarda integração e validação em CPU. Não será substituída por transcrição + TTS.");return;}
  state.mode=mode;
  $("voice-step").hidden=mode==="asr";
  $("voice-choice").parentElement.hidden=mode==="asr";
  updateVoiceChoice();
  document.querySelectorAll("[data-mode]").forEach(x=>x.classList.toggle("selected",x.dataset.mode===mode));
  $("script-fields").hidden=mode!=="tts"; $("source-fields").hidden=mode==="tts"; $("dub-fields").hidden=mode!=="dub";
  $("engine-label").hidden=mode==="asr"; $("asr-label").hidden=mode!=="asr"; $("rate-label").hidden=mode==="asr"; $("format-label").hidden=mode!=="tts";
  $("memory-label").hidden=mode==="asr";$("memory-hint").hidden=mode==="asr";
  $("script-import-label").hidden=mode!=="tts";
  $("editor-title").textContent={tts:"2. Digite ou envie o texto",asr:"1. Envie o áudio ou vídeo",dub:"2. Escolha o áudio ou vídeo para dublar"}[mode];
  $("model-title").textContent=mode==="asr"?"2. Escolha o modelo":"3. Escolha o modelo";
  $("generate-title").textContent={tts:"4. Gere o áudio",asr:"3. Gere as legendas",dub:"4. Gere o vídeo dublado"}[mode];
  $("create-title").textContent={tts:"Dê voz ao seu texto.",asr:"Transforme fala em legendas.",dub:"Duble com a voz escolhida."}[mode];
  $("create-description").textContent={tts:"Escolha a voz, escreva ou importe o texto, escolha o modelo e gere.",asr:"Envie o arquivo, escolha o modelo e gere as legendas.",dub:"Escolha a voz, envie áudio ou vídeo, escolha o modelo e gere o vídeo dublado."}[mode];
  $("language-label").firstChild.textContent=mode==="tts"?"Idioma do texto":"Idioma da fala original";
  updateVoiceChoice();modelNotice();updateSourceStatus();updateGenerateState();renderPreparation();
}
document.querySelectorAll("[data-mode]").forEach(x=>x.addEventListener("click",()=>setMode(x.dataset.mode)));
document.querySelectorAll("[data-editor]").forEach(x=>x.addEventListener("click",()=>{
  document.querySelectorAll("[data-editor]").forEach(y=>y.classList.toggle("active",y===x));$("direction-tools").hidden=x.dataset.editor!=="detailed";
}));
document.querySelectorAll("[data-insert]").forEach(x=>x.addEventListener("click",()=>{
  const area=$("script");area.setRangeText(x.dataset.insert,area.selectionStart,area.selectionEnd,"end");area.dispatchEvent(new Event("input"));area.focus();
}));
function payload(){
  return {name:$("project-name").value.trim()||"Projeto sem título",audio_name:$("audio-name").value.trim(),adaptive_memory:$("adaptive-memory").checked,expressiveness:Number($("expressiveness").value),voice_style:$("voice-style").value,mode:state.mode,text:$("script").value,language:$("language").value,engine:$("engine").value,asr_engine:$("asr-engine").value,character_id:$("character").value||null,media_id:$("source-media").value||null,background_id:$("background-media").value||null,rate:Number($("rate").value),format:$("format").value,cues:state.cues};
}
function saveDraft(){
  draftPending=true;
  $("char-count").textContent=$("script").value.length.toLocaleString("pt-BR")+" caracteres";
  $("save-state").textContent="Salvando no servidor…";
  clearTimeout(saveTimer);
  saveTimer=setTimeout(safe(async()=>{await saveProject(false);}),1500);
}
$("project-form").addEventListener("input",saveDraft);
$("project-form").addEventListener("change",saveDraft);
function saveProject(message=true){
  clearTimeout(saveTimer);
  saveChain=saveChain.catch(()=>{}).then(()=>persistProject(message));
  return saveChain;
}
async function persistProject(message=true){
  clearTimeout(saveTimer);
  const body=JSON.stringify(payload());
  let project;
  try{project=await api(state.projectId?"/projects/"+state.projectId:"/projects",{method:state.projectId?"PUT":"POST",body});}
  catch(error){draftPending=!error.status||error.status>=500||[401,408,429].includes(error.status);$("save-state").textContent=draftPending?"Rascunho aguardando conexão com o servidor":error.message;throw error;}
  state.projectId=project.id;$("save-state").textContent="Projeto salvo no servidor";
  draftPending=JSON.stringify(payload())!==body;
  try{state.projects=await api("/projects");renderProjects();}
  catch{pendingSections.add("projects");schedulePolling(3000);}
  if(message)toast("Projeto salvo.");
  return project;
}
$("save-project").addEventListener("click",safe(()=>saveProject()));
$("project-form").addEventListener("submit",safe(async event=>{
  event.preventDefault();if(state.submitting||state.uploads)return;
  if(state.mode==="tts"&&!$("script").value.trim()){$("script").focus();throw Error("No passo 2, digite o texto ou importe um arquivo.");}
  if(state.mode!=="tts"&&!$("source-media").value){$("source-upload").focus();throw Error("Escolha o áudio ou vídeo no passo "+(state.mode==="asr"?1:2)+".");}
  state.submitting=true;updateGenerateState();
  try{
    if(state.mode!=="asr" && isClone($("engine").value) && $("reference-upload").files[0])await saveQuickReference();
    const project=await saveProject(false);await post("/projects/"+project.id+"/generate");
    toast("Trabalho na fila. Você pode fechar esta aba ou preparar outro texto.");await loadJobs();
  }catch(error){if(/referência|Selecione uma voz/.test(error.message)&&state.mode!=="asr"){$("character").focus();}throw error;}
  finally{state.submitting=false;updateGenerateState();}
}));
function updateGenerateState(){
  const catalogReady=state.models.some(m=>m.id===(state.mode==="asr"?$("asr-engine").value:$("engine").value));
  $("generate").disabled=state.submitting||state.uploads>0||!catalogReady;
  $("generate").textContent=state.submitting?"Enviando para o servidor…":state.uploads?"Enviando arquivo…":!catalogReady?"Aguardando os modelos…":{tts:"✦ Gerar áudio",asr:"≡ Gerar legendas",dub:"▷ Gerar vídeo dublado"}[state.mode];
  document.querySelectorAll("[data-mode]").forEach(b=>b.disabled=state.submitting);
}
$("validate-script").addEventListener("click",safe(async()=>{const result=await post("/script/validate",payload());toast(result.segments.length+" trechos válidos. Pausas e metadados não serão falados.");}));
$("rate").addEventListener("input",()=>{$("rate-value").textContent=Number($("rate").value).toFixed(2)+"×";});
function modelNotice(){
  const ident=state.mode==="asr"?$("asr-engine").value:$("engine").value;
  const model=state.models.find(x=>x.id===ident);
  const download=model?.download;
  $("model-notice").textContent=model?((model.available?"":download?.status==="downloading"?"Baixando no servidor. ":download?.status==="queued"?"Aguardando download no servidor. ":"Não instalado. ")+model.notice):"";
  $("download-selected-model").hidden=!model||model.available||ident==="diagnostic"||["queued","downloading"].includes(download?.status)||!!download?.retry_at;
  $("download-selected-model").textContent="Baixar "+(model?.download_gib?"· cerca de "+model.download_gib+" GiB ":"")+"no servidor";
  $("expression-settings").hidden=state.mode==="asr"||!model?.expressiveness;
  $("voice-style-settings").hidden=state.mode==="asr"||!model?.style_control;
  const fixedPrecision=["chatterbox-pt-br","omnivoice","voxcpm2"].includes(ident);
  $("memory-label").hidden=state.mode==="asr"||fixedPrecision;
  $("memory-hint").textContent=fixedPrecision?"Mantém o modelo e a precisão escolhidos. Se faltar RAM, aguarda memória e retoma dos trechos salvos.":"Mantém o modelo escolhido em todo o áudio. Se faltar RAM, tenta o modo econômico antes de começar. Se ainda não couber, aguarda memória.";
  $("expression-value").textContent=Number($("expressiveness").value).toFixed(2);
}
$("expressiveness").addEventListener("input",()=>{$("expression-value").textContent=Number($("expressiveness").value).toFixed(2);});
$("download-selected-model").onclick=safe(async()=>{
  const ident=state.mode==="asr"?$("asr-engine").value:$("engine").value;
  $("download-selected-model").disabled=true;
  try{await post("/models/"+ident+"/download",{accept_license:true});toast("Download iniciado no servidor. O modelo ficará disponível após a preparação.");await loadModels();}
  finally{$("download-selected-model").disabled=false;}
});
$("engine").addEventListener("change",()=>{if(isClone($("engine").value))state.cloneEngine=$("engine").value;$("voice-choice").value=$("engine").value==="diagnostic"?"simple":"clone";updateVoiceChoice();modelNotice();renderPreparation();});$("asr-engine").addEventListener("change",()=>{modelNotice();renderPreparation();});
function fillOptions(element,items,placeholder,label){
  const selected=element.value;
  const options=(placeholder!==null?'<option value="">'+escapeHTML(placeholder)+'</option>':"")+items.map(x=>'<option value="'+escapeHTML(x.id)+'">'+escapeHTML(label(x))+'</option>').join("");
  if(element.dataset.options===options || document.activeElement===element)return;
  element.innerHTML=options;element.dataset.options=options;
  if(items.some(x=>x.id===selected))element.value=selected;
}
function refreshSelectors(){
  fillOptions($("character"),state.characters,"Selecione uma voz salva",x=>x.name+" · v"+x.version);
  fillOptions($("source-media"),state.media.filter(x=>x.audio),"Selecione na biblioteca",x=>x.name);
  fillOptions($("character-reference"),state.media.filter(x=>x.audio),"Selecione áudio ou vídeo",x=>x.name+(x.video?" · áudio do vídeo":""));
  fillOptions($("background-media"),state.media.filter(x=>x.audio&&!x.video),"Sem ambiente separado",x=>x.name);
  fillOptions($("reaction-media"),state.media.filter(x=>x.audio),"Selecione áudio ou vídeo",x=>x.name);
  renderSelectedVoice();updateSourceStatus();
}
async function loadModels(){
  const models=await api("/models");
  const selectedEngine=$("engine").value||defaultClone;
  const selectedAsr=$("asr-engine").value||defaultAsr;
  state.models=models;
  fillOptions($("engine"),state.models.filter(x=>x.kind==="tts"),null,x=>x.name+(x.available?"":" · não instalado"));
  fillOptions($("asr-engine"),state.models.filter(x=>x.kind==="asr"),null,x=>x.name+(x.available?"":" · não instalado"));
  $("engine").value=selectedEngine;
  $("asr-engine").value=selectedAsr;
  modelNotice();renderPreparation();updateGenerateState();
  if(!$("view-settings").hidden)renderModelList();
}
async function loadProject(p){
  clearTimeout(saveTimer);await saveChain.catch(()=>{});state.projectId=p.id||null;state.cues=p.cues||[];
  draftPending=false;
  $("reference-upload").value="";$("quick-transcript").value="";$("reference-status").textContent="";
  for(const [key,id] of Object.entries({name:"project-name",text:"script",language:"language",engine:"engine",asr_engine:"asr-engine",character_id:"character",media_id:"source-media",background_id:"background-media",rate:"rate",format:"format"})){
    if(p[key]!==undefined)$(id).value=p[key]??"";
  }
  $("audio-name").value=p.audio_name||"";$("adaptive-memory").checked=p.adaptive_memory!==false;
  $("expressiveness").value=p.expressiveness??0.7;
  $("voice-style").value=p.voice_style||"natural";
  state.sourceId=$("source-media").value;$("source-upload").value="";
  $("voice-choice").value=$("engine").value==="diagnostic"?"simple":"clone";
  if(isClone($("engine").value))state.cloneEngine=$("engine").value;
  setMode(p.mode||"tts");renderCues();$("rate-value").textContent=Number($("rate").value).toFixed(2)+"×";
  $("char-count").textContent=$("script").value.length+" caracteres";view("create");$("save-state").textContent=p.id?"Projeto carregado":"Novo projeto · salvamento automático no servidor";
  renderJobs();
}
function renderProjects(){
  $("project-list").innerHTML=state.projects.length?state.projects.map(p=>'<article class="card item-card"><span class="badge">'+escapeHTML({tts:"Texto para voz",asr:"Legendas",dub:"Dublagem"}[p.mode])+'</span><h3 class="section-title">'+escapeHTML(p.name)+'</h3><p>Revisão '+p.revision+' · '+new Date(p.updated*1000).toLocaleDateString("pt-BR")+'</p><div class="item-actions"><button class="secondary" data-open="'+p.id+'">Abrir projeto</button><button class="quiet" data-duplicate="'+p.id+'">Duplicar</button></div></article>').join(""):'<div class="empty">Seu próximo projeto começa em Criar voz.</div>';
  document.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>loadProject(state.projects.find(p=>p.id===b.dataset.open)));
  document.querySelectorAll("[data-duplicate]").forEach(b=>b.onclick=()=>{const p={...state.projects.find(p=>p.id===b.dataset.duplicate),id:null};p.name+=" · cópia";loadProject(p);});
}
function renderCharacters(){
  $("character-list").innerHTML=state.characters.length?state.characters.map(c=>'<article class="card item-card" data-item-id="'+c.id+'">'+selectionHTML("characters",c)+'<div class="avatar">'+escapeHTML(c.name.slice(0,2).toUpperCase())+'</div><h3>'+escapeHTML(c.name)+'</h3><span class="badge">Versão '+c.version+' · '+escapeHTML(c.language)+'</span><p>'+escapeHTML(c.description||"Sem descrição")+'</p>'+(c.reference_id?'<audio controls preload="none" src="/api/characters/'+c.id+'/reference-file"></audio>':'<p class="hint">Adicione uma referência para clonagem.</p>')+'<div class="item-actions"><button class="primary" data-use-voice="'+c.id+'">Usar voz</button><button class="secondary" data-character="'+c.id+'">Editar</button>'+deleteHTML("characters",c)+'</div><button type="button" class="text-button" data-reference-text="'+c.id+'">Conferir transcrição</button></article>').join(""):'<div class="empty">Adicione uma gravação para salvar sua primeira voz.</div>';
  renderSelection("characters");
  document.querySelectorAll("[data-use-voice]").forEach(b=>b.onclick=()=>{if(state.mode==="asr")setMode("tts");$("character").value=b.dataset.useVoice;chooseSavedVoice();view("create");$("voice-step").scrollIntoView({behavior:"smooth",block:"start"});});
  document.querySelectorAll("[data-reference-text]").forEach(b=>b.onclick=safe(async()=>{
    const result=await api("/characters/"+b.dataset.referenceText+"/reference-text");
    showDetails("Transcrição da voz",result.text?(result.automatic?"Transcrição automática da referência (confira as palavras):\n\n":"Texto informado na referência:\n\n")+result.text:"A referência será preparada na primeira geração. Você também pode informar a transcrição ao editar esta voz.");
  }));
  document.querySelectorAll("[data-character]").forEach(b=>b.onclick=()=>{
    const c=state.characters.find(x=>x.id===b.dataset.character);state.characterId=c.id;$("character-form-title").textContent="Editar personagem · v"+c.version;
    for(const [key,id] of Object.entries({name:"character-name",description:"character-description",origin:"character-origin",language:"character-language",reference_id:"character-reference",reference_text:"reference-text"}))$(id).value=c[key]||"";
    state.characterReactions={...(c.reactions||{})};renderCharacterReactions();$("reaction-upload-status").textContent="";
    $("character-form").scrollIntoView({behavior:"smooth",block:"start"});
  });
}
$("add-voice").onclick=()=>{$("new-character").click();$("character-form").scrollIntoView({behavior:"smooth",block:"start"});$("character-name").focus({preventScroll:true});};
  $("new-character").onclick=()=>{state.characterId=null;state.characterReactions={};$("character-form").reset();renderCharacterReactions();$("reaction-upload-status").textContent="";$("character-form-title").textContent="Nova voz";$("character-upload-status").textContent="O áudio será extraído e convertido automaticamente, sem alterar o arquivo original.";};
$("character-upload").onchange=safe(async e=>{
  const file=e.target.files[0];if(!file)return;
  const save=$("character-form").querySelector('button[type="submit"]');save.disabled=true;
  $("character-upload-status").textContent="Enviando "+file.name+" para o servidor…";
  try{
    const media=await upload(file);if(!media.audio)throw Error("Esse arquivo não contém uma faixa de áudio. Escolha outro áudio ou vídeo com fala.");
    $("character-reference").value=media.id;
    if(!$("character-name").value.trim())$("character-name").value=file.name.replace(/\.[^.]+$/,"").slice(0,120);
    $("character-upload-status").textContent="Arquivo enviado e selecionado. Salve a voz; o app prepara o áudio automaticamente.";
  }catch(error){$("character-upload-status").textContent=error.message;throw error;}
  finally{save.disabled=false;e.target.value="";}
});
$("character-form").addEventListener("submit",safe(async e=>{
  e.preventDefault();const data={name:$("character-name").value,description:$("character-description").value,origin:$("character-origin").value,language:$("character-language").value,reference_id:$("character-reference").value||null,reference_text:$("reference-text").value,reactions:state.characterReactions};
  await api(state.characterId?"/characters/"+state.characterId:"/characters",{method:state.characterId?"PUT":"POST",body:JSON.stringify(data)});
  state.characters=await api("/characters");renderCharacters();refreshSelectors();toast("Personagem salvo com versão preservada.");$("new-character").click();
}));
async function upload(file){
  state.uploads++;updateGenerateState();
  try{
  const form=new FormData();form.append("file",file);
  $("upload-progress").textContent="Importando "+file.name+"…";
  const result=await api("/media",{method:"POST",body:form});
  state.media.unshift(result);refreshSelectors();renderMedia();$("upload-progress").textContent="Importação concluída.";
  return result;
  }finally{state.uploads--;updateGenerateState();}
}
$("media-import").addEventListener("change",safe(async e=>{for(const file of e.target.files)await upload(file);e.target.value="";}));
$("script-import").addEventListener("change",safe(async e=>{
  if(!e.target.files[0])return;
  const m=await upload(e.target.files[0]);
  if(m.type!=="script")throw Error("Escolha um arquivo de texto TXT ou SRT.");
  $("script").value=m.cues?m.cues.map(c=>c.text).join("\n"):m.text;
  $("script").dispatchEvent(new Event("input",{bubbles:true}));toast("Texto importado. Confira o conteúdo antes de gerar.");
  saveDraft();e.target.value="";
}));
function renderMedia(){
  $("media-list").innerHTML=state.media.length?state.media.map(m=>'<article class="card item-card" data-item-id="'+m.id+'">'+selectionHTML("media",m)+'<span class="badge">'+escapeHTML(m.video?"Vídeo":m.audio?"Áudio":"Roteiro")+'</span><h3 class="section-title">'+escapeHTML(m.name)+'</h3><p>'+((m.size||0)/1024**2).toFixed(1)+' MB'+(m.duration?' · '+m.duration.toFixed(1)+' s':"")+'</p>'+(m.audio?(m.video?'<video':'<audio')+' controls preload="none" src="/api/media/'+m.id+'/file"></'+(m.video?"video":"audio")+'>':'')+'<div class="item-actions"><a href="/api/media/'+m.id+'/file" download>Baixar original</a>'+deleteHTML("media",m)+'</div></article>').join(""):'<div class="empty">Sua biblioteca está pronta para os primeiros arquivos.</div>';
  renderSelection("media");
}
function renderCues(){
  $("dub-cue-status").hidden=!state.cues.length;$("dub-cue-status").textContent="Serão usadas "+state.cues.length+" falas revisadas. Abra as opções abaixo para conferir ou voltar à transcrição automática.";
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
  document.querySelectorAll("[data-log]").forEach(b=>b.onclick=safe(async()=>{showDetails("Diagnóstico do trabalho",(await api("/jobs/"+b.dataset.log+"/log")).text);}));
  document.querySelectorAll("[data-review]").forEach(b=>b.onclick=safe(async()=>{
    const job=state.jobs.find(j=>j.id===b.dataset.review);const project=await api("/projects/"+job.project_id);
    project.cues=job.cues;project.mode="dub";project.id=null;project.name+=" · revisão";loadProject(project);$("queue-panel").hidden=true;toast("Legendas carregadas em uma cópia. Salve as alterações antes de gerar.");
  }));
  const other=state.jobs.some(j=>j.status==="running"&&j.project_id!==state.projectId);$("running-notice").hidden=!other;$("running-notice").textContent="Há um trabalho em andamento. Você pode preparar outro texto; ele entra na fila do servidor.";
  renderResults();renderCurrentResult();
}
async function fetchRecords(kind,count){
  const items=[];
  while(items.length<count){const limit=Math.min(100,count-items.length),batch=await api("/"+kind+"?offset="+items.length+"&limit="+limit);items.push(...batch);if(batch.length<limit)break;}
  return items;
}
async function loadJobs(){const jobs=await fetchRecords("jobs",state.jobsLimit);if(JSON.stringify(jobs)!==JSON.stringify(state.jobs)){state.jobs=jobs;renderJobs();}}
function renderResults(){
  const completed=state.jobs.filter(x=>!["queued","running"].includes(x.status));
  const signature=JSON.stringify(completed);if($("result-list").dataset.rendered===signature)return;$("result-list").dataset.rendered=signature;
  $("result-list").innerHTML=completed.length?completed.map(j=>{
    const playable=(j.outputs||[]).findIndex(x=>["audio","video"].includes(x.type));const type=playable>=0?j.outputs[playable].type:null;
    return '<article class="card item-card" data-item-id="'+j.id+'">'+selectionHTML("results",j)+'<h3>'+escapeHTML(j.name)+'</h3><span class="badge">'+escapeHTML(statuses[j.status])+'</span>'+(type?'<'+type+' controls preload="none" src="/api/jobs/'+j.id+'/output/'+playable+'"></'+type+'>':"")+(j.status!=="completed"?'<p class="hint">'+escapeHTML(j.stage)+'</p>':'')+'<div class="item-actions">'+outputHTML(j)+deleteHTML("results",j)+'</div></article>';
  }).join(""):'<div class="empty">Os resultados concluídos aparecem aqui.</div>';
  renderSelection("results");
}
function renderModelList(){
  const active=state.models.filter(m=>["queued","downloading"].includes(m.download?.status)||m.download?.retry_at).length;
  $("model-auto-status").textContent=active?active+" modelo(s) sendo preparados no servidor. Você pode usar o estúdio enquanto aguarda.":"Os modelos são baixados após a instalação e ficam salvos na pasta de dados. Atualizar o app reutiliza os downloads concluídos; a geração funciona sem internet.";
  $("model-list").innerHTML=state.models.map(m=>{
    const d=m.download||{},busy=["queued","downloading"].includes(d.status)||!!d.retry_at;
    const action=m.available||m.id==="diagnostic"?"":busy?'<button class="quiet" data-model-cancel="'+m.id+'">Pausar download</button>':'<button class="secondary" data-model-download="'+m.id+'">'+(d.status==="failed"||d.status==="cancelled"?'Tentar novamente':'Preparar este modelo')+'</button>';
    const label=m.available?(m.source==="bundled"?"Incluído no app":"Pronto"):d.retry_at?"Nova tentativa agendada":d.status==="failed"?"Precisa de atenção":busy?(d.status==="downloading"?"Baixando":"Na fila"):"Não instalado";
    return '<div class="model-row"><span class="badge">'+label+'</span><h3>'+escapeHTML(m.name)+'</h3><p>'+escapeHTML(m.notice)+'</p><p>'+escapeHTML(m.license)+' · '+escapeHTML(m.revision?m.revision.slice(0,12):"Preparação pendente")+'</p>'+(busy?'<progress max="100" value="'+(d.progress||0)+'"></progress><p>'+escapeHTML(downloadText(d))+'</p>':'')+(d.error?'<details class="download-error"><summary>Ver o erro da preparação</summary><pre>'+escapeHTML(d.error)+'</pre></details>':'')+'<div class="item-actions">'+action+'</div></div>';
  }).join("");
  document.querySelectorAll("[data-model-download]").forEach(b=>b.onclick=safe(async()=>{await post("/models/"+b.dataset.modelDownload+"/download",{accept_license:true});toast("O servidor vai preparar o modelo. Os trabalhos aguardando continuam automaticamente.");await loadModels();await loadDiagnostics();}));
  document.querySelectorAll("[data-model-cancel]").forEach(b=>b.onclick=safe(async()=>{await post("/models/"+b.dataset.modelCancel+"/cancel");await loadModels();await loadDiagnostics();}));
}
async function loadDiagnostics(){
  const d=await api("/diagnostics");$("version").textContent=d.version;
  $("diagnostics").innerHTML='<div class="card stat"><strong>'+bytes(d.memory_available)+'</strong><small>RAM disponível para o app</small></div><div class="card stat"><strong>'+bytes(d.disk_free)+'</strong><small>Disco disponível</small></div><div class="card stat"><strong>'+d.threads+' threads</strong><small>Processamento em CPU</small></div>';
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
$("logout").onclick=safe(async()=>{await post("/auth/logout");await start();});
for(const [id,kind,key,render] of [["more-projects","projects","projects",renderProjects]]){
  $(id).onclick=safe(async()=>{const next=await api("/"+kind+"?offset="+state[key].length);state[key].push(...next);render();if(!next.length)toast("Todos os registros foram carregados.");});
}
for(const [id,kind,limit,render] of [["more-media","media","mediaLimit",renderMedia],["more-characters","characters","charactersLimit",renderCharacters],["more-jobs","jobs","jobsLimit",renderJobs],["more-results","jobs","jobsLimit",renderJobs]]){
  $(id).onclick=safe(async()=>{state[limit]+=50;state[kind]=await fetchRecords(kind,state[limit]);render();refreshSelectors();});
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
function connectionState(errors=[]){
  $("connection-notice").hidden=!errors.length;
  $("retry-connection").hidden=!errors.length;
  if(errors.length)$("connection-text").textContent="Parte do estúdio não respondeu. Tentando novamente. Seu texto continua nesta página e os trabalhos ficam no servidor.";
}
function schedulePolling(delay=5000){
  clearTimeout(modelTimer);
  modelTimer=setTimeout(pollStudio,delay);
}
async function loadStudioSections(sections){
  const loaders={
    characters:async()=>{state.characters=await fetchRecords("characters",state.charactersLimit);renderCharacters();refreshSelectors();},
    media:async()=>{state.media=await fetchRecords("media",state.mediaLimit);renderMedia();refreshSelectors();},
    projects:async()=>{state.projects=await api("/projects");renderProjects();},
    reactions:async()=>{state.reactions=await api("/reactions");renderReactionOptions();},
    models:loadModels,jobs:loadJobs,health:loadWorkerStatus,diagnostics:loadDiagnostics,
  };
  const names=[...new Set(sections)],results=await Promise.allSettled(names.map(name=>loaders[name]()));
  const errors=[];
  results.forEach((result,index)=>{if(result.status==="fulfilled")pendingSections.delete(names[index]);else{pendingSections.add(names[index]);errors.push(result.reason);}});
  if(restorePending&&!["models","characters","media","projects"].some(name=>pendingSections.has(name))){
    restorePending=false;
    if(!state.projectId&&state.projects.length&&!$("script").value&&!$("reference-upload").files.length)await loadProject(state.projects[0]);
  }
  updateVoiceChoice();renderCurrentResult();connectionState(errors);
  return errors;
}
async function pollStudio(){
  if(polling||startPromise){schedulePolling(1000);return;}
  polling=true;
  try{
    if(needsAuthCheck){await start();return;}
    if($("app").hidden)return;
    const sections=[...pendingSections,"models","jobs","health"];
    if(!$("view-settings").hidden)sections.push("diagnostics");
    const errors=await loadStudioSections(sections);
    if(!errors.length&&draftPending&&state.projectId&&!state.submitting&&!state.uploads)await saveProject(false);
    retryDelay=errors.length?Math.min(30000,retryDelay*2):3000;
    schedulePolling(document.hidden?30000:errors.length?retryDelay:5000);
  }catch(error){connectionState([error]);needsAuthCheck=true;schedulePolling(3000);}
  finally{polling=false;}
}
async function start(){
  if(startPromise)return startPromise;
  startPromise=startStudio();
  try{return await startPromise;}finally{startPromise=null;}
}
async function startStudio(){
  clearTimeout(modelTimer);
  try{
  const auth=await api("/auth/status");state.configured=auth.configured;
  needsAuthCheck=false;
  $("auth").hidden=auth.authenticated;$("app").hidden=!auth.authenticated;
  state.user={username:auth.username||"admin",role:auth.role||"admin"};
  $("auth-description").textContent=auth.configured?"Bem-vindo de volta ao seu estúdio.":"Crie o primeiro usuário administrador para abrir seu estúdio local.";
  $("auth-submit").textContent=auth.configured?"Entrar no estúdio":"Criar meu estúdio";
  if(!auth.authenticated){clearTimeout(saveTimer);state.projectId=null;state.jobs=[];restorePending=true;Object.values(selections).forEach(s=>s.clear());$("delete-dialog").close();connectionState();return;}
  const errors=await loadStudioSections(["characters","media","projects","reactions","models","jobs","health"]);
  retryDelay=3000;schedulePolling(errors.length?3000:5000);
  }catch(error){needsAuthCheck=true;connectionState([error]);schedulePolling(3000);throw error;}
}
$("retry-connection").onclick=safe(async()=>{await start();if(!pendingSections.size)toast("Conexão restabelecida. Seus projetos e trabalhos foram carregados.");});
window.addEventListener("online",()=>schedulePolling(0));
window.addEventListener("pageshow",()=>schedulePolling(0));
window.addEventListener("pagehide",()=>clearTimeout(modelTimer));
document.addEventListener("visibilitychange",()=>{if(!document.hidden)schedulePolling(0);});
safe(start)();


$("export-srt").onclick=safe(async()=>{const p=await saveProject(false);const link=document.createElement("a");link.href="/api/projects/"+p.id+"/subtitles/srt";link.download="legendas.srt";link.click();});
$("new-project").onclick=safe(async()=>{
  clearTimeout(saveTimer);await saveChain.catch(()=>{});
  const voice=$("character").value,language=$("language").value,referenceLanguage=$("reference-language").value;
  state.projectId=null;state.cues=[];$("project-form").reset();
  $("engine").value=state.cloneEngine||defaultClone;$("voice-choice").value="clone";
  $("character").value=voice;$("language").value=language;$("reference-language").value=referenceLanguage;
  $("reference-status").textContent=voice?"Sua voz salva está selecionada para o próximo texto.":"Você também pode enviar a gravação diretamente ao clicar em Gerar voz.";
  setMode("tts");renderCues();renderJobs();view("create");saveDraft();
});

function updateVoiceChoice(){
  const clone=$("voice-choice").value==="clone";
  $("quick-reference").hidden=!clone||state.mode==="asr";
  $("simple-hint").hidden=clone||state.mode==="asr";
  $("character").parentElement.hidden=!clone||state.mode==="asr";
  $("engine-label").hidden=state.mode==="asr";
  if(!state.characters.length)$("new-voice-options").open=true;
  renderSelectedVoice();
}
function renderSelectedVoice(){
  const c=state.characters.find(x=>x.id===$("character").value),box=$("selected-voice"),player=$("selected-voice-audio");
  box.hidden=!c||state.mode==="asr"||$("voice-choice").value!=="clone";
  $("selected-voice-name").textContent=c?"Voz escolhida: "+c.name+" · versão "+c.version:"";
  if(c?.reference_id){const src="/api/characters/"+c.id+"/reference-file";if(player.getAttribute("src")!==src)player.setAttribute("src",src);player.hidden=false;}
  else{player.hidden=true;player.removeAttribute("src");}
}
function chooseSavedVoice(){
  if($("character").value){$("reference-upload").value="";$("quick-transcript").value="";$("voice-choice").value="clone";if(!isClone($("engine").value))$("engine").value=state.cloneEngine||defaultClone;$("new-voice-options").open=false;}
  updateVoiceChoice();modelNotice();renderPreparation();saveDraft();
}
$("character").onchange=chooseSavedVoice;
$("reference-upload").onchange=()=>{if($("reference-upload").files.length){$("character").value="";$("reference-status").textContent="Nova gravação escolhida. A voz será salva e selecionada quando você gerar.";renderSelectedVoice();}};
$("voice-choice").onchange=()=>{
  $("engine").value=$("voice-choice").value==="clone"?(state.cloneEngine||defaultClone):"diagnostic";
  updateVoiceChoice();modelNotice();renderPreparation();saveDraft();
};
$("source-upload").onchange=safe(async e=>{
  if(!e.target.files[0])return;
  $("source-status").textContent="Enviando "+e.target.files[0].name+"…";
  try{const m=await upload(e.target.files[0]);if(!m.audio)throw Error("Escolha um áudio ou vídeo com uma faixa de fala.");selectSource(m.id);}
  catch(error){$("source-status").textContent=error.message;throw error;}
  finally{e.target.value="";}
});
function selectSource(ident){
  if(state.sourceId!==ident){state.cues=[];renderCues();}
  $("source-media").value=ident;state.sourceId=ident;updateSourceStatus();saveDraft();
}
$("source-media").onchange=()=>selectSource($("source-media").value);
function updateSourceStatus(){
  const m=state.media.find(x=>x.id===$("source-media").value);
  $("source-status").textContent=m?m.name+" · "+(m.video?"o vídeo mantém a imagem original":state.mode==="dub"?"o áudio será dublado em um vídeo com fundo simples":"áudio para transcrição"):"Escolha um arquivo para começar.";
}
$("dub-script-import").onchange=safe(async e=>{
  try{if(!e.target.files[0])return;const m=await upload(e.target.files[0]);if(!m.cues?.length)throw Error("Escolha um SRT com falas e tempos válidos.");state.cues=m.cues;renderCues();saveDraft();toast("Falas revisadas importadas. Confira os tempos antes de gerar.");}
  finally{e.target.value="";}
});
$("automatic-dub").onclick=()=>{state.cues=[];renderCues();saveDraft();toast("A fala original será transcrita automaticamente.");};
async function saveQuickReference(){
  const file=$("reference-upload").files[0], transcript=$("quick-transcript").value.trim();
  if(!file)throw Error("Selecione um áudio de referência.");
  $("use-reference").disabled=true;$("reference-status").textContent="Enviando referência para o servidor…";
  try{
    const m=await upload(file);
    const c=await post("/characters",{name:file.name.slice(0,120),reference_id:m.id,reference_text:transcript,language:$("reference-language").value,origin:"own"});
    state.characters.unshift(c);refreshSelectors();renderCharacters();$("character").value=c.id;
    $("reference-upload").value="";$("quick-transcript").value="";
    $("reference-status").textContent="Áudio salvo no servidor. Sua voz está selecionada.";$("new-voice-options").open=false;renderSelectedVoice();saveDraft();
  }finally{$("use-reference").disabled=false;}
}
$("use-reference").onclick=safe(saveQuickReference);
function selectedModels(){
  const ident=state.mode==="asr"?$("asr-engine").value:$("engine").value;
  const model=state.models.find(m=>m.id===ident),ids=[ident];
  if(state.mode==="dub")ids.push($("asr-engine").value||defaultAsr);
  if(model?.reference_text)ids.push(defaultAsr);
  return state.models.filter(m=>ids.includes(m.id));
}
function downloadText(d){
  const amount=n=>n>=1024**3?bytes(n):(Math.max(0,n||0)/1024**2).toFixed(1)+" MiB";
  return (d.stage||"")+(d.total_bytes?" · "+amount(d.downloaded_bytes)+" de "+amount(d.total_bytes):"")+" · "+(d.progress||0)+"%";
}
function renderPreparation(){
  const needed=selectedModels(),missing=needed.filter(m=>!m.available);
  const active=missing.filter(m=>["queued","downloading"].includes(m.download?.status)||m.download?.retry_at);
  const progress=$("preparation-progress");
  progress.hidden=!active.length;
  const downloading=active.find(m=>m.download.status==="downloading");
  if(downloading?.download.total_bytes)progress.value=downloading.download.progress||0;else progress.removeAttribute("value");
  $("retry-preparation").hidden=!missing.some(m=>m.id!=="diagnostic"&&!['queued','downloading'].includes(m.download?.status));
  $("preparation-text").textContent=!needed.length?"Conectando ao servidor…":!missing.length?"Pronto para começar. Envie sua gravação e seu texto; a preparação da voz será automática.":active.length?"Preparando no servidor: "+active.map(m=>m.name+" — "+(m.download.retry_at?"nova tentativa agendada":m.download.status==="queued"?"aguardando":downloadText(m.download))).join(" · ")+". Você já pode enviar o texto; ele começa assim que o modelo ficar pronto.":"Um modelo precisa ser preparado. Use Retomar preparação; seu texto e a fila ficam salvos.";
}
$("retry-preparation").onclick=safe(async()=>{
  $("retry-preparation").disabled=true;
  try{
    await post("/models/prepare");
    for(const m of selectedModels().filter(m=>!m.available&&m.id!=="diagnostic"))await post("/models/"+m.id+"/download",{accept_license:true});
    toast("Preparação retomada. Os trabalhos aguardando começam automaticamente.");await loadModels();await loadJobs();
  }finally{$("retry-preparation").disabled=false;}
});
function renderCurrentResult(){
  const job=state.jobs.find(j=>j.project_id===state.projectId);
  const box=$("current-result");box.hidden=!job;if(!job){delete box.dataset.rendered;return;}
  const seconds=job.status==="running"&&job.started?Math.max(0,Math.floor(Date.now()/1000-job.started)):job.elapsed_seconds;
  const elapsed=seconds!==undefined?Math.floor(seconds/60)+" min "+Math.floor(seconds%60)+" s":"";
  const signature=JSON.stringify([job,elapsed]);if(box.dataset.rendered===signature)return;box.dataset.rendered=signature;
  const i=(job.outputs||[]).findIndex(o=>["audio","video"].includes(o.type)),type=i>=0?job.outputs[i].type:null;
  box.innerHTML='<h2>'+escapeHTML(job.name)+'</h2><p class="job-error">'+escapeHTML(statuses[job.status]+' · '+job.stage)+'</p>'+(job.profile?'<p class="hint">Perfil usado: '+escapeHTML(job.profile.name)+(job.profile.adapted?' · adaptado à RAM disponível':'')+'</p>':'')+'<progress max="100" '+(job.status==="running"&&!job.progress?'':'value="'+(job.progress||0)+'"')+'></progress>'+(elapsed?'<p class="hint">Tempo de processamento: '+elapsed+'</p>':'')+(type?'<'+type+' controls preload="none" src="/api/jobs/'+job.id+'/output/'+i+'"></'+type+'>':'')+'<div class="item-actions">'+outputHTML(job)+(['paused','failed','cancelled'].includes(job.status)?'<button type="button" class="secondary" id="retry-current">Tentar novamente</button>':'')+(['queued','running'].includes(job.status)?'<button type="button" class="quiet" id="cancel-current">Cancelar trabalho</button>':'')+'<button type="button" class="secondary" id="add-another">Adicionar outro texto</button><button type="button" class="quiet" id="diagnose-current">Ver diagnóstico</button></div>';
  $("diagnose-current").onclick=safe(async()=>showDetails("Diagnóstico do trabalho",(await api("/jobs/"+job.id+"/log")).text));
  $("add-another").onclick=()=>$("new-project").click();
  if($("retry-current"))$("retry-current").onclick=safe(async()=>{await post("/jobs/"+job.id+"/resume");await loadJobs();});
  if($("cancel-current"))$("cancel-current").onclick=safe(async()=>{await post("/jobs/"+job.id+"/cancel");await loadJobs();});
}
function renderReactionOptions(){
  const groups=[...new Set(state.reactions.map(x=>x.category))];
  const html=groups.map(group=>'<optgroup label="'+escapeHTML(group)+'">'+state.reactions.filter(x=>x.category===group).map(x=>'<option value="'+escapeHTML(x.id)+'">'+escapeHTML(x.name)+'</option>').join("")+'</optgroup>').join("");
  $("reaction-choice").innerHTML=html;$("character-reaction").innerHTML=html;
}
$("insert-reaction").onclick=()=>{
  const ident=$("reaction-choice").value;if(!ident)return;
  const area=$("script");area.setRangeText('[reacao='+ident+']',area.selectionStart,area.selectionEnd,"end");area.dispatchEvent(new Event("input"));area.focus();
};
$("preview-reaction").onclick=safe(async()=>{
  const ident=$("reaction-choice").value;if(!ident)return;
  const player=$("reaction-preview");player.src="/api/reactions/"+encodeURIComponent(ident)+"/file";player.hidden=false;await player.play();
});
function renderCharacterReactions(){
  $("character-reactions").innerHTML=Object.entries(state.characterReactions).map(([key,ident])=>'<p>'+escapeHTML(state.reactions.find(x=>x.id===key)?.name||key)+' · '+escapeHTML(state.media.find(x=>x.id===ident)?.name||"Gravação salva")+'</p>').join("");
}
$("assign-reaction").onclick=()=>{
  const key=$("character-reaction").value,ident=$("reaction-media").value;
  if(!key||!ident){toast("Escolha a reação e um arquivo com áudio.");return;}
  state.characterReactions[key]=ident;renderCharacterReactions();$("reaction-upload-status").textContent="Reação associada. Salve a voz para preservar a gravação.";
};
$("remove-reaction").onclick=()=>{delete state.characterReactions[$("character-reaction").value];renderCharacterReactions();};
$("reaction-upload").onchange=safe(async e=>{
  const file=e.target.files[0];if(!file)return;const key=$("character-reaction").value;
  const save=$("character-form").querySelector('button[type="submit"]');save.disabled=true;
  $("reaction-upload-status").textContent="Enviando "+file.name+"…";
  try{const m=await upload(file);if(!m.audio)throw Error("A reação precisa conter áudio.");state.characterReactions[key]=m.id;$("reaction-media").value=m.id;renderCharacterReactions();$("reaction-upload-status").textContent="Som enviado e associado. Salve a voz.";}
  catch(error){$("reaction-upload-status").textContent=error.message;throw error;}
  finally{save.disabled=false;e.target.value="";}
});

async function loadWorkerStatus(){
  const response=await fetch("/health",{cache:"no-store",signal:AbortSignal.timeout(20000)});
  if(!response.ok)throw Error("Servidor indisponível.");
  const status=await response.json();
  $("worker-warning").hidden=!!status.worker;
  $("worker-warning").textContent="O executor está parado. Os trabalhos não podem iniciar. Reinicie o aplicativo no servidor e consulte Ajustes se o aviso continuar.";
  $("version").textContent=status.version;
}

function selectionItems(kind){return kind==="results"?state.jobs.filter(j=>!["queued","running"].includes(j.status)):state[kind];}
function selectionHTML(kind,item){return '<label class="selection-check"><input type="checkbox" data-select-kind="'+kind+'" data-select-id="'+item.id+'" aria-label="Selecionar '+escapeHTML(item.name)+'"'+(selections[kind].has(item.id)?' checked':'')+'> Selecionar</label>';}
function deleteHTML(kind,item){return '<button type="button" class="text-button delete-one" data-delete-one="'+item.id+'" data-delete-kind="'+kind+'" aria-label="Excluir '+escapeHTML(item.name)+'">Excluir</button>';}
function renderSelection(kind){
  const valid=new Set(selectionItems(kind).map(x=>x.id));for(const id of selections[kind])if(!valid.has(id))selections[kind].delete(id);
  const count=selections[kind].size,toolbar=document.querySelector('[data-selection-toolbar="'+kind+'"]');
  toolbar.querySelector('[data-selection-count]').textContent=count?count+(kind==="characters"?' selecionada(s)':' selecionado(s)'):(kind==="characters"?'Nenhuma selecionada':'Nenhum selecionado');
  const button=toolbar.querySelector('[data-delete-selected]');button.disabled=!count;button.textContent=(kind==="characters"?'Excluir selecionadas':'Excluir selecionados')+(count?' ('+count+')':'');
  toolbar.querySelector('[data-clear-selection]').hidden=!count;toolbar.querySelector('[data-select-all]').disabled=!valid.size;
  document.querySelectorAll('[data-select-kind="'+kind+'"]').forEach(x=>{x.checked=selections[kind].has(x.dataset.selectId);x.closest('article').classList.toggle('item-selected',x.checked);});
}
document.addEventListener("change",event=>{
  const box=event.target.closest('[data-select-kind]');if(!box)return;const selected=selections[box.dataset.selectKind];if(box.checked)selected.add(box.dataset.selectId);else selected.delete(box.dataset.selectId);renderSelection(box.dataset.selectKind);
});
document.querySelectorAll('[data-select-all]').forEach(b=>b.onclick=()=>{selectionItems(b.dataset.selectAll).forEach(x=>selections[b.dataset.selectAll].add(x.id));renderSelection(b.dataset.selectAll);});
document.querySelectorAll('[data-clear-selection]').forEach(b=>b.onclick=()=>{selections[b.dataset.clearSelection].clear();renderSelection(b.dataset.clearSelection);});
document.querySelectorAll('[data-delete-selected]').forEach(b=>b.onclick=()=>openDelete(b.dataset.deleteSelected,[...selections[b.dataset.deleteSelected]]));
document.addEventListener("click",event=>{const b=event.target.closest('[data-delete-one]');if(b)openDelete(b.dataset.deleteKind,[b.dataset.deleteOne]);});
function openDelete(kind,ids){
  if(!ids.length)return;deletePlan={kind,ids};const names=selectionItems(kind).filter(x=>ids.includes(x.id)).map(x=>x.name);
  $("delete-title").textContent="Excluir "+ids.length+" "+({media:"arquivo(s)",characters:"voz(es)",results:"resultado(s)"}[kind])+"?";
  $("delete-description").textContent={media:"Esta ação apaga os arquivos enviados. Arquivos usados por vozes ou trabalhos que podem ser retomados serão preservados, com o motivo indicado.",characters:"As vozes selecionadas serão removidas. As gravações continuam na biblioteca e os trabalhos já enviados mantêm a voz escolhida.",results:"Esta ação apaga os áudios, vídeos, legendas e o progresso dos trabalhos selecionados. Os projetos e os arquivos originais continuam salvos."}[kind];
  $("delete-items").innerHTML=names.slice(0,10).map(n=>'<li>'+escapeHTML(n)+'</li>').join('')+(names.length>10?'<li>E mais '+(names.length-10)+' itens.</li>':'');
  $("delete-error").hidden=true;$("delete-confirm").hidden=false;$("delete-confirm").disabled=false;$("delete-cancel").textContent="Voltar";$("delete-dialog").showModal();
}
$("delete-cancel").onclick=()=>$("delete-dialog").close();
$("delete-dialog").addEventListener("cancel",event=>{if($("delete-confirm").disabled)event.preventDefault();});
$("delete-confirm").onclick=safe(async()=>{
  if(!deletePlan)return;const {kind,ids}=deletePlan;$("delete-confirm").disabled=true;$("delete-cancel").disabled=true;
  const result={deleted:[],blocked:[],missing:[],cleanup_pending:false};
  try{
    if(saveTimer){clearTimeout(saveTimer);saveTimer=null;await saveProject(false);}else await saveChain.catch(()=>{});
    for(let i=0;i<ids.length;i+=100){const batch=await post("/items/delete",{kind,ids:ids.slice(i,i+100)});for(const key of ['deleted','blocked','missing'])result[key].push(...batch[key]);result.cleanup_pending ||= batch.cleanup_pending;}
    for(const id of [...result.deleted,...result.missing])selections[kind].delete(id);
    if(kind==="characters"&&result.deleted.includes(state.characterId))$("new-character").click();
    if(kind==="media")for(const [reaction,id] of Object.entries(state.characterReactions))if(result.deleted.includes(id))delete state.characterReactions[reaction];
    [state.media,state.characters,state.projects]=await Promise.all([fetchRecords("media",state.mediaLimit),fetchRecords("characters",state.charactersLimit),api("/projects")]);
    refreshSelectors();renderMedia();renderCharacters();renderCharacterReactions();renderProjects();await loadJobs();
    if(kind==="results"){state.jobs=state.jobs.filter(j=>!result.deleted.includes(j.id));delete $("result-list").dataset.rendered;renderJobs();}
    if(result.blocked.length||result.cleanup_pending){
      $("delete-title").textContent=result.deleted.length?"Exclusão concluída com itens preservados":"Estes itens ainda estão em uso";
      $("delete-description").textContent=result.deleted.length+" item(ns) excluído(s). Confira os motivos abaixo.";
      $("delete-items").innerHTML=result.blocked.map(x=>'<li><strong>'+escapeHTML(x.name)+'</strong><br>'+escapeHTML(x.reason)+'</li>').join('');
      if(result.cleanup_pending){$("delete-error").hidden=false;$("delete-error").textContent="Alguns arquivos ainda aguardam limpeza em disco. Ela será tentada novamente ao reiniciar o servidor.";}
      $("delete-confirm").hidden=true;$("delete-cancel").textContent="Fechar";
    }else{$("delete-dialog").close();toast(result.deleted.length+" item(ns) excluído(s).");}
  }catch(error){$("delete-error").hidden=false;$("delete-error").textContent=error.message;throw error;}
  finally{$("delete-confirm").disabled=false;$("delete-cancel").disabled=false;}
});
