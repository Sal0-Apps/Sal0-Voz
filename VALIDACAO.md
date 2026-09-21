# Validação da versão 0.1.0

## Automatizada

A suíte verifica autenticação, CSRF, uploads e caminhos, versões de personagens/projetos, snapshots da fila, modelos ausentes, VoiceScript, preservação de roteiro com mais de 100 mil caracteres, SRT/VTT, restauração e proteção contra caminhos maliciosos em ZIP.

O teste de integração Linux gera frases reais em português e inglês com eSpeak NG, exporta com FFmpeg, reutiliza checkpoints e regenera um bloco corrompido. A integração de diagnóstico não valida qualidade neural.

O workflow valida os dois arquivos Compose, executa a suíte, constrói a imagem CPU, testa healthcheck e publica no GHCR somente se as etapas anteriores passarem.

## Pendente no servidor real

- Importação pelo ZimaOS e reinício após boot.
- Qwen 1.7B/0.6B com pesos reais e referências do proprietário.
- Whisper medium/large-v3 com áudio real e avaliação da transcrição.
- Medição de RAM/RTF no AMD A10-9700E e instruções de CPU.
- Duas horas de áudio, vídeo longo e revisão de sincronização.
- Ensaio completo com internet bloqueada.
- Comparação auditiva com ElevenLabs.

Nenhum benchmark de qualidade ou de hardware é inferido a partir de testes unitários.


## Execução local registrada

Windows/Python 3.12: 28 testes passaram; um teste de áudio Linux fica para o CI. Navegação Chromium em 1440 px e 390 px: sem erros JavaScript e sem overflow horizontal em todas as telas. Backup/restauração passou após correção de fechamento das conexões SQLite.
