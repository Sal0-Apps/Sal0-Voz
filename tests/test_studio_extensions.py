import io
import json
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from app import storage as s
from app.catalog import models_needed
from app.engine_policy import choose_profile, MemoryUnavailable
from app.media import ffargs, probe
from app.output_names import output_name, safe_name
from app.reactions import catalog, synthesis_text
from app.script import compile_script
from app.worker import Worker

def audio_bytes(seconds=6):
    samples = (np.sin(2*np.pi*180*np.arange(24000*seconds)/24000)*10000).astype('<i2')
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(samples.tobytes())
    return out.getvalue()

def test_reaction_catalog_exposes_generation_and_only_supported_native_tags():
    items = catalog()
    assert len(items) >= 30 and len({x['id'] for x in items}) == len(items)
    for item in items:
        assert item['generation'] == 'selected_voice' and 'file' not in item
        for engine in ('omnivoice', 'voxcpm2', 'qwen-1.7b', 'qwen-0.6b', 'chatterbox-pt-br', 'diagnostic'):
            text = synthesis_text(item['id'], engine)
            assert text and item['name'].lower() not in text.lower()
            assert text.startswith('[') == (engine in item['native_models'])
    assert synthesis_text('risada', 'omnivoice') == '[laughter]'
    assert synthesis_text('risada', 'voxcpm2') == '[laughing]'
    assert synthesis_text('gemido', 'omnivoice') == 'Ah... mmh...'
    assert synthesis_text('espirro', 'qwen-1.7b', 'en-US') == 'Achoo!'

def test_reactions_preserve_speech_and_never_become_tts_labels():
    result = compile_script('Olá! [reacao=risada][pausa=100ms][volume=-3][reacao=gemido][/volume] Fim.')
    assert ''.join(x['text'] for x in result) == 'Olá!  Fim.'
    assert result[1]['reaction'] == 'risada' and result[3]['reaction'] == 'gemido'
    assert result[3]['volume'] == -3 and result[4]['volume'] == 0
    assert compile_script('[reacao=choro]')[0]['text'] == ''
    with pytest.raises(ValueError, match='Reação desconhecida'):
        compile_script('[reacao=impossivel]')

def test_reaction_only_export_uses_selected_voice_and_reuses_checkpoints(owner, data, monkeypatch):
    import app.worker as module
    ref = owner.post('/api/media', files={'file':('ref.wav',audio_bytes())}).json()
    voice = owner.post('/api/characters', json={'name':'Minha voz','reference_id':ref['id'],'reference_text':'Minha gravação.'}).json()
    project = owner.post('/api/projects', json={'name':'Reações','engine':'omnivoice','character_id':voice['id'],'text':'[reacao=risada][pausa=100ms][reacao=gemido]', 'audio_name':'Cena'}).json()
    response = owner.post('/api/projects/'+project['id']+'/generate')
    assert response.status_code == 200, response.text
    job = s.get('job', response.json()['id'])
    assert models_needed(job['snapshot']) == ['omnivoice']
    assert choose_profile(job['snapshot'], available=10*1024**3)['engine'] == 'omnivoice'
    assert [x['id'] for x in s.listing('model_download', limit=-1)] == ['omnivoice']
    assert s.listing('model_download', limit=-1)[0]['status'] == 'queued'
    worker = Worker()
    calls=[]
    def engine(ident,request,folder):
        calls.append(request)
        type(data)(request['output']).write_bytes(audio_bytes(1))
    monkeypatch.setattr(worker, 'engine', engine)
    worker.update(job['id'], status='running'); worker.execute(job)
    result = s.get('job',job['id'])
    assert [x['text'] for x in result['cues']] == ['[risada]','[gemido de dor]']
    assert result['outputs'][0]['name'] == 'Cena.wav'
    assert probe(s.safe_path(result['outputs'][0]['path']))['duration'] > 2
    assert [x['text'] for x in calls] == ['[laughter]','Ah... mmh...']
    assert all(x['engine']=='omnivoice' and x['reference_text']=='Minha gravação.' for x in calls)
    assert calls[0]['reference']==calls[1]['reference']
    assert Worker.speech_started(result['snapshot'], data/'jobs'/job['id'])
    worker.execute(s.get('job',job['id']))
    assert len(calls)==2
    assert owner.get('/api/reactions/risada/file').status_code == 410

