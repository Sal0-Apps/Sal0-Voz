# Manual — Sal0 Voz 0.3.0

## Primeira instalação

O Compose do ZimaOS publica a porta **7886**, preservando a porta 7885 do Karaoke. Confirme o disco antes de usar o caminho `/DATA/AppData/sal0-voz`. Os dados, contas, configurações do Telegram e modelos opcionais ficam nesse volume; recriar o container não deve apagá-lo. Os modelos principais ficam na própria imagem, fora do volume.

O entrypoint prepara a pasta e inicia o serviço como usuário não privilegiado (UID 1000). Se restaurar arquivos com outro proprietário, ajuste as permissões do diretório de dados no servidor. Não use container privilegiado.

Crie a senha do proprietário na primeira abertura. A aplicação deve ficar na rede doméstica. HTTPS local permite gravar o microfone de um celular; pelo IP via HTTP, use upload de uma gravação.

A tela inicial usa **Clonar uma voz**, no perfil **Maior fidelidade · Qwen 1.7B**. A voz simples de diagnóstico continua disponível no seletor Tipo de voz para testar instalação e exportação.

`qwen-1.7b` e `whisper-large-v3-turbo` vêm na imagem em `/opt/sal0-models/models`, com revisões fixas e hashes verificados durante a construção. A primeira geração usa esses arquivos sem download separado. Os modelos opcionais são gravados em `/data/models`; o navegador recebe somente o status. Uma cópia completa no volume tem preferência; uma cópia incompleta não esconde o modelo da imagem. Em **Ajustes**, cada modelo mostra a disponibilidade, a fila, o progresso e os controles de preparação.

## Usuários e Telegram

O primeiro acesso cria uma conta administradora. Em **Ajustes → Usuários**, o administrador cria ou remove contas comuns e administradoras. Cada conta possui seus projetos, mídias, personagens e configuração de Telegram.

Em **Ajustes → Telegram**, informe o token criado pelo `@BotFather` e o Chat ID do destino. O servidor envia a situação do trabalho e anexa os arquivos gerados quando a tarefa termina. O token fica somente no volume `/data`; ele nunca é enviado ao navegador além da máscara parcial.

## Criar sem configurar o motor

- **Voz simples:** escreva o texto e clique em Gerar voz. Disponível imediatamente, com timbre robótico para testar a instalação.
- **Clonar uma voz:** envie uma gravação, informe o idioma dela, escreva o texto e clique em Gerar voz. O app salva a voz e prepara a transcrição automaticamente. O idioma do texto pode ser diferente do da gravação.
- **Gerar legendas:** envie áudio ou vídeo na própria tela, escolha o idioma e gere.
- O rascunho é salvo automaticamente no servidor e o projeto mais recente é reaberto ao entrar. O resultado aparece na tela Criar e na Biblioteca.
- Qwen 1.7B e large-v3-turbo já estão incluídos. Se escolher o perfil opcional Qwen 0.6B, o servidor o prepara uma vez. Downloads interrompidos podem ser retomados; o botão Retomar preparação aparece na tela inicial quando necessário.
- Uma tarefa enviada antes do modelo ficar pronto permanece na fila. Em caso de falha de rede ou espaço, Ajustes mostra o erro; retome o download e o trabalho.

## Atualizar usando latest

```sh
docker compose pull
docker compose up -d
```

No ZimaOS, use a atualização/recriação do aplicativo mantendo o volume de dados. Não basta reiniciar o mesmo container: ele precisa ser recriado com a imagem nova. `SAL0_AUTO_DOWNLOAD_MODELS=0` continua permitindo desativar explicitamente os downloads automáticos.

## Instalar modelos explicitamente (opcional)

Com o repositório no servidor:

```sh
docker compose -f compose.yaml --profile setup run --rm model-setup list
docker compose -f compose.yaml --profile setup run --rm model-setup plan qwen-0.6b
docker compose -f compose.yaml --profile setup run --rm model-setup install qwen-0.6b --accept-license
docker compose -f compose.yaml --profile setup run --rm model-setup verify qwen-0.6b
```

Se o ZimaOS foi instalado pelo Compose simplificado, sem clonar o código:

```sh
docker run --rm -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 -v /DATA/AppData/sal0-voz:/data ghcr.io/sal0-apps/sal0-voz:latest python -m scripts.models plan qwen-0.6b
docker run --rm -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 -v /DATA/AppData/sal0-voz:/data ghcr.io/sal0-apps/sal0-voz:latest python -m scripts.models install qwen-0.6b --accept-license
```

