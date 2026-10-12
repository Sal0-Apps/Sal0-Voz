# Validação da versão 0.3.1

Revisão de 11/10/2026, para CPU de quatro núcleos/16 GB. O proprietário informou que seu primeiro teste da versão anterior funcionou.

## Verificações locais

- **65 testes passaram localmente e dois foram ignorados**, cobrindo API, segurança, mídia e fila, com Python 3.12, FFmpeg e FFprobe. Os dois testes com eSpeak NG ficam para o CI por ausência do executável local.
- 33 arquivos reais de reações verificados contra SHA-256, mono/24 kHz/PCM16, não vazios e com créditos CC0. Exportação de reações usa FFmpeg real sem chamar TTS.
- Upload de vídeo e arquivos com extensão incomum ou sem extensão, conversão da referência para WAV, preservação do original, arquivos de reação privados e snapshots de versões.
- Numeração de nomes testada com dez requisições concorrentes e reinício do banco.
- Dublagem sem SRT testada com FFmpeg real e motores neurais substitutos: transcrição, texto literal preservado, ajuste de ritmo, MP4 com mesma duração e retomada sem repetir ASR/TTS. Esse teste não avalia qualidade neural.
- Política de memória testa GB/GiB, falta de RAM, perfil travado após checkpoint e recuperação para o mesmo modelo econômico após falha.
- O teste Chromium foi ampliado para uploads em Minhas vozes, reações próprias, editor Detalhado, nomes e dublagem sem SRT. A execução local foi bloqueada pela restrição de sockets deste ambiente e será feita no GitHub Actions.

## Testes da imagem e do APK

A versão 0.3.0 passou no [CI 38173018563](https://github.com/Sal0-Apps/Sal0-Voz/actions/runs/38173018563): suíte, Chromium e clonagem real de 1.7B/0.6B com Turbo, quatro CPUs, 12 GiB e rede bloqueada.

Para 0.3.1, o workflow exige os testes de código/interface antes do build. A imagem inclui e verifica os três modelos. Antes de publicar, exige ASR e clonagem completa com duas falas em quatro CPUs e rede bloqueada: 1.7B/12 GiB float32, 0.6B/12 GiB float32, adaptação a 0.6B bfloat16/4 GiB com instruções AVX2 e 1.7B bfloat16/8 GiB. Esses ensaios novos ainda aguardam execução; definir o teste não significa que ele passou.

O workflow Android compila o APK, executa testes de roteamento e lint, e publica APK instalável e checksum em Release. Não há Android SDK local; o resultado de compilação será verificado no CI. O cliente precisa de teste físico no celular do proprietário.

A precisão da clonagem, naturalidade das reações próprias, transcrição e tempo real dependem da gravação e do hardware. Testes em CI não substituem avaliação auditiva no AMD A10 do proprietário. Dublagem não inclui tradução, separação de música/efeitos ou lip sync visual.
