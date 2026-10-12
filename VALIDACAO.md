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

Testes locais novos cobrem exclusão em lote, proteção de referências e trabalhos ativos, isolamento entre usuários, remoção dos arquivos reais, restauração após falha de commit, retomada de exclusão interrompida, dublagem de áudio para MP4 com FFmpeg real e seleção do mesmo Qwen 1.7B econômico sob limite de 10 GiB. A imagem aguarda validação do CI e publicação.
