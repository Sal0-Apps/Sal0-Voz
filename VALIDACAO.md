# Validação da versão 0.3.1

Revisão de 12/10/2026, para CPU de quatro núcleos/16 GB. O proprietário informou que seu primeiro teste da versão anterior funcionou.

## Verificações locais

- **69 testes passaram localmente e dois foram ignorados**, cobrindo API, segurança, mídia e fila, com Python 3.12, FFmpeg e FFprobe. Os dois testes com eSpeak NG ficam para o CI por ausência do executável local.
- 33 arquivos reais de reações verificados contra SHA-256, mono/24 kHz/PCM16, não vazios e com créditos CC0. Exportação de reações usa FFmpeg real sem chamar TTS.
- Upload de vídeo e arquivos com extensão incomum ou sem extensão, conversão da referência para WAV, preservação do original, arquivos de reação privados e snapshots de versões.
- Numeração de nomes testada com dez requisições concorrentes e reinício do banco.
- Dublagem sem SRT testada com FFmpeg real e motores neurais substitutos: transcrição, texto literal preservado, ajuste de ritmo, MP4 com mesma duração e retomada sem repetir ASR/TTS. Esse teste não avalia qualidade neural.
- Política de memória testa GB/GiB, falta de RAM, perfil travado após checkpoint e recuperação para o mesmo modelo econômico após falha. A política nunca muda de 1.7B para 0.6B.
- O job de testes do [CI 38197401549](https://github.com/Sal0-Apps/Sal0-Voz/actions/runs/38197401549), no commit `1274407bcbc44e892f834bf821e61535243dbae2`, passou nos **71 testes**, nos dois Compose e no Chromium. Inclui divisão por pontuação, modelo constante, agrupamento e ajuste dos tempos de dublagem, uploads em Minhas vozes, reações próprias, editor Detalhado, nomes e dublagem sem SRT, em computador e celular. A execução local de Chromium foi bloqueada pela restrição de sockets.

## Testes da imagem e do APK

A versão 0.3.0 passou no [CI 38173018563](https://github.com/Sal0-Apps/Sal0-Voz/actions/runs/38173018563): suíte, Chromium e clonagem real de 1.7B/0.6B com Turbo, quatro CPUs, 12 GiB e rede bloqueada.

Para 0.3.1, o [CI 38197401549](https://github.com/Sal0-Apps/Sal0-Voz/actions/runs/38197401549) passou na inicialização da imagem e nos quatro ensaios com modelos reais. Todos usaram **quatro CPUs e rede bloqueada**, Faster-Whisper large-v3-turbo INT8, transcrição automática da referência e clonagem completa com duas falas. Os três modelos foram encontrados na imagem, sem downloads separados.

| Modelo escolhido | Limite do container | Precisão usada | Resultado |
| --- | --- | --- | --- |
| Qwen 1.7B | 12 GiB | float32 | Passou |
| Qwen 0.6B | 12 GiB | float32 | Passou |
| Qwen 0.6B | 4 GiB, instruções AVX2 | bfloat16 | Passou |
| Qwen 1.7B | 8 GiB | bfloat16 | Passou |

Os ensaios econômicos confirmaram o modelo e a precisão usados no resultado; o perfil 1.7B não foi trocado por 0.6B. O teste AVX2/4 GiB levou cerca de dez minutos incluindo ASR, preparação, carregamento e duas falas, contra cerca de dois minutos no ensaio 0.6B/12 GiB float32. Isso não mede a velocidade em tempo real nem constitui benchmark do A10.

O workflow terminou com sucesso e publicou `ghcr.io/sal0-apps/sal0-voz:0.3.1`, `latest` e `sha-1274407bcbc44e892f834bf821e61535243dbae2`. A consulta anônima ao registro confirmou HTTP 200 e o mesmo digest nas três tags: `sha256:ad9f1e031bf80cfabdc54c459942bff23da609e10594602aef9f1c9a1fa9828b`. A imagem contém o código validado no commit acima; este relatório é atualizado em um commit posterior que altera somente documentação.

O [workflow Android 38195580727](https://github.com/Sal0-Apps/Sal0-Voz/actions/runs/38195580727) passou: APK compilado, três testes de roteamento e lint. [APK instalável e checksum](https://github.com/Sal0-Apps/Sal0-Voz/releases/tag/android-v0.3.1) publicados. O APK publicado foi baixado e seu SHA-256 confirmado: `b4d5e9491770abcc7764f8c7ad4482a5db91bbf789bf34c0022fc4ae96874cb8`. O cliente precisa de teste físico no celular do proprietário.

A precisão da clonagem, naturalidade das reações próprias, transcrição e tempo real dependem da gravação e do hardware. Testes em CI não substituem avaliação auditiva no AMD A10 do proprietário. Dublagem não inclui tradução, separação de música/efeitos ou lip sync visual.

# Revisão 0.3.2

A falha `Not Found` foi reproduzida pela API real: a rota genérica de listagem interceptava `/api/reactions`. A revisão usa rotas explícitas e adiciona testes de inicialização, persistência após recarga e reconexão no navegador.

Testes locais novos cobrem exclusão em lote, proteção de referências e trabalhos ativos, isolamento entre usuários, remoção dos arquivos reais, restauração após falha de commit, retomada de exclusão interrompida, dublagem de áudio para MP4 com FFmpeg real e seleção do mesmo Qwen 1.7B econômico sob limite de 10 GiB. O [CI 38206389915](https://github.com/Sal0-Apps/Sal0-Voz/actions/runs/38206389915), no commit `4eec06ff0cb7c6c0ce349fbc12748477a339970b`, passou nos **81 testes**, na validação dos templates de Compose existentes e nos dois testes de navegador: fluxo de criação/exclusão e inicialização pela API real, com recarga e reconexão.

O workflow também passou na construção e inicialização da imagem, sem rede no teste de inicialização, com autenticação HTTP, fila persistente, rotas de carregamento do estúdio e geração diagnóstica por eSpeak NG. **Não executou os modelos Qwen ou Faster-Whisper.** A pedido do proprietário, os testes de geração dos modelos foram removidos do workflow; ele fará essa avaliação no servidor. A seleção econômica sob limite de 10 GiB foi verificada como política de software, sem novo ensaio de clonagem neural nessa memória.

Foram publicadas as tags `ghcr.io/sal0-apps/sal0-voz:0.3.2`, `latest` e `sha-4eec06ff0cb7c6c0ce349fbc12748477a339970b`, com digest `sha256:644f92adee0fd9556e9f75421db868c19d400c2bf0a3b4e4cc6676d78c86f908`. A consulta anônima ao registro confirmou HTTP 200 e o mesmo digest nas três tags. A imagem contém o código do commit acima; esta atualização do relatório altera somente documentação.

O Compose personalizado de 10 GiB/quatro núcleos é entregue separadamente e não foi incluído no repositório. Os templates de instalação que já existiam no repositório permanecem como estavam antes desta revisão.

# Revisão 0.3.3

Redução de RAM com decodificação PCM e espectrogramas longos em disco; FFT em blocos com contexto e normalização global preservados. A comparação numérica usa somente o FeatureExtractor NumPy do Faster-Whisper 1.1.1, com licença MIT em tests/vendor, sem carregar ou executar o modelo. Prompts de clonagem completos persistem por trabalho e apenas a voz atual fica na RAM. Cada áudio bruto tem checkpoint próprio antes de confirmação, e Qwen encerra antes de converter a última fala e exportar. A fila e as páginas consultam metadados limitados em SQLite, e o envio ao Telegram é feito em blocos.

Novos testes com motores substitutos e FFmpeg real verificam retomada automática após falta de memória, perda de confirmação após gravação, conservação dos trechos e do perfil, intervalo crescente, respeito a pausa/cancelamento, recuperação de falhas antigas, SIGKILL sem contador de OOM, encerramento de descendentes quando o pai já saiu, falhas de memória em processo de transcrição, prompts completos/versões/corrupção, paginação antes de desserializar snapshots e multipart por blocos sem envio real. **100 testes passaram na suíte local e dois testes com eSpeak NG foram ignorados por ausência do executável.** As verificações adicionais também passaram, incluindo a regressão que impede um erro de memória antigo no log de esconder a causa de uma nova falha. Qwen e Whisper não foram carregados para geração.

O [CI 38228522862](https://github.com/Sal0-Apps/Sal0-Voz/actions/runs/38228522862), no commit `e2509d4e710d2a91703be8d1b9899ec4505b6359`, passou nos **103 testes**, na validação dos templates de instalação existentes, nos dois testes de navegador e na inicialização da imagem sem rede. O teste da imagem usa somente eSpeak NG, HTTP, fila e arquivos WAV/SRT. Não houve inferência com Qwen ou Faster-Whisper. A qualidade e os picos reais de RAM no hardware do proprietário ficam para a avaliação dele.

Foram publicadas as tags `ghcr.io/sal0-apps/sal0-voz:0.3.3`, `latest` e `sha-e2509d4e710d2a91703be8d1b9899ec4505b6359`. A consulta anônima ao registro confirmou HTTP 200 e digest igual nas três tags: `sha256:914b055b271e8c4522de594c2ca800188f2e740d8aefc95a75e8764bd3864a2c`. A imagem contém o código do commit acima; a atualização deste relatório modifica somente documentação. O Compose personalizado permanece fora do GitHub, e os templates existentes não foram alterados nesta revisão.

# Revisão 0.3.4

Integração opcional do Chatterbox Multilingual V3 especializado em português brasileiro. As revisões das duas fontes, nomes dos arquivos e metadados dos checkpoints foram conferidos sem executar os modelos. O carregador usa T3 pt-BR, decoder V3 e encoder de voz em CPU float32; preserva os buffers determinísticos de mel/janela que o arquivo safetensors do decoder omite, mantendo verificação estrita dos pesos. O download seleciona somente os arquivos necessários, sem os checkpoints antigos ou as duas cópias do mesmo decoder.

Os testes de integração usam motores substitutos. Verificam download de duas fontes fixadas e hashes, indisponibilidade de downloads incompletos, persistência da expressividade no trabalho, restrição de saída a pt-BR, ausência de Whisper na preparação dessa referência, necessidade de ASR na dublagem, despacho em processo único e reaproveitamento dos trechos concluídos. O cache de referência em disco é restaurado após recarregar o motor. A política mantém Chatterbox float32 sob limite de 10 GiB e aguarda RAM sem trocar de modelo ou precisão.

**111 testes passaram na suíte local e dois com eSpeak NG foram ignorados por ausência do executável.** Após os ajustes do carregador, tokenizer e plano de download, os 21 testes direcionados também passaram, incluindo uma nova regressão de retomada da preparação. Os dois testes Chromium passaram: seleção/download/expressividade, preservação do modelo ao escolher uma voz salva, fluxos de criação e dublagem, exclusões em lote, telas de computador/celular, API real, recarga e reconexão. Nenhum modelo neural foi carregado ou executado. A reserva de 6,5 GiB é uma política de preparação; qualidade, tempo e picos reais de RAM ficam para o teste do proprietário. O Compose personalizado e os templates existentes não foram modificados nesta revisão.

O [CI 38248670975](https://github.com/Sal0-Apps/Sal0-Voz/actions/runs/38248670975), no commit `deb90bfa99d5e6a191286163f67fbc9fbeaf2c9b`, passou nos **114 testes**, nos dois testes Chromium, na construção e na inicialização da imagem sem rede. O ambiente CPU do Chatterbox e a revisão fixa do código foram instalados na imagem; seus pesos continuam como download opcional. O teste da imagem usa somente eSpeak NG, HTTP, fila e arquivos WAV/SRT. Não houve geração com Chatterbox, Qwen ou Faster-Whisper.

Foram publicadas as tags `ghcr.io/sal0-apps/sal0-voz:0.3.4`, `latest` e `sha-deb90bfa99d5e6a191286163f67fbc9fbeaf2c9b`. A consulta anônima confirmou HTTP 200 e digest igual nas três tags: `sha256:6a928b2d28c45a96b889d7bdc280a89461c41da9964bbad340f0d863096d98d3`. A imagem contém o código do commit acima; a atualização deste relatório modifica somente documentação.

# Revisão 0.3.5

A imagem oficial deixa de incluir os pesos. A preparação ocorre pelo gerenciador do aplicativo em segundo plano, após iniciar, e grava os modelos em `/data/models`. Qwen 1.7B e Faster-Whisper large-v3-turbo são os padrões automáticos; Qwen 0.6B e Chatterbox continuam disponíveis sob escolha. Modelos já completos no volume são reutilizados. Downloads interrompidos preservam o plano e os arquivos parciais. Modelos que estavam apenas na imagem antiga precisam ser preparados uma vez no volume durante essa transição.

O rótulo de versão foi movido para depois das dependências, evitando que uma mudança de versão invalide a construção dos ambientes de CPU. As dependências continuam instaladas na imagem e a inferência permanece local. A consulta anônima ao manifesto da versão 0.3.4 identificou **8.651.487.812 bytes** de camadas comprimidas, dos quais **7.155.650.618 bytes** correspondiam à camada de preparação dos pesos. A remoção dessa etapa será conferida na imagem publicada.

**114 testes locais passaram e dois de eSpeak NG foram ignorados por ausência do executável.** As regressões adicionais verificam HTTP e autenticação enquanto um download permanece pendente e a reutilização de arquivos completos após recriar o gerenciador. Os dois testes Chromium passaram, incluindo API real, recarga, reconexão, fila, criação/dublagem e gestão de arquivos. Também passaram sintaxe JavaScript, YAML do workflow e verificação do diff. Nenhum modelo neural foi carregado ou executado. O smoke da imagem agora exige que um volume vazio inicie sem modelos disponíveis e usa somente a voz de diagnóstico. O Compose personalizado e os templates existentes permanecem sem alterações.

A conferência de tarefas antigas reproduziu uma falha com um registro de download concluído, mas sem os arquivos que antes estavam na imagem. A fila agora solicita a preparação desses pesos em vez de falhar imediatamente. Se os arquivos existem e falta somente o ambiente de execução, continua pedindo a atualização da imagem, sem baixar os pesos novamente. Essas duas situações foram verificadas com arquivos substitutos e sem carregar modelos.