Troque o identificador por `whisper-medium` ou `whisper-large-v3` para preparar modelos opcionais antigos. Os modelos principais também podem ser copiados ao volume explicitamente. O comando plan consulta a fonte, fixa o commit dos pesos e calcula o tamanho. Confira a licença antes do install. O modelo só é anunciado como instalado após completar todos os arquivos e gravar seu manifesto.

Os ambientes Python e os pesos principais já vêm na imagem. Pesos opcionais são baixados pelo servidor, sem passar pelo navegador. Um modelo instalado não é sobrescrito automaticamente. Trocar uma cópia persistente exige preservar os pesos antigos e atualizar a instalação explicitamente.

Na interface, use Ajustes → Atualizar diagnóstico.

## Personagens e clonagem

1. Importe uma referência de áudio limpa na Biblioteca.
2. Crie um personagem, informe a origem, selecione o áudio; a transcrição é opcional.
3. Em Criar voz, selecione o personagem, idioma e Qwen instalado.
4. Comece com uma frase curta. Ouça e avalie conteúdo, semelhança e naturalidade.

Editar um personagem cria nova versão. Trabalhos já enviados preservam a versão anterior. O Qwen Base clona por referência; nesta versão não há controles de emoção nativos nem treinamento.

A implementação segue a API oficial [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS). A execução real do modelo no seu A10 precisa de benchmark; não foi comprovada por testes de API.

Prefira de 6 a 30 segundos de fala clara, de uma pessoa e sem música. A duração mínima aceita é 3 segundos. Na preparação automática, o app usa os primeiros 30 segundos, converte para mono/24 kHz e transcreve com large-v3-turbo. Se informar a transcrição manual, use um áudio de até 30 segundos e escreva o texto correspondente ao áudio inteiro.

A clonagem usa o áudio **e** a transcrição (`x_vector_only_mode=False`). A preparação fica em cache e não altera a versão salva da voz. Confira o texto em Minhas vozes → Conferir transcrição; se houver erro, edite a voz e informe o texto correto. O Whisper termina antes de carregar Qwen, e Qwen permanece carregado para todos os trechos do mesmo trabalho. Adicionar outro texto preserva a voz selecionada.

## Roteiros e VoiceScript

```text
[idioma=pt-BR]
Olá! [pausa=450ms]
[ritmo=0.95]Esta frase é um pouco mais lenta.[/ritmo]
[volume=-3]Esta frase tem ganho menor.[/volume]
```

`[personagem=ID]` muda o personagem; use o ID do catálogo/API. Ritmo de 0.8 a 1.2 e volume de -24 a +6 dB usam pós-processamento FFmpeg. Use `\[` e `\]` para colchetes literais.

Tags desconhecidas, emoções, tons e reações não suportados causam erro explícito. O aplicativo não as envia como fala. Não há cota de caracteres, mas tempo, memória e disco limitam os projetos. Os blocos são pequenos para o motor; o original é preservado.

O editor salva o rascunho no servidor após uma breve pausa, inclusive antes de clicar em Salvar projeto. Duplicar cria projeto independente. Resultados anteriores permanecem na Biblioteca.

## Legendas

Escolha Gerar legendas, mídia e idioma. O padrão é Faster-Whisper large-v3-turbo, em CPU INT8 com quatro threads. A fila gera SRT e VTT; revise nomes, pontuação e tempos. O pipeline segue [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper). Projetos com outro modelo escolhido explicitamente mantêm essa opção.

O SRT de TTS acompanha os tempos de cada trecho gerado, incluindo pausas inseridas; não é alinhamento por palavra. As quebras editoriais e velocidade de leitura ainda precisam de revisão.

Importe um SRT para editar início, fim, texto e personagem. A API permite baixar o SRT/VTT revisado em `/api/projects/ID/subtitles/srt` ou `vtt`.

## Dublagem

1. Importe vídeo e um SRT revisado.
2. Selecione o vídeo original, atribua o personagem principal e personagens por fala.
3. Para manter música e efeitos, importe uma faixa de ambiente já separada.
4. Gere e ouça o resultado.

Sem ambiente separado, a faixa original de áudio é substituída. Não há separação automática nesta versão. As falas ficam ancoradas aos tempos do SRT; não são concatenadas de forma a deslocar falas posteriores. Sobreposições exigem revisão. O vídeo é copiado sem reencodar; codecs incompatíveis com MP4 resultam em erro explícito. Lip sync visual não está incluído.

Se uma fala exceder sua janela em mais de 10%, o trabalho falha com indicação do trecho; edite o texto/tempos e gere outra versão. Não corta palavras. Dentro de 10%, usa ajuste moderado de ritmo. O usuário deve ouvir a naturalidade.

## Fila, reinício e recursos