def test_reaction_only_requires_voice_reference(owner):
    project=owner.post('/api/projects',json={'name':'Reação','engine':'omnivoice','text':'[reacao=risada]'}).json()
    response=owner.post('/api/projects/'+project['id']+'/generate')
    assert response.status_code==400 and 'referência' in response.text

def test_reactions_follow_each_selected_character_and_ignore_legacy_audio(owner,data,monkeypatch):
    ref1=owner.post('/api/media',files={'file':('one.wav',audio_bytes())}).json()
    ref2=owner.post('/api/media',files={'file':('two.wav',audio_bytes(4))}).json()
    voices=[owner.post('/api/characters',json={'name':name,'reference_id':ref['id'],'reference_text':text}).json()
            for name,ref,text in [('Um',ref1,'Referência um.'),('Dois',ref2,'Referência dois.')]]
    script='Olá! [reacao=risada][personagem='+voices[1]['id']+'][reacao=suspiro] Fim.'
    project=owner.post('/api/projects',json={'name':'Duas vozes','engine':'omnivoice','character_id':voices[0]['id'],'text':script}).json()
    job=s.get('job',owner.post('/api/projects/'+project['id']+'/generate').json()['id'])
    folder=data/'jobs'/job['id'];folder.mkdir(exist_ok=True)
    from app.audio_files import checkpoint_audio
    # Reuse good speech; discard old clip-based reactions without opening them.
    for index in (0,1,2):
        for prefix in ('raw','segment'):
            path=folder/f'{prefix}-{index:06d}.wav';path.write_bytes(audio_bytes(1));checkpoint_audio(path)
    good=s.digest(folder/'segment-000000.wav')
    job['snapshot']['segments'][1]['reaction_media']={'path':'media/missing-old-clip.wav'}
    job['snapshot']['segments'][2]['reaction_media']={'path':'media/missing-own-recording.wav'}
    s.put('job',job)
    calls=[];worker=Worker()
    def engine(ident,request,directory):
        calls.append(request);type(data)(request['output']).write_bytes(audio_bytes(1))
    monkeypatch.setattr(worker,'engine',engine)
    worker.update(job['id'],status='running');worker.execute(job)
    assert [x['text'] for x in calls]==['[laughter]','[sigh]',' Fim.']
    assert calls[0]['reference_text']=='Referência um.'
    assert calls[1]['reference_text']==calls[2]['reference_text']=='Referência dois.'
    assert calls[0]['reference']!=calls[1]['reference']==calls[2]['reference']
    assert s.digest(folder/'segment-000000.wav')==good
    worker.execute(s.get('job',job['id']));assert len(calls)==3

def test_reaction_raw_checkpoint_survives_interruption(owner,data,monkeypatch):
    from app.audio_files import checkpoint_audio
    from app.resources import ProcessInterrupted
    ref=owner.post('/api/media',files={'file':('ref.wav',audio_bytes())}).json()
    voice=owner.post('/api/characters',json={'name':'Voz','reference_id':ref['id'],'reference_text':'Minha gravação.'}).json()
    project=owner.post('/api/projects',json={'name':'Reação','engine':'omnivoice','character_id':voice['id'],'text':'[reacao=risada]'}).json()
    job=s.get('job',owner.post('/api/projects/'+project['id']+'/generate').json()['id'])
    worker=Worker();calls=[]
    def engine(ident,request,folder):
        calls.append(request)
        path=type(data)(request['output']);path.write_bytes(audio_bytes(1));checkpoint_audio(path)
        raise ProcessInterrupted('Confirmação interrompida')
    monkeypatch.setattr(worker,'engine',engine)
    worker.update(job['id'],status='running')
    with pytest.raises(ProcessInterrupted):worker.execute(job)
    worker.execute(s.get('job',job['id']))
    assert len(calls)==1 and s.get('job',job['id'])['outputs']

