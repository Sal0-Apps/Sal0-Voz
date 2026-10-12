# Sal0 Voz

<img src="app/static/icon-512.png" width="96" alt="Sal0 Voz">

Estúdio pessoal de voz para **Docker no ZimaOS**, com interface em português, personagens versionados, roteiros, fila persistente e processamento local em CPU.

**Versão 0.3.4 — Chatterbox V3 pt-BR opcional, com clonagem em CPU e ajuste de expressividade.** Mantém os modelos incluídos, o uso de disco para reduzir RAM e a retomada automática. Configuração para quatro núcleos/16 GB de RAM, com limite de 10 GiB do container. A fidelidade e o tempo de geração precisam ser avaliados com a gravação do proprietário no servidor alvo.

## Instalar no ZimaOS

1. Importe [docker-compose.yml](docker-compose.yml) como aplicativo personalizado.
2. Confira a pasta de dados: o exemplo usa `/DATA/AppData/sal0-voz`.
3. Inicie e abra **http://IP-DO-ZIMAOS:7886**.
4. Crie sua senha local.
5. Em **Criar voz**, envie uma gravação limpa, escolha o idioma da gravação e escreva o novo texto.
6. Clique em **Gerar voz**. O app prepara e transcreve a referência automaticamente, usa a clonagem completa do Qwen e mostra o resultado na mesma tela.
7. Clique em **Adicionar outro texto** para reutilizar a voz salva. Para legendas, envie o áudio diretamente em **Gerar legendas**.

A imagem usada pelo Compose é `ghcr.io/sal0-apps/sal0-voz:latest`. O workflow **CI e imagem Docker** verifica o código, a interface e a inicialização da imagem antes de publicar `latest`, a versão fixa `0.3.4` e o SHA do commit para rollback.

**Qwen3-TTS 1.7B/0.6B Base e Faster-Whisper large-v3-turbo já vêm na imagem**, com revisões fixas e hashes verificados na construção. Ficam em `/opt/sal0-models/models`, fora de `/data`, para que o volume de uma instalação nova ou antiga não esconda os pesos. O Whisper transcreve a referência e as legendas em CPU INT8; o Qwen reproduz a voz em CPU float32 ou bfloat16. Não é necessário instalar CUDA ou baixar os modelos separadamente.

O perfil **Mais leve · Qwen 0.6B** também vem incluído e pode ser escolhido se você preferir um modelo menor. A fila preserva o texto durante downloads interrompidos e permite retomar a preparação. `whisper-medium` e `whisper-large-v3` continuam como opções para projetos existentes. Se o pacote GHCR estiver privado, o administrador deve torná-lo público para permitir download anônimo pelo ZimaOS.

### Clonagem com mais expressão em português

Em **Ajustes → Modelos do aplicativo**, prepare **Expressiva · Chatterbox V3 pt-BR**. Também pode selecioná-lo no passo 3 de Criar voz e clicar em **Baixar no servidor**. É um download opcional de aproximadamente **3 GiB**, salvo no volume; não ocorre ao iniciar o aplicativo. Depois, escolha uma voz salva ou envie uma gravação, selecione esse modelo e gere. A dublagem usa a mesma opção.

O perfil usa os pesos oficiais especializados em português brasileiro e o decoder V3, em CPU float32. A reserva inicial é de 6,5 GiB mais margem; é uma política de preparação, sem medição no A10. O consumo real e a qualidade continuam sujeitos à avaliação no servidor. Os ambientes são separados, o modelo carrega uma vez por execução e referências/trechos concluídos ficam no disco. Ele dispensa a transcrição da referência; Whisper é usado apenas se a operação precisar transcrever a mídia original.

O controle **Expressividade** começa em 0,70. 0,50 é mais discreto, e valores maiores intensificam a interpretação e podem acelerar a fala. A referência influencia a voz e o estilo. O controle não escolhe emoções específicas nem garante que todas as vozes fiquem melhores que no Qwen. O modelo é destinado à saída em pt-BR; para inglês, use Qwen. O áudio mantém a marca d'água nativa do Chatterbox.

O Compose personalizado do servidor usa quatro CPUs e limite de 10 GiB, preservando o volume existente. Esse arquivo é entregue separadamente; os templates genéricos do repositório continuam como estavam. O modelo escolhido é mantido em todo o áudio. Em um container limitado a 10 GiB, o padrão usa Qwen 1.7B econômico antes da primeira fala, preservando margem de memória. Antes da primeira frase, o app pode usar o modo econômico do mesmo modelo, com margens de 9,5/6,0 GiB para 1.7B float32/bfloat16 e 5,5/3,25 GiB para 0.6B, mais reserva para iniciar o processo. Se ocorrer falta de RAM antes de confirmar uma fala, tenta a precisão econômica do mesmo modelo. Depois de confirmar fala, mantém modelo e precisão. Se o modelo escolhido não couber, aguarda RAM; não troca automaticamente 1.7B por 0.6B. O painel mostra memória efetiva para o app, incluindo o limite do container. São margens de preparação, sujeitas ao consumo real. A geração em CPU pode levar vários minutos; o navegador pode ser fechado enquanto o servidor trabalha.

## O que está implementado

