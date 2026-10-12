# Manual — Sal0 Voz 0.3.2

## Primeira instalação

O Compose do ZimaOS publica a porta **7886**, preservando a porta 7885 do Karaoke. Confirme o disco antes de usar o caminho `/DATA/AppData/sal0-voz`. Os dados, contas, configurações do Telegram e modelos opcionais ficam nesse volume; recriar o container não deve apagá-lo. Os modelos principais ficam na própria imagem, fora do volume.

O entrypoint prepara a pasta e inicia o serviço como usuário não privilegiado (UID 1000). Se restaurar arquivos com outro proprietário, ajuste as permissões do diretório de dados no servidor. Não use container privilegiado.

Crie a senha do proprietário na primeira abertura. A aplicação deve ficar na rede doméstica. HTTPS local permite gravar o microfone de um celular; pelo IP via HTTP, use upload de uma gravação.

A tela inicial usa **Clonar uma voz**, no perfil **Maior fidelidade · Qwen 1.7B**. A voz simples de diagnóstico continua disponível no seletor Tipo de voz para testar instalação e exportação.

`qwen-1.7b`, `qwen-0.6b` e `whisper-large-v3-turbo` vêm na imagem em `/opt/sal0-models/models`, com revisões fixas e hashes verificados durante a construção. A primeira geração usa esses arquivos sem download separado. Os modelos opcionais são gravados em `/data/models`; o navegador recebe somente o status. Uma cópia completa no volume tem preferência; uma cópia incompleta não esconde o modelo da imagem. Em **Ajustes**, cada modelo mostra a disponibilidade, a fila, o progresso e os controles de preparação.

## Usuários e Telegram

O primeiro acesso cria uma conta administradora. Em **Ajustes → Usuários**, o administrador cria ou remove contas comuns e administradoras. Cada conta possui seus projetos, mídias, personagens e configuração de Telegram.

Em **Ajustes → Telegram**, informe o token criado pelo `@BotFather` e o Chat ID do destino. O servidor envia a situação do trabalho e anexa os arquivos gerados quando a tarefa termina. O token fica somente no volume `/data`; ele nunca é enviado ao navegador além da máscara parcial.

## Criar sem configurar o motor

- **Voz simples:** escreva o texto e clique em Gerar voz. Disponível imediatamente, com timbre robótico para testar a instalação.
- **Clonar uma voz:** envie uma gravação, informe o idioma dela, escreva o texto e clique em Gerar voz. O app salva a voz e prepara a transcrição automaticamente. O idioma do texto pode ser diferente do da gravação.
- **Gerar legendas:** envie áudio ou vídeo na própria tela, escolha o idioma e gere.
- O rascunho é salvo automaticamente no servidor e o projeto mais recente é reaberto ao entrar. O resultado aparece na tela Criar e na Biblioteca.
- Qwen 1.7B, Qwen 0.6B e large-v3-turbo já estão incluídos. Downloads interrompidos podem ser retomados; o botão Retomar preparação aparece na tela inicial quando necessário.
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

1. Envie áudio ou vídeo com fala limpa diretamente em Minhas vozes, ou escolha um arquivo da Biblioteca. O app extrai e converte o áudio automaticamente.
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

Tags desconhecidas, emoções, tons e nomes de reações inexistentes causam erro explícito. O aplicativo não as envia como fala. Não há cota de caracteres, mas tempo, memória e disco limitam os projetos. Os blocos são pequenos para o motor; o original é preservado.

O editor salva o rascunho no servidor após uma breve pausa, inclusive antes de clicar em Salvar projeto. Duplicar cria projeto independente. Resultados anteriores permanecem na Biblioteca.

## Legendas

Escolha Gerar legendas, mídia e idioma. O padrão é Faster-Whisper large-v3-turbo, em CPU INT8 com quatro threads. A fila gera SRT e VTT; revise nomes, pontuação e tempos. O pipeline segue [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper). Projetos com outro modelo escolhido explicitamente mantêm essa opção.

O SRT de TTS acompanha os tempos de cada trecho gerado, incluindo pausas inseridas; não é alinhamento por palavra. As quebras editoriais e velocidade de leitura ainda precisam de revisão.