def test_voxcpm_style_retries_regenerate_old_spoken_instructions(owner,data,monkeypatch):
    from app.audio_files import checkpoint_audio
    ref=owner.post('/api/media',files={'file':('ref.wav',audio_bytes())}).json()
    voice=owner.post('/api/characters',json={'name':'Voz','reference_id':ref['id']}).json()
    project=owner.post('/api/projects',json={'name':'Tom','engine':'voxcpm2','voice_style':'excited','character_id':voice['id'],'text':'Olá! Tudo bem?'}).json()
    job=s.get('job',owner.post('/api/projects/'+project['id']+'/generate').json()['id'])
    folder=data/'jobs'/job['id'];folder.mkdir(exist_ok=True)
    for prefix in ('raw','segment'):
        path=folder/(prefix+'-000000.wav');path.write_bytes(audio_bytes(1));checkpoint_audio(path)
    calls=[];worker=Worker()
    def engine(ident,request,directory):
        assert request['engine']=='voxcpm2' # No unnecessary ASR for isolated style cloning.
        calls.append(request);type(data)(request['output']).write_bytes(audio_bytes(1))
    monkeypatch.setattr(worker,'engine',engine)
    worker.update(job['id'],status='running');worker.execute(job)
    assert [x['text'] for x in calls]==['Olá! Tudo bem?']
    assert all(x['voice_style']=='excited' and x['reference_text']=='' for x in calls)
    worker.execute(s.get('job',job['id']));assert len(calls)==1

def test_video_reference_and_unusual_extensions_are_converted(owner, data):
    source = data/'media'/'source.mkv'
    subprocess.run(ffargs('-f','lavfi','-i','color=c=blue:s=160x90:r=25','-f','lavfi','-i','sine=frequency=180:sample_rate=24000','-t','4','-c:v','libx264','-c:a','aac',source),check=True)
    for name in ['recording.unusual', 'recording']:
        response = owner.post('/api/media', files={'file':(name, source.read_bytes(), 'application/octet-stream')})
        assert response.status_code == 200, response.text
        media = response.json(); assert media['audio'] and media['video']
        voice = owner.post('/api/characters', json={'name':'Minha voz','reference_id':media['id']}).json()
        preview = owner.get('/api/characters/'+voice['id']+'/reference-file')
        with wave.open(io.BytesIO(preview.content)) as wav:
            assert (wav.getnchannels(),wav.getframerate(),wav.getsampwidth()) == (1,24000,2)
            assert wav.getnframes()/24000 > 3.9
        assert owner.get('/api/media/'+media['id']+'/file').content == source.read_bytes()
    playlist = b'ffconcat version 1.0\nfile /etc/passwd\n'
    assert owner.post('/api/media',files={'file':('input.wav',playlist)}).status_code == 400
    suspicious = owner.post('/api/media',files={'file':('reference.html',audio_bytes(1))}).json()
    assert owner.get('/api/media/'+suspicious['id']+'/file').headers['content-type'] == 'application/octet-stream'

def test_voice_reactions_are_frozen_and_private(owner):
    media = owner.post('/api/media',files={'file':('own-reaction.wav',audio_bytes(1))}).json()
    ref = owner.post('/api/media',files={'file':('reference.wav',audio_bytes())}).json()
    voice = owner.post('/api/characters',json={'name':'Minha voz','reference_id':ref['id'],'reference_text':'Minha gravação.','reactions':{'risada':media['id']}}).json()
    project = owner.post('/api/projects',json={'name':'Cena','character_id':voice['id'],'text':'[reacao=risada]'}).json()
    ident = owner.post('/api/projects/'+project['id']+'/generate').json()['id']
    owner.put('/api/characters/'+voice['id'],json={'name':'Minha voz nova','reactions':{}})
    segment = s.get('job',ident)['snapshot']['segments'][0]
    assert segment['character']['name'] == 'Minha voz' and segment['character']['reference']['id'] == ref['id']
    assert 'reaction_media' not in segment
    owner.post('/api/users',json={'username':'maria','password':'test-password'})
    owner.post('/api/auth/logout');owner.post('/api/auth/login',json={'username':'maria','password':'test-password'})
    assert owner.post('/api/characters',json={'name':'Outra','reactions':{'risada':media['id']}}).status_code == 403
    assert owner.get('/api/characters/'+voice['id']+'/reference-file').status_code == 403

def test_download_names_are_numbered_atomically_and_survive_restart(data):
    project = {'mode':'tts','engine':'qwen-1.7b','character_id':'voice-1','segments':[{'character':{'name':'Luna'}}]}
    with ThreadPoolExecutor(max_workers=5) as executor:
        names = list(executor.map(lambda _: output_name(project,'admin'), range(10)))
    assert set(names) == {f'Luna {i}' for i in range(1,11)}
    s.init(); assert output_name(project,'admin') == 'Luna 11'
    assert output_name({**project,'audio_name':'Minha cena.wav'},'admin') == 'Minha cena'
    assert output_name(project,'maria') == 'Luna 1'
    assert safe_name('../Pasta/arquivo\n.wav') == 'Pasta arquivo'

