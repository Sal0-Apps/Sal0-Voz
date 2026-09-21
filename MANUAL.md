# Manual — Sal0 Voz 0.1.0

## Primeira instalação

O Compose do ZimaOS publica a porta **7886**, preservando a porta 7885 do Karaoke. Confirme o disco antes de usar o caminho `/DATA/AppData/sal0-voz`. Todos os dados e modelos ficam nesse volume; recriar o container não deve apagá-lo.

O entrypoint prepara a pasta e inicia o serviço como usuário não privilegiado (UID 1000). Se restaurar arquivos com outro proprietário, ajuste as permissões do diretório de dados no servidor. Não use container privilegiado.

Crie a senha do proprietário na primeira abertura. A aplicação deve ficar na rede doméstica. HTTPS local permite gravar o microfone de um celular; pelo IP via HTTP, use upload de uma gravação.

A primeira versão inclui uma voz simples de diagnóstico. Ela gera fala real e serve para testar instalação e exportação; não é clonagem nem a qualidade final pretendida.

## Instalar modelos explicitamente

Com o repositório no servidor:

```sh
docker compose -f compose.yaml --profile setup run --rm model-setup list
docker compose -f compose.yaml --profile setup run --rm model-setup plan qwen-1.7b
docker compose -f compose.yaml --profile setup run --rm model-setup install qwen-1.7b --accept-license
docker compose -f compose.yaml --profile setup run --rm model-setup verify qwen-1.7b
```

Se o ZimaOS foi instalado pelo Compose simplificado, sem clonar o código:

```sh
docker run --rm -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 -v /DATA/AppData/sal0-voz:/data ghcr.io/sal0-apps/sal0-voz:latest python -m scripts.models plan qwen-1.7b
docker run --rm -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 -v /DATA/AppData/sal0-voz:/data ghcr.io/sal0-apps/sal0-voz:latest python -m scripts.models install qwen-1.7b --accept-license
```

Troque o identificador por `qwen-0.6b`, `whisper-medium` ou `whisper-large-v3`. O comando plan consulta a fonte oficial, fixa o commit dos pesos e calcula o tamanho. Confira a licença antes do install. O modelo só é anunciado como instalado após completar todos os arquivos e gravar seu manifesto.

Os ambientes Python já vêm na imagem. Pesos são baixados separadamente, sem download implícito durante a geração. Um modelo instalado não é sobrescrito automaticamente. Trocar os pesos exige preservar os antigos e atualizar a instalação explicitamente.

Na interface, use Ajustes → Atualizar diagnóstico.

## Personagens e clonagem

1. Importe uma referência de áudio limpa na Biblioteca.
2. Crie um personagem, informe a origem, selecione o áudio e transcreva exatamente o conteúdo.
3. Em Criar voz, selecione o personagem, idioma e Qwen instalado.
4. Comece com uma frase curta. Ouça e avalie conteúdo, semelhança e naturalidade.

Editar um personagem cria nova versão. Trabalhos já enviados preservam a versão anterior. O Qwen Base clona por referência; nesta versão não há controles de emoção nativos nem treinamento.

A implementação segue a API oficial [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS). A execução real do modelo no seu A10 precisa de benchmark; não foi comprovada por testes de API.

## Roteiros e VoiceScript

```text
[idioma=pt-BR]
Olá! [pausa=450ms]
[ritmo=0.95]Esta frase é um pouco mais lenta.[/ritmo]
[volume=-3]Esta frase tem ganho menor.[/volume]
```

`[personagem=ID]` muda o personagem; use o ID do catálogo/API. Ritmo de 0.8 a 1.2 e volume de -24 a +6 dB usam pós-processamento FFmpeg. Use `\[` e `\]` para colchetes literais.

Tags desconhecidas, emoções, tons e reações não suportados causam erro explícito. O aplicativo não as envia como fala. Não há cota de caracteres, mas tempo, memória e disco limitam os projetos. Os blocos são pequenos para o motor; o original é preservado.

O editor salva o rascunho neste navegador. Depois de Salvar projeto, alterações são salvas no servidor após uma breve pausa. Duplicar cria projeto independente. Resultados anteriores permanecem na Biblioteca.

## Legendas

Escolha Gerar legendas, mídia e modelo Whisper instalado. A fila gera SRT e VTT; revise nomes, pontuação e tempos. O pipeline segue [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper).

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

O teto inicial é 10 GB e 2 CPUs. O executor pausa perto do limite cgroup de RAM ou com pouco disco. Isso não garante que uma alocação instantânea não provoque OOM. Valide o consumo real. Não execute geração pesada simultaneamente ao Karaoke no A10.

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

Leve a imagem, os modelos e o Compose ao servidor. Use `docker load -i sal0-voz-latest.tar`, copie os modelos ao volume e inicie. Os ícones internos e demais recursos web são locais. O painel do ZimaOS usa a URL de ícone do GitHub; para painel totalmente sem rede, configure seu ícone local no ZimaOS.

As flags offline impedem downloads pelas bibliotecas compatíveis; **não são um firewall**. A homologação exige repetir os fluxos com saída para internet bloqueada, mantendo LAN.

## Diagnóstico da máquina alvo

```sh
docker exec sal0-voz python -m scripts.benchmark
```

O relatório fica em `/data/benchmark-hardware.json`. Registre também versão do ZimaOS/Docker, containers concorrentes e disco escolhido. Compare os modelos separadamente em português e inglês, com frases curtas, narração e cenas. Avalie 1/2/4 threads e memória de pico. Não use apenas velocidade para escolher o motor.

## Atualização e rollback

Faça backup, pare o app, atualize a tag `latest` e recrie; para rollback, use uma tag fixa publicada. Preserve /data. Nunca use somente latest como forma de recuperar instalação. Esquema atual: SQLite user_version=1, criado idempotentemente na inicialização. Uma versão futura com migração deve documentar compatibilidade e recuperação.

## Limites desta entrega

Conversão direta, tradução automática, separação/diarização, emoção automática, treinamento, VoxCPM2 e Chatterbox ainda não foram integrados. Qwen/Whisper estão disponíveis como adaptadores reais, mas dependem dos pesos e validação de CPU. Não foi feita comparação auditiva ElevenLabs nem homologação no servidor do usuário. Consulte VALIDACAO.md.