- Identidade Sal0, ícones SVG/PNG/ICO locais, tema claro/escuro e interface para computador/celular.
- Contas de usuários e administradores, sessões, proteção de origem e arquivos acessíveis somente após login.
- Configuração de Telegram por usuário para receber status e arquivos concluídos diretamente do servidor.
- Upload na Biblioteca e em Minhas vozes; formatos de áudio/vídeo reconhecidos por FFmpeg são validados pelo conteúdo e convertidos automaticamente para a referência. Arquivos originais são preservados.
- Personagens com versões imutáveis; trabalhos preservam uma cópia do personagem usado.
- Editor com autosave, projetos e histórico de revisões.
- VoiceScript: personagem, idioma, pausa exata, ritmo, volume e reações. Texto dividido por pontuação, com frases longas subdivididas; mesmo modelo durante todo o áudio e um processo de voz ativo por vez.
- Fila SQLite, um executor pesado por vez, pausa, cancelamento da árvore de processos e retomada automática após falta de RAM/interrupção, por checkpoint validado com SHA-256. Intervalo crescente entre tentativas; pausa e cancelamento manuais são respeitados.
- TTS de diagnóstico real em pt-BR/en-US com eSpeak NG.
- Adaptadores locais Qwen3-TTS 1.7B/0.6B Base e Chatterbox V3 pt-BR (clonagem), e Faster-Whisper large-v3-turbo/medium/large-v3 CPU INT8.
- Referência mono a 24 kHz, transcrição automática em cache, áudio junto com texto na clonagem completa. Qwen carrega uma vez na execução normal e encerra após a última fala; numa retomada, recarrega e reutiliza os trechos salvos.
- Whisper encerra antes da clonagem; áudio longo e espectrograma usam disco com cálculo em blocos. Prompts completos de vozes persistem no trabalho, com apenas a voz atual em RAM. Montagem e envio ao Telegram também usam blocos.
- WAV, FLAC, MP3, Opus, SRT/VTT; legendas de TTS com tempos por trecho, sujeitas a revisão.
- Dublagem direta do vídeo, com transcrição Turbo automática e ajuste de ritmo para manter os tempos. SRT revisado continua opcional; nesse modo, excesso de duração acima de 10% exige revisão.
- 33 reações e sons offline no editor Detalhado: risada, gemido de dor, choro, surpresa, suspiro, tosse e outras. Gravações próprias por voz, com versões preservadas.
- Nome do áudio opcional; vazio gera nome da voz e número crescente.
- Cliente Android com configuração de rede, upload de áudio/vídeo e downloads: [APK](https://github.com/Sal0-Apps/Sal0-Voz/releases/tag/android-v0.3.1).
- Modelos principais incluídos; downloads opcionais no próprio servidor, com revisão fixa, licença, estimativa de tamanho e hashes; o navegador recebe apenas o status.
- Backup/restauração portável por CLI, inventário de hardware e healthcheck.

## Ainda pendente

- Benchmark dos modelos no AMD A10-9700E/16 GB e avaliação auditiva pt-BR/inglês.
- Validação da clonagem real com referências do proprietário.
- VoxCPM2 como candidato adicional.
- Conversão direta de voz, tradução automática, separação/diarização, emoções específicas por instrução, reações geradas pelo modelo, voice design e treinamento.
- Alinhamento por palavra, editor gráfico de forma de onda, comparação de tomadas e testes extensivos de vídeo longo.
- Homologação no ZimaOS e teste com rede externa bloqueada no servidor real.

O app não troca um clone indisponível por uma voz pronta. O modo Trocar voz permanece identificado como pendente.

## Construir a imagem

```sh
docker compose -f compose.yaml build
docker compose -f compose.yaml up -d
```

Use `compose.yaml` para desenvolvimento/preparação, e `docker-compose.yml` para importar a imagem publicada no ZimaOS. Não monte a pasta do host sobre `/app`.

## Desenvolvimento e testes

Python 3.11/3.12, FFmpeg/FFprobe e eSpeak NG:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
python -m uvicorn app.main:app --host 127.0.0.1 --port 7886
```

Use apenas **um processo Uvicorn**. Os ambientes de IA ficam isolados em `/opt/engines` na imagem. O navegador não carrega os modelos.

[Manual completo](MANUAL.md) · [Guia original](Guia_Sal0_Voz_Local.md) · [Estado dos testes](VALIDACAO.md)
· [Mudanças e comparação com Karaokê](REVISAO_0_3_0.md)


As reações incluídas são gravações de terceiros em CC0 e podem ter timbre diferente da voz clonada. Para manter a identidade, associe sua própria gravação à reação em Minhas vozes. [Origem dos sons](app/assets/reactions/SOURCES.md).

## Criação e limpeza em quatro passos

Em **Criar voz**, escolha a voz, digite ou importe TXT/SRT como texto, escolha o modelo e gere o áudio. Em **Dublar arquivo**, escolha a voz, envie áudio ou vídeo, escolha o modelo e gere o vídeo dublado. O SRT e o ambiente separado ficam nas opções de revisão, recolhidas por padrão. Um áudio gera MP4 com fundo simples; um vídeo mantém a imagem original.

**Minhas vozes** e **Biblioteca** permitem marcar itens, selecionar todos os exibidos e excluir vários com uma confirmação. Resultados incluem arquivos e progresso de trabalhos pausados, cancelados e com falha. Arquivos usados por vozes ou trabalhos retomáveis ficam preservados e o app informa o motivo. Excluir uma voz preserva sua gravação e as vozes congeladas nos trabalhos enviados. Excluir resultados preserva o projeto e os originais.

A versão 0.3.2 corrige o `Not Found` ao carregar o catálogo de reações, que interrompia a restauração da interface. Há teste de inicialização pela API real e teste de navegador com recarga e reconexão. O APK Android 0.3.1 recebe esta interface ao atualizar o servidor.

Os testes de geração dos modelos foram retirados do workflow a pedido do proprietário. A avaliação dos modelos destas revisões será feita no servidor; a publicação mantém os modelos incluídos e verificados durante a construção.