Uma tarefa pesada por vez, incluindo exportação. Fechar o navegador não encerra a fila. Pausar/cancelar encerra o subprocesso e seus descendentes. Os blocos confirmados são preservados. Retomar confere o hash antes de reaproveitar cada bloco.

Reiniciar o container recupera trabalhos interrompidos. Exportações parciais são refeitas. Erros preservam entradas e referências. O diagnóstico do trabalho mostra o log local, acessível somente ao proprietário.

O Compose permite até **12 GiB e quatro CPUs**, para um servidor de 16 GB. O perfil 1.7B pede cerca de 9,5 GiB livres para carregar e prioriza fidelidade; o 0.6B pede 5,5 GiB e reduz o custo de CPU. Os dois executam Qwen em float32/eager, sem CUDA. A execução sequencial evita carregar Whisper e Qwen juntos. O executor considera o limite de memória do container, desconta cache de arquivos limpos e pausa com pouca memória ou disco. As margens não substituem a medição real de pico no A10. Feche outras tarefas pesadas antes de gerar.

## Backup e restauração

Pare o app antes de criar/restaurar para obter um conjunto consistente de banco e arquivos. Guarde o ZIP fora do volume de dados:

```sh
docker stop sal0-voz
docker run --rm -v /DATA/AppData/sal0-voz:/data -v /CAMINHO/DOS/BACKUPS:/backup ghcr.io/sal0-apps/sal0-voz:latest python -m scripts.backup create /backup/sal0-voz.zip
docker start sal0-voz
```

O diretório de backup precisa permitir escrita ao UID 1000. O ZIP inclui banco, mídia, projetos, trabalhos e exportações. Modelos não são duplicados; suas revisões e hashes ficam no manifesto. Copie `models/` separadamente para backup offline completo.

Restaure em pasta nova/vazia:

```sh
docker run --rm -v /CAMINHO/DOS/BACKUPS:/backup:ro -v /DATA/AppData/sal0-voz-restaurado:/restore ghcr.io/sal0-apps/sal0-voz:latest python -m scripts.backup restore /backup/sal0-voz.zip --destination /restore
```

Prepare a pasta /restore com permissão de escrita do UID 1000. Confira os arquivos, recoloque os modelos nas revisões registradas e só então mude o volume do Compose. Sessões antigas são invalidadas na restauração; a senha do proprietário é preservada. O importador valida nomes e hashes e rejeita caminhos que escapam da pasta.

## Instalação offline

Em uma máquina conectada, prepare a imagem e os modelos, verifique hashes e exporte:

```sh
docker pull ghcr.io/sal0-apps/sal0-voz:latest
docker save ghcr.io/sal0-apps/sal0-voz:latest -o sal0-voz-latest.tar
```

Leve a imagem e o Compose ao servidor. Use `docker load -i sal0-voz-latest.tar` e inicie: Qwen 1.7B e large-v3-turbo já estão na imagem. Se quiser o perfil opcional 0.6B offline, copie também sua instalação verificada ao volume. Os ícones internos e demais recursos web são locais. O painel do ZimaOS usa a URL de ícone do GitHub; para painel totalmente sem rede, configure seu ícone local no ZimaOS.

As flags offline impedem downloads pelas bibliotecas compatíveis; **não são um firewall**. A telemetria de Hugging Face, Gradio e ONNX Runtime é desativada no motor. O workflow executa o teste de modelos reais com `--network none`; a homologação no servidor deve manter acesso LAN e bloquear saída externa.

## Diagnóstico da máquina alvo

```sh
docker exec sal0-voz python -m scripts.benchmark
```

O relatório fica em `/data/benchmark-hardware.json`. Registre também versão do ZimaOS/Docker, containers concorrentes e disco escolhido. Compare os modelos separadamente em português e inglês, com frases curtas, narração e cenas. Avalie 1/2/4 threads e memória de pico. Não use apenas velocidade para escolher o motor.

## Atualização e rollback

Faça backup, pare o app, atualize a tag `latest` e recrie; para rollback, use uma tag fixa publicada. Preserve /data. Nunca use somente latest como forma de recuperar instalação. Esquema atual: SQLite user_version=1, criado idempotentemente na inicialização. Uma versão futura com migração deve documentar compatibilidade e recuperação.

## Limites desta entrega

Conversão direta, tradução automática, separação/diarização, emoção automática, treinamento, VoxCPM2 e Chatterbox ainda não foram integrados. Qwen/Whisper estão disponíveis como adaptadores reais, mas dependem dos pesos e validação de CPU. Não foi feita comparação auditiva ElevenLabs nem homologação no servidor do usuário. Consulte VALIDACAO.md.

