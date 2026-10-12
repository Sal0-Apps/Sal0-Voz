# Componentes e referências

A identidade de cores e organização foi inspirada no [Sal0 Karaokê](https://github.com/Sal0-Apps/Sal0-Karaoke). O código deste app e o ícone vetorial foram criados para Sal0 Voz; não foram copiados módulos do Karaokê.

## Modelos preparados pelo aplicativo

| Modelo | Fonte e revisão fixa | Licença | Execução |
|---|---|---|---|
| Qwen3-TTS 1.7B Base | [Qwen/Qwen3-TTS-12Hz-1.7B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base/tree/fd4b254389122332181a7c3db7f27e918eec64e3) · `fd4b254389122332181a7c3db7f27e918eec64e3` | Apache-2.0 | CPU float32/bfloat16, clonagem com áudio e texto |
| Faster-Whisper large-v3-turbo | [dropbox-dash/faster-whisper-large-v3-turbo](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/tree/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf) · `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` | MIT | CPU INT8, transcrição |

O Turbo é a conversão CTranslate2 do [OpenAI whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo). A fonte antes identificada como `mobiuslabsgmbh/faster-whisper-large-v3-turbo` redireciona para o repositório `dropbox-dash`. Seus pesos de origem são FP16; o motor seleciona INT8 ao carregar em CPU.

O download consulta os tamanhos e hashes da fonte na revisão fixa, verifica os arquivos e grava um manifesto SHA-256. Os pesos são preparados após iniciar o app e ficam no volume de dados. Os textos integrais [Apache-2.0 do Qwen3-TTS](licenses/Qwen3-TTS-Apache-2.0.txt) e [MIT do Whisper](licenses/Whisper-MIT.txt) acompanham este repositório e a imagem, em `/app/licenses`.

O perfil opcional [Qwen3-TTS 0.6B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base/tree/5d83992436eae1d760afd27aff78a71d676296fc) usa Apache-2.0 e revisão `5d83992436eae1d760afd27aff78a71d676296fc`. Whisper medium e large-v3 continuam no catálogo opcional com MIT e revisões fixas indicadas em `app/catalog.py`.

## Modelo opcional Chatterbox V3 pt-BR

O download `chatterbox-pt-br` usa [ResembleAI/Chatterbox-Multilingual-pt-br](https://huggingface.co/ResembleAI/Chatterbox-Multilingual-pt-br/tree/b3952f18bc2eaa72b9bd7c17d2c4653bcad4770d), revisão `b3952f18bc2eaa72b9bd7c17d2c4653bcad4770d`: T3 pt-BR, decoder V3 em safetensors e tokenizer. O encoder de voz vem de [ResembleAI/chatterbox](https://huggingface.co/ResembleAI/chatterbox/tree/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18), revisão `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`. Cada arquivo é verificado contra o hash da fonte; o manifesto preserva as duas revisões. Checkpoints alternativos e versões duplicadas do decoder não são baixados.

Modelos e [Chatterbox](https://github.com/resemble-ai/chatterbox) usam MIT. A imagem inclui o código da revisão `5de7a54aa4e5e2baadb0182dde554908b48b85c2` em ambiente CPU separado, com dependências da versão 0.1.7. A licença integral acompanha a imagem em [Chatterbox-MIT.txt](licenses/Chatterbox-MIT.txt). Os pesos pt-BR ficam no volume e são opcionais. A marca d'água nativa Perth permanece na saída.

## Modelos opcionais OmniVoice e VoxCPM2

`omnivoice` usa [k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice/tree/c5fdb5ccb189668d56333f77ba2629f4cd7535f4), revisão `c5fdb5ccb189668d56333f77ba2629f4cd7535f4`, incluindo o codec na subpasta `audio_tokenizer`. Os pesos OmniVoice têm licença CC-BY-NC conforme seu README; o codec preserva seu aviso de licença próprio. O código é instalado da revisão `08be0b4ccbac3e13e374e86fbfead4b4cac343e2` de [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice), com Apache-2.0 em [OmniVoice-Apache-2.0.txt](licenses/OmniVoice-Apache-2.0.txt). Não se baixa Whisper dentro desse motor; a transcrição é preparada pelo aplicativo antes da clonagem.

`voxcpm2` usa os dois arquivos F16 de [DennisHuang648/VoxCPM2-GGUF](https://huggingface.co/DennisHuang648/VoxCPM2-GGUF/tree/169f64d8b98bbaab1761e4ca3a83e6af653456cc), revisão `169f64d8b98bbaab1761e4ca3a83e6af653456cc`, convertidos dos pesos [OpenBMB/VoxCPM2](https://huggingface.co/openbmb/VoxCPM2) com Apache-2.0. A variante Q8 não é baixada. O motor [tc-mb/llama.cpp-omni](https://github.com/tc-mb/llama.cpp-omni) usa a revisão `88bd37eb671f67cf8d747140ed100231756e0bc3`, com licença em [VoxCPM-GGML-MIT.txt](licenses/VoxCPM-GGML-MIT.txt). `scripts/configure_voxcpm.py` aplica o limite de threads e adapta as chamadas de backend e o aviso de cache de macOS para a compilação Linux; não modifica pesos ou fórmulas de síntese. A imagem inclui somente o motor de CPU e bibliotecas; os pesos são opcionais e ficam no volume.

## Bibliotecas e ferramentas

- FastAPI: MIT; Uvicorn: BSD-3-Clause; SQLite: domínio público.
- FFmpeg: LGPL/GPL conforme configuração da distribuição.
- eSpeak NG: GPL-3.0-or-later; usado como voz de diagnóstico.
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS): Apache-2.0.
- [Chatterbox](https://github.com/resemble-ai/chatterbox) e [Perth](https://github.com/resemble-ai/Perth): MIT.
- PyTorch/torchaudio: BSD-style, avisos próprios dos pacotes.
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper)/CTranslate2: MIT.
- Fontes do sistema, sem requisição a Google Fonts.
- Ícone: arte vetorial original Sal0 Voz.

As dependências mantêm seus avisos dentro dos pacotes instalados. Downloads opcionais preservam as licenças presentes nas fontes e registram as revisões. Consulte as licenças antes de redistribuir outros modelos.

As 33 gravações de reações incluídas usam CC0-1.0. Autores, URLs, arquivos originais, alterações e hashes estão em [SOURCES.md](app/assets/reactions/SOURCES.md) e no catálogo ao lado. O cliente Android deriva do Sal0 Karaokê, com origem documentada em [android/README.md](android/README.md).