Importe um SRT para editar início, fim, texto e personagem. A API permite baixar o SRT/VTT revisado em `/api/projects/ID/subtitles/srt` ou `vtt`.

## Dublagem

1. Envie o vídeo diretamente em Criar voz → Dublar vídeo. O SRT é opcional.
2. Selecione o vídeo, a voz salva e o idioma da fala original. Sem SRT, o app transcreve o áudio com Faster-Whisper large-v3-turbo e dubla o texto detectado. Não traduz o vídeo. Com SRT, usa o texto/tempos revisados e permite personagem por fala.
3. Para manter música e efeitos, importe uma faixa de ambiente já separada.
4. Gere e ouça o resultado.

Sem ambiente separado, a faixa original de áudio é substituída. Não há separação automática nesta versão. As falas ficam ancoradas aos tempos detectados ou do SRT; não são concatenadas de forma a deslocar falas posteriores. Sobreposições exigem revisão. H.264/yuv420p é copiado sem reencodar. Outros formatos reconhecidos são convertidos automaticamente para MP4 H.264/AAC. Lip sync visual não está incluído.

No modo automático, o app ajusta o ritmo de cada fala para caber na janela sem cortar o texto. Confira a transcrição e a naturalidade. No modo com SRT revisado, se uma fala exceder sua janela em mais de 10%, o trabalho falha com indicação do trecho; edite o texto/tempos e gere outra versão. Não corta palavras. Dentro de 10%, usa ajuste moderado de ritmo. O usuário deve ouvir a naturalidade.

## Fila, reinício e recursos

Uma tarefa pesada por vez, incluindo exportação. Fechar o navegador não encerra a fila. Pausar/cancelar encerra o subprocesso e seus descendentes. Os blocos confirmados são preservados. Retomar confere o hash antes de reaproveitar cada bloco.

Reiniciar o container recupera trabalhos interrompidos. Exportações parciais são refeitas. Erros preservam entradas e referências. O diagnóstico do trabalho mostra o log local, acessível somente ao proprietário.

O Compose permite até **10 GiB e quatro CPUs**, para um servidor de 16 GB. Com a opção Permitir modo econômico do mesmo modelo marcada, o app tenta o modelo escolhido em float32 e depois em bfloat16. O modelo permanece igual em todas as frases; não troca automaticamente Qwen 1.7B por 0.6B. As margens são 9,5 GiB para 1.7B float32, 6,0 GiB para 1.7B econômico, 5,5 GiB para 0.6B float32 e 3,25 GiB para 0.6B econômico, mais reserva de 0,25 GiB antes de iniciar. Bfloat16 pode ser mais lento em CPUs antigas. Todas as opções usam clonagem completa, atenção eager e CPU. Whisper termina antes de carregar Qwen.

Se o processo reportar falta de RAM ou o container registrar OOM, o trabalho volta à fila. Antes da primeira fala confirmada, tenta o modo econômico do mesmo modelo; após confirmar fala, mantém o perfil e aguarda memória para evitar mudar a voz no meio do áudio. Desmarque o modo econômico se preferir aguardar o modelo escolhido em float32. Erros antigos podem ser retomados pelo botão Tentar novamente. O diagnóstico separa memória total do host, livre no host, limite do container e disponível para o app; 10 GB decimais equivalem a cerca de 9,31 GiB. Nenhuma margem garante execução com outros aplicativos consumindo RAM durante o trabalho.

O aviso de flash-attn não exige instalação em CPU. A execução usa atenção PyTorch; NNPACK é desativado por compatibilidade, e pad_token_id é informado explicitamente. Erros reais permanecem no diagnóstico.

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

Leve a imagem e o Compose ao servidor. Use `docker load -i sal0-voz-latest.tar` e inicie: Qwen 1.7B, 0.6B e large-v3-turbo já estão na imagem. Os ícones internos e demais recursos web são locais. O painel do ZimaOS usa a URL de ícone do GitHub; para painel totalmente sem rede, configure seu ícone local no ZimaOS.

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


## Reações e nomes dos áudios

Em Detalhado, escolha uma das 33 reações e clique em Inserir reação. Use Ouvir exemplo para conferir o som. Por exemplo:

```text
Olá! [reacao=risada] Isso doeu. [reacao=gemido]
```

