/* Sal0 native themes: Cristal, Aurora, Wall and the original app appearance. */
(() => {
  'use strict';
  if (window.Sal0Appearance) return;
  const root = document.documentElement;
  const config = {"button": "theme", "key": "sal0-theme", "source": "body"};
  const storageKey = 'sal0.appearance.v1';
  const looks = {cristal:'Cristal',aurora:'Aurora',wall:'Wall',legacy:'Tema antigo'};
  const defaults = {look:'cristal',motion:true,glass:45};
  let prefs = {...defaults};
  try { const saved=JSON.parse(localStorage.getItem(storageKey)||'{}');
    if (Object.hasOwn(looks,saved.look)) prefs.look=saved.look;
    if (typeof saved.motion==='boolean') prefs.motion=saved.motion;
    if (Number.isFinite(saved.glass)) prefs.glass=Math.max(15,Math.min(65,saved.glass));
  } catch (_) {}
  function persist(){try{localStorage.setItem(storageKey,JSON.stringify(prefs));}catch(_) {}}
  function meta(name,content){let tag=document.querySelector('meta[name="'+name+'"]');if(!tag){tag=document.createElement('meta');tag.name=name;document.head.appendChild(tag);}tag.content=content;}
  function nativeMode(){return config.source==='body'?(document.body.classList.contains('light')?'light':'dark'):(root.dataset.theme==='light'?'light':'dark');}
  function syncMode(){const mode=nativeMode();root.dataset.sal0Mode=mode;if(root.dataset.theme!==mode)root.dataset.theme=mode;meta('color-scheme',mode==='light'?'only light':'dark');meta('theme-color',mode==='light'?'#e8f2fc':'#050b12');updateControls();}
  function setMode(mode){
    if(mode!=='light'&&mode!=='dark')return;
    try{localStorage.setItem(config.key,mode);}catch(_){}
    if(config.source==='root'&&typeof window.setTheme==='function')window.setTheme(mode);
    root.dataset.theme=mode;
    if(config.source==='body')document.body.classList.toggle('light',mode==='light');
    syncMode();
  }
  let dialog,scene,paused,lastWidth,resizeFrame=0;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  function syncMotion(){
    if(!scene)return;
    const next=document.hidden||reduced.matches||!prefs.motion||prefs.look==='legacy';
    if(next===paused)return;
    paused=next;scene.dataset.paused=String(next);
  }
  function apply(){
    root.dataset.sal0Look=prefs.look;root.dataset.sal0Motion=prefs.motion?'on':'off';
    root.style.setProperty('--sal0-glass-alpha',((100-prefs.glass)/100).toFixed(2));
    updateControls();syncMotion();
  }
  function setLook(value){if(!Object.hasOwn(looks,value))return;prefs.look=value;prefs.glass=({cristal:45,aurora:58,wall:36,legacy:prefs.glass})[value];apply();persist();}
  function updateControls(){
    const launcher=document.getElementById(config.button);
    if(launcher&&launcher.classList.contains('sal0-theme-launcher')&&launcher.textContent.trim()!=='Temas')launcher.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2"/><circle cx="15" cy="17" r="2"/></svg><span>Temas</span>';
    if(!dialog)return;
    dialog.querySelectorAll('[data-sal0-choice]').forEach(button=>button.setAttribute('aria-checked',String(button.dataset.sal0Choice===prefs.look)));
    dialog.querySelectorAll('[data-sal0-mode-choice]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.sal0ModeChoice===nativeMode())));
    dialog.querySelector('#sal0-motion').checked=prefs.motion;
    dialog.querySelector('#sal0-glass').value=prefs.glass;
    dialog.querySelector('#sal0-glass-value').textContent=prefs.glass+'%';
    dialog.querySelector('#sal0-glass').disabled=prefs.look==='legacy';
  }
  // Mobile browser chrome changes the visual viewport during scrolling. The
  // background uses the largest stable viewport, never a scroll/visualViewport
  // callback; the fallback is only remeasured after a real width change.
  function lockViewport(force=false){
    if(!scene)return;
    const width=window.innerWidth;
    if(!force&&Math.abs(width-lastWidth)<2)return;
    lastWidth=width;
    if(window.CSS&&CSS.supports('height','100lvh'))return;
    const screenHeight=window.screen&&window.screen.height;
    const height=screenHeight>window.innerHeight&&screenHeight<window.innerHeight*1.4?screenHeight:window.innerHeight;
    scene.style.height=Math.ceil(height)+'px';
  }
  function open(){if(!dialog||dialog.open)return;dialog.showModal();dialog.querySelector('[data-sal0-close]').focus();}
  function mount(){
    if(document.getElementById('sal0-scene'))return;
    const host=document.createElement('div');host.innerHTML="<div class=\"sal0-scene\" aria-hidden=\"true\">\n <div class=\"sal0-liquid-haze\"></div><div class=\"sal0-liquid-haze second\"></div>\n <svg class=\"sal0-ribbons\" viewBox=\"0 0 1600 1200\" preserveAspectRatio=\"xMidYMid slice\" focusable=\"false\">\n <defs>\n <linearGradient id=\"sal0-fluid-depth\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop class=\"sal0-fluid-deep\" offset=\"0\" stop-opacity=\".08\"/><stop class=\"sal0-fluid-deep\" offset=\".24\" stop-opacity=\".75\"/><stop class=\"sal0-fluid-blue\" offset=\".62\" stop-opacity=\".85\"/><stop class=\"sal0-fluid-deep\" offset=\"1\" stop-opacity=\".07\"/></linearGradient>\n <linearGradient id=\"sal0-fluid-soft\" x1=\"0\" y1=\"1\" x2=\"1\" y2=\"0\"><stop class=\"sal0-fluid-deep\" offset=\"0\" stop-opacity=\"0\"/><stop class=\"sal0-fluid-blue\" offset=\".5\" stop-opacity=\".65\"/><stop class=\"sal0-fluid-deep\" offset=\"1\" stop-opacity=\".1\"/></linearGradient>\n <linearGradient id=\"sal0-fluid-edge\"><stop class=\"sal0-fluid-ice\" stop-opacity=\"0\"/><stop class=\"sal0-fluid-ice\" offset=\".38\" stop-opacity=\".56\"/><stop class=\"sal0-fluid-blue\" offset=\".72\" stop-opacity=\".2\"/><stop class=\"sal0-fluid-ice\" offset=\"1\" stop-opacity=\"0\"/></linearGradient>\n </defs>\n<path class=\"sal0-liquid-ribbon\" d=\"M-260 210.56 C-100.00 341.53 60.00 548.53 220.00 548.89 C380.00 549.24 540.00 471.78 700.00 413.17 C860.00 354.57 1020.00 196.43 1180.00 143.77 C1406.67 69.17 1633.33 494.72 1860.00 542.66 L1860 743.21 C1633.33 695.27 1406.67 269.72 1180.00 344.32 C1020.00 396.97 860.00 555.12 700.00 613.72 C540.00 672.32 380.00 749.79 220.00 749.44 C60.00 749.08 -100.00 542.08 -260.00 411.11 Z\"></path><path class=\"sal0-liquid-ribbon lower\" d=\"M-260 910.09 C-100.00 1060.83 60.00 1134.30 220.00 1079.11 C380.00 1023.93 540.00 1009.39 700.00 967.35 C860.00 925.32 1020.00 751.20 1180.00 757.82 C1406.67 767.19 1633.33 1154.75 1860.00 1097.42 L1860 1347.97 C1633.33 1405.30 1406.67 1017.74 1180.00 1008.37 C1020.00 1001.75 860.00 1175.86 700.00 1217.90 C540.00 1259.94 380.00 1274.48 220.00 1329.66 C60.00 1384.84 -100.00 1311.38 -260.00 1160.64 Z\"></path><path class=\"sal0-liquid-contour\" d=\"M-260 210.56 C-100.00 341.53 60.00 548.53 220.00 548.89 C380.00 549.24 540.00 471.78 700.00 413.17 C860.00 354.57 1020.00 196.43 1180.00 143.77 C1406.67 69.17 1633.33 494.72 1860.00 542.66\"></path><path class=\"sal0-liquid-contour lower\" d=\"M-260 910.09 C-100.00 1060.83 60.00 1134.30 220.00 1079.11 C380.00 1023.93 540.00 1009.39 700.00 967.35 C860.00 925.32 1020.00 751.20 1180.00 757.82 C1406.67 767.19 1633.33 1154.75 1860.00 1097.42\"></path>\n </svg><div class=\"scene-grid\"></div>\n</div>";
    scene=host.firstElementChild;scene.id='sal0-scene';document.body.prepend(scene);
    // Keep a single native-sized header control. The color choices live in the menu.
    const button=document.getElementById(config.button);if(!button)return;
    button.type='button';button.classList.add('sal0-theme-launcher');
    button.style.removeProperty('padding');button.style.removeProperty('font-size');
    button.setAttribute('aria-label','Escolher tema visual');button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');button.title='Temas: Cristal, Aurora, Wall e antigo';
    dialog=document.createElement('dialog');dialog.id='sal0-theme-dialog';dialog.className='sal0-theme-dialog';dialog.setAttribute('aria-labelledby','sal0-theme-title');
    dialog.innerHTML='<div class="sal0-dialog-heading"><h2 id="sal0-theme-title">Temas</h2><button type="button" data-sal0-close aria-label="Fechar temas">×</button></div><p class="sal0-dialog-note">A aparência do app, do seu jeito.</p><div class="sal0-look-options" role="radiogroup" aria-label="Estilo visual">'+Object.entries(looks).map(([id,name])=>'<button type="button" role="radio" data-sal0-choice="'+id+'" aria-checked="false"><span class="sal0-theme-sample sal0-sample-'+id+'" aria-hidden="true"></span><strong>'+name+'</strong><small>'+({cristal:'Vidro equilibrado',aurora:'Mais luz e fluidez',wall:'Painel compacto',legacy:'Visual original deste app'})[id]+'</small></button>').join('')+'</div><div class="sal0-mode-options" role="group" aria-label="Modo de cor"><button type="button" data-sal0-mode-choice="dark">Escuro</button><button type="button" data-sal0-mode-choice="light">Claro</button></div><label class="sal0-glass-label" for="sal0-glass">Transparência <output id="sal0-glass-value"></output></label><input id="sal0-glass" type="range" min="15" max="65" step="1"><label class="sal0-motion-label"><span>Animações suaves<small>Respeita o movimento reduzido do aparelho.</small></span><input id="sal0-motion" type="checkbox" role="switch"></label>';
    document.body.appendChild(dialog);
    button.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();open();button.setAttribute('aria-expanded','true');},true);
    dialog.querySelector('[data-sal0-close]').addEventListener('click',()=>dialog.close());
    dialog.addEventListener('click',event=>{
      if(event.target===dialog){const b=dialog.getBoundingClientRect();if(event.clientX<b.left||event.clientX>b.right||event.clientY<b.top||event.clientY>b.bottom)dialog.close();}
      const choice=event.target.closest('[data-sal0-choice]');if(choice)setLook(choice.dataset.sal0Choice);
      const mode=event.target.closest('[data-sal0-mode-choice]');if(mode)setMode(mode.dataset.sal0ModeChoice);
    });
    dialog.addEventListener('close',()=>{button.setAttribute('aria-expanded','false');button.focus();});
    dialog.querySelector('#sal0-motion').addEventListener('change',event=>{prefs.motion=event.target.checked;apply();persist();});
    dialog.querySelector('#sal0-glass').addEventListener('input',event=>{prefs.glass=Number(event.target.value);apply();persist();});
    new MutationObserver(syncMode).observe(config.source==='body'?document.body:root,{attributes:true,attributeFilter:[config.source==='body'?'class':'data-theme']});
    document.addEventListener('visibilitychange',syncMotion);
    if(reduced.addEventListener)reduced.addEventListener('change',syncMotion);else if(reduced.addListener)reduced.addListener(syncMotion);
    window.addEventListener('resize',()=>{if(!resizeFrame)resizeFrame=requestAnimationFrame(()=>{resizeFrame=0;lockViewport();});},{passive:true});
    window.addEventListener('orientationchange',()=>{lastWidth=-1;},{passive:true});
    lockViewport(true);apply();syncMode();
  }
  meta('darkreader-lock','');
  root.dataset.sal0Look=prefs.look;
  window.Sal0Appearance=Object.freeze({open,setLook,setMode});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