def test_memory_policy_adapts_and_never_retries_an_oom_profile():
    project = {'mode':'tts','engine':'qwen-1.7b'}
    assert choose_profile(project, available=10*1024**3)['engine'] == 'qwen-1.7b'
    assert choose_profile(project, available=10_000_000_000)['engine'] == 'qwen-1.7b'
    assert choose_profile(project, available=10_000_000_000)['dtype'] == 'bfloat16'
    assert choose_profile({**project,'engine':'qwen-0.6b'}, available=4*1024**3)['dtype'] == 'bfloat16'
    with pytest.raises(MemoryUnavailable): choose_profile(project, available=4*1024**3)
    assert choose_profile({**project,'memory_failed_profiles':['qwen-1.7b/float32']},available=12*1024**3)['dtype'] == 'bfloat16'
    assert choose_profile({**project,'mode':'asr'}, available=2*1024**3) is None
    with pytest.raises(MemoryUnavailable): choose_profile(project,available=3*1024**3)
    with pytest.raises(MemoryUnavailable): choose_profile({**project,'adaptive_memory':False},available=4*1024**3)
    with pytest.raises(MemoryUnavailable): choose_profile(project,available=4*1024**3,locked=True)
    assert choose_profile({**project,'engine':'qwen-0.6b'},available=12*1024**3)['engine']=='qwen-0.6b'