A tag insere áudio não verbal na posição marcada. Ela não é enviada ao TTS. Ritmo, volume, pausas e personagem continuam valendo. As legendas identificam o som, como [risada]. Também é possível gerar apenas reações, sem carregar modelos neurais.

Os exemplos são gravações de terceiros com CC0; não recebem o timbre da voz clonada automaticamente. Em Minhas vozes → Reações com esta voz, escolha uma reação e envie sua gravação em áudio ou vídeo, ou associe um arquivo da Biblioteca. Salve a voz para preservar a versão. O servidor converte o som para mono/24 kHz e usa até 30 segundos. Trabalhos enviados mantêm as gravações escolhidas, mesmo se você editar a voz depois. [Lista e créditos](app/assets/reactions/SOURCES.md).

Preencha Nome do áudio para escolher o nome de download. Vazio usa o nome da voz e um número crescente, como Minha voz 1.wav e Minha voz 2.wav. Os nomes são preservados ao retomar; a numeração continua após reinício. O nome do projeto permanece separado.

## Aplicativo Android

Baixe [Sal0 Voz Android](https://github.com/Sal0-Apps/Sal0-Voz/releases/tag/android-v0.3.1) e configure o endereço local do servidor. Endereço externo e SSID são opcionais. Uploads e downloads usam o servidor; fechar o APK não cancela trabalhos. Consulte [instruções do cliente](android/README.md).

## Geração por frases e memória

O texto é dividido em `.`, `!`, `?`, `;`, `:`, reticências e quebras de linha. A pontuação e as palavras são preservadas; números decimais e títulos comuns não são divididos no meio. Frases longas continuam subdivididas por palavras em blocos de até cerca de 350 caracteres.

Cada frase é gerada e salva em disco antes da próxima. O modelo é carregado uma vez e mantém a mesma voz e precisão em todo o trabalho. Buffers temporários são liberados após cada geração; os WAVs são unidos por leitura de um segundo por vez. Na dublagem, frases da mesma legenda são agrupadas antes do ajuste aos tempos do vídeo.

Dividir o texto reduz memória temporária de inferência, mas não reduz o espaço necessário para manter os pesos do modelo. Se Qwen 1.7B ainda não couber, a fila aguarda RAM. Para escolher 0.6B, altere explicitamente o perfil antes de gerar um novo trabalho.

## Fluxo simplificado e exclusão de vários itens

1. Escolha uma voz salva; para uma nova voz, abra Usar uma nova gravação e envie a referência.
2. Para criar áudio, digite o texto ou importe TXT/SRT. Para dublar, envie áudio/vídeo ou escolha da biblioteca. O áudio original é transcrito automaticamente, sem SRT obrigatório.
3. Escolha o modelo, visível na tela. Ajustes de memória, ritmo e formato ficam recolhidos. Com o limite de 10 GiB, o padrão usa o modo econômico de Qwen 1.7B antes de começar; mantém o modelo durante todo o trabalho.
4. Gere. O nome do arquivo é opcional; fica nas opções finais.

Dublar vídeo preserva a imagem e substitui a faixa de voz. Dublar áudio gera um MP4 com fundo simples. Revisar falas, importar SRT e adicionar ambiente são opções avançadas, recolhidas por padrão. Escolher outro arquivo limpa as falas revisadas do anterior.

Marque as caixas em Minhas vozes ou Biblioteca e clique em Excluir selecionados. Selecionar todos marca apenas os itens carregados; Carregar mais permite ampliar a seleção. O app confirma a lista antes de excluir. Arquivos usados por vozes salvas ou trabalhos retomáveis são preservados, com indicação de como liberar. Um trabalho em execução deve ser cancelado e encerrado antes de excluir seus resultados.

Excluir uma voz mantém o arquivo original e as vozes usadas nos trabalhos já enviados. Excluir resultados remove as exportações e o progresso, preservando o projeto e os originais. Seleções removidas são limpas dos projetos; o texto continua salvo.

O aviso Not Found ao recarregar foi corrigido na 0.3.2. Atualizar a página restaura os projetos e trabalhos gravados em /data. Se uma conexão falhar, use Tentar conectar novamente. Ao atualizar o container, mantenha o mesmo volume de dados.
