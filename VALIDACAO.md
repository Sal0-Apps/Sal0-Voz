# Validação da versão 0.3.0

Registro de revisão: **11/10/2026**. O alvo é CPU com quatro núcleos e 16 GB de RAM. Os resultados locais não são um benchmark do servidor do proprietário.

## Verificações do código atual

- Python 3.12: **56 testes passaram, dois foram ignorados** por ausência do executável eSpeak NG neste ambiente. O CI instala eSpeak NG e executa esses dois testes de geração/exportação real. A suíte cobre autenticação, isolamento entre usuários, uploads, caminhos, backup, versões de vozes/projetos, snapshots da fila, VoiceScript, SRT/VTT e checkpoints.
- As regressões novas verificam os modelos incluídos com volume vazio, fallback após cópia incompleta, Turbo como padrão, manutenção de escolhas explícitas antigas, recuperação da fila, transcrição em cache e uma sessão Qwen para vários trechos.
- O FFmpeg real decodificou e reamostrou uma gravação de teste. O teste do adaptador verifica CPU INT8, quatro threads, áudio decodificado e conversão dos tempos em legendas. Essa verificação usa um modelo substituto e não mede qualidade de transcrição.
- A proteção de memória desconta páginas limpas de arquivos mapeados, mantendo memória compartilhada e páginas sujas na conta.
- O teste Chromium `tests/browser_clone_flow.cjs` passou usando a interface real e respostas de API simuladas: padrão Qwen 1.7B/Turbo, gravação e texto com idiomas independentes, envio, preservação do texto e seleção durante polling, reutilização da voz, preparação opcional e navegação em 1366/390 px sem overflow. Ele não valida inferência neural.
- A sintaxe JavaScript e os arquivos YAML são verificados localmente. A validação semântica dos dois Compose e a construção Docker ficam para o CI, pois Docker não está disponível neste ambiente.

## Ensaios reais anteriores durante esta revisão

O large-v3-turbo foi carregado em CPU INT8 com quatro threads e transcreveu uma referência sintética em inglês de 8,12 segundos em aproximadamente **8,43 segundos**. A transcrição teve uma diferença de palavra; isso não demonstra precisão perfeita nem desempenho com voz humana no A10.

Os arquivos reais dos dois modelos padrão e do perfil opcional 0.6B foram baixados e conferidos contra os hashes das revisões fixas. O teste completo de Qwen 0.6B com transcrição automática Turbo não teve sua conclusão observada localmente. Um ensaio anterior de 0.6B com Whisper medium concluiu, mas não valida a combinação atual com Turbo. A geração real de Qwen 1.7B ainda não foi medida neste ambiente.

## Condições para publicar a imagem

O workflow `.github/workflows/docker.yml` executa a suíte, o teste Chromium e `docker compose config -q`. Depois constrói os ambientes de IA em CPU e inclui Qwen 1.7B/Turbo com hashes verificados.

Antes do push das tags, testa healthcheck, geração de diagnóstico e importação dos motores. Executa `scripts.smoke_models` com o perfil padrão 1.7B, **quatro CPUs, limite de 12 GiB e `--network none`**. Depois prepara o perfil 0.6B em volume separado e repete o ensaio nas mesmas condições. Cada ensaio exige os dois modelos padrão disponíveis na imagem, ASR real, referência transcrita automaticamente, clonagem completa com duas falas e um WAV válido. Uma falha impede a publicação de `0.3.0`, `latest` e da tag do SHA. A CPU do CI ainda difere da CPU do proprietário.

Telemetria de Hugging Face, Gradio e ONNX Runtime é desativada. Flags de biblioteca não substituem o bloqueio de rede aplicado no ensaio Docker. O estado e os logs da execução ficam em [GitHub Actions](https://github.com/Sal0-Apps/Sal0-Voz/actions); definir o teste não significa que ele já passou.

## Pendente no servidor real

- Importação/atualização no ZimaOS, boot e volume existente.
- Tempo e RAM de pico de 1.7B e 0.6B, com quatro núcleos e 16 GB, incluindo compatibilidade das instruções da CPU.
- Clonagem com gravações do proprietário em português/inglês: conteúdo, semelhança e naturalidade.
- Transcrição de fala humana, nomes e sotaques; revisão do texto automático.
- Fluxos com internet bloqueada e acesso LAN mantido.
- Áudio/vídeo longos, sincronização e comparação auditiva de qualidade.

Testes de API e interface não comprovam fidelidade neural. O aplicativo mantém a avaliação do hardware alvo como pendente.