def test_queue_recovers_from_memory_failure_with_same_model_economically(data,monkeypatch):
    import app.worker as module
    import app.engine_policy as policy
    monkeypatch.setattr(policy,'memory_available',lambda:12*1024**3)
    monkeypatch.setattr(policy,'cgroup_memory',lambda:(12*1024**3,0))
    monkeypatch.setattr(module,'require',lambda *args:{'id':args[0]})
    worker=Worker();attempts=[]
    clock=[1000]
    from types import SimpleNamespace
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=lambda:clock[0], monotonic=lambda:clock[0]))
    monkeypatch.setattr(worker.wake, 'wait', lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    job=s.put('job',{'status':'queued','snapshot':{'mode':'tts','engine':'qwen-1.7b','segments':[{'text':'Oi.'}]}})
    def execute(value):
        profile=s.get('job',value['id'])['profile'];attempts.append(profile)
        if len(attempts)==1:raise MemoryUnavailable(9.5,8)
    monkeypatch.setattr(worker,'execute',execute)
    monkeypatch.setattr(worker,'check',lambda _:None)
    monkeypatch.setattr(module,'notify_job',lambda _:worker.stop_event.set())
    monkeypatch.setattr(worker.stop_event,'wait',lambda _:None)
    worker.loop()
    result=s.get('job',job['id'])
    assert result['status']=='completed' and result['error'] is None
    assert [x['dtype'] for x in attempts]==['float32','bfloat16']
    assert all(x['engine']=='qwen-1.7b' for x in attempts)

def test_video_is_dubbed_without_srt_and_keeps_all_transcribed_text(owner,data,monkeypatch):
    import app.main as main
    import app.worker as module
    monkeypatch.setattr(main,'require',lambda *args:{'id':args[0], 'revision':'fixed'})
    monkeypatch.setattr(module,'require',lambda *args:{'id':args[0], 'revision':'fixed'})
    source = data/'media'/'video.mp4'
    subprocess.run(ffargs('-f','lavfi','-i','color=c=blue:s=160x90:r=25','-f','lavfi','-i','sine=frequency=180:sample_rate=24000','-t','4','-c:v','libx264','-c:a','aac',source),check=True)
    media = owner.post('/api/media',files={'file':('video.mp4',source.read_bytes())}).json()
    ref = owner.post('/api/media',files={'file':('reference.wav',audio_bytes())}).json()
    voice = owner.post('/api/characters',json={'name':'Minha voz','reference_id':ref['id'],'reference_text':'Texto da referência.'}).json()
    project = owner.post('/api/projects',json={'name':'Dublagem','mode':'dub','media_id':media['id'],'character_id':voice['id']}).json()
    response = owner.post('/api/projects/'+project['id']+'/generate')
    assert response.status_code == 200,response.text
    job = s.get('job',response.json()['id']);assert job['snapshot']['automatic_dub']
    assert models_needed(job['snapshot']) == ['qwen-1.7b','whisper-large-v3-turbo']
    worker=Worker();calls=[]
    def engine(ident,request,folder):
        calls.append(request)
        if request['engine'].startswith('whisper'):
            Path = type(source)
            Path(request['output']).write_text(json.dumps([{'start_ms':1000,'end_ms':2000,'text':'Todo o texto [literal]. Outra frase!'}]))
        else:
            type(source)(request['output']).write_bytes(audio_bytes(3))
    monkeypatch.setattr(worker,'engine',engine)
    worker.update(job['id'],status='running');worker.execute(job)
    result = s.get('job',job['id'])
    assert result['cues'][0]['text'] == 'Todo o texto [literal]. Outra frase!'
    assert calls[0]['engine'] == 'whisper-large-v3-turbo'
    assert [x['text'] for x in calls if x['engine']=='qwen-1.7b']==['Todo o texto [literal]. Outra frase!']
    assert calls[-1]['reference_text'] == 'Texto da referência.'
    info = probe(s.safe_path(result['outputs'][0]['path']))
    assert info['video'] and info['audio'] and abs(info['duration']-4) < .15
    fitted = sorted((data/'jobs'/job['id']).glob('fitted-0-*.wav'))[-1]
    with wave.open(str(fitted)) as wav:
        assert wav.getnframes()/wav.getframerate() <= 1
    assert result['outputs'][0]['name'] == 'Minha voz 1.mp4'
    previous = len(calls);worker.execute(s.get('job',job['id']))
    assert len(calls) == previous

def test_whole_text_keeps_one_voice_model_and_one_process(owner,data,monkeypatch):
    import app.main as main
    import app.worker as module
    monkeypatch.setattr(main,'require',lambda *args:{'id':args[0],'revision':'fixed'})
    monkeypatch.setattr(module,'require',lambda *args:{'id':args[0],'revision':'fixed'})
    ref=owner.post('/api/media',files={'file':('ref.wav',audio_bytes())}).json()
    voice=owner.post('/api/characters',json={'name':'Minha voz','reference_id':ref['id'],'reference_text':'Minha gravação.'}).json()
    project=owner.post('/api/projects',json={'name':'Frases','text':'Primeira! Segunda? Terceira.','engine':'qwen-1.7b','character_id':voice['id']}).json()
    job=s.get('job',owner.post('/api/projects/'+project['id']+'/generate').json()['id'])
    sessions=[];requests=[]
    class Session:
        def __init__(self,*args):sessions.append(self);self.closed=False
        def generate(self,request):
            requests.append(request);type(data)(request['output']).write_bytes(audio_bytes(1))
        def close(self):self.closed=True
    monkeypatch.setattr(module,'EngineSession',Session)
    worker=Worker();worker.update(job['id'],status='running');worker.execute(job)
    assert len(sessions)==1 and sessions[0].closed
    assert [x['text'] for x in requests]==['Primeira! Segunda? Terceira.']
    assert all(x['engine']=='qwen-1.7b' for x in requests)
    result=s.get('job',job['id'])
    assert len(result['cues'])==1 and abs(probe(s.safe_path(result['outputs'][0]['path']))['duration']-1)<.01

def test_manual_dubbing_cue_can_have_multiple_sentences(owner,monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,'require',lambda *args:{'id':args[0]})
    media=s.put('media',{'audio':True,'video':True,'duration':5,'path':'media/source.mp4','owner_username':'admin'})
    project=owner.post('/api/projects',json={'name':'Cena','mode':'dub','engine':'diagnostic','media_id':media['id'],'cues':[{'start_ms':0,'end_ms':4000,'text':'Olá! Tudo bem?'}]}).json()
    response=owner.post('/api/projects/'+project['id']+'/generate')
    assert response.status_code==200,response.text
    segments=s.get('job',response.json()['id'])['snapshot']['segments']
    assert [x['text'] for x in segments]==['Olá! Tudo bem?']
    assert all(x['cue_index']==0 and x['start_ms']==0 and x['end_ms']==4000 for x in segments)
