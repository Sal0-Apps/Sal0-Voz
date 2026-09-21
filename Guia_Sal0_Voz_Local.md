# Guia de implementação do Sal0 Voz

Documento de produto e engenharia para um estúdio pessoal de voz, personagens, legendas e dublagem totalmente local.

**Versão 1.2 · 21 de setembro de 2026**  
**Máquina de destino:** AMD PRO A10-9700E, 16 GB de RAM e GPU integrada.  
**Plataforma obrigatória:** Docker no ZimaOS, como o Sal0-Karaoke.  
**Idiomas prioritários:** português brasileiro e inglês. **Uso:** pessoal.  
**Prioridade principal:** maior qualidade possível; tempo de processamento não é prioridade.  
**Referência de qualidade desejada:** resultados no nível do ElevenLabs, mantendo geração e processamento totalmente locais.  
**Nome oficial do aplicativo:** Sal0 Voz.

## 1 Direção do projeto

Construir um aplicativo local independente, inspirado na experiência do Sal0-Karaoke, que organize personagens e permita gerar fala a partir de texto, transformar uma gravação na voz de um personagem, criar legendas e substituir diálogos de vídeos. A interface deve ser simples no uso cotidiano e oferecer edição detalhada quando necessário.

**Meta de qualidade ElevenLabs:** buscar resultados perceptualmente comparáveis à referência escolhida do ElevenLabs em naturalidade, semelhança da voz clonada, pronúncia, expressividade, reações e consistência dos personagens, em português brasileiro e inglês. Na dublagem, incluir preservação da atuação, sincronização e qualidade da mixagem. Essa meta orienta a seleção de modelos, a curadoria de referências e o refinamento das tomadas; velocidade não deve justificar reduzir a qualidade final.

ElevenLabs é a referência de resultado, não uma dependência do aplicativo. O produto deve funcionar sem sua API, assinatura ou inferência remota. A equivalência precisa ser demonstrada por comparação auditiva; não é uma capacidade já comprovada dos modelos candidatos no A10. Se o melhor resultado local ainda ficar abaixo da referência, registrar a diferença e manter a meta de qualidade pendente.

**A primeira decisão é desenvolver para CPU.** Na máquina informada, o caminho é buscar os melhores resultados que caibam na memória, com processamento sequencial, lotes longos e revisão humana. Não há meta de tempo real nem descarte de um modelo apenas por ser lento. Mais tempo permite testar tomadas, alinhamento e modelos maiores, mas não resolve falta de RAM, instruções de CPU incompatíveis ou ausência de uma implementação CPU. Cada recurso terá uma classificação de viabilidade baseada em testes locais.

O produto deve preservar o objetivo completo e separar três níveis: qualidade máxima validada na máquina atual, prévia econômica opcional e recursos que exigem mais memória ou hardware compatível. Não apresentar uma voz pronta como se fosse uma voz clonada. Uma versão só poderá ser chamada de completa quando texto para fala, clonagem, conversão de voz e dublagem tiverem passado pelos testes definidos neste guia.

### O que significa totalmente local

Textos, amostras, personagens, reconhecimento, tradução, geração e exportação ficam na máquina de casa. Downloads de programas e modelos acontecem na preparação, de forma explícita; depois, o app deve funcionar com a conexão externa bloqueada. Também deve existir instalação por pacote offline levado em SSD ou pendrive.

O computador desta conversa não substitui a medição na máquina de casa. A plataforma é ZimaOS com Docker. A versão do sistema, arquitetura de 64 bits, espaço disponível, tipo de disco e memória realmente utilizável devem ser registrados na etapa inicial. A GPU integrada compartilha recursos do sistema; ela não equivale a uma placa dedicada com 16 GB de VRAM. Não depender de CUDA, nem presumir suporte dessa APU ao ROCm atual. A documentação de compatibilidade da AMD será a referência na instalação. [F01]

### Promessas que precisam ser convertidas em requisitos verificáveis

| Desejo | Compromisso implementável | Limite real |
| --- | --- | --- |
| Sem limite de texto ou áudio | Sem cota de caracteres, minutos ou quantidade de personagens; dividir e retomar projetos | Disco, tempo, RAM, formatos e limites de contexto dos modelos continuam existindo |
| Aprender uma voz com precisão | Referências selecionadas, versões do personagem, avaliação e treinamento opcional | Clonagem por referência não é treinamento; semelhança perfeita não é garantida |
| Reconhecer emoção e tonalidade | Sugerir interpretação por trecho, medir prosódia e permitir correção | A emoção é uma inferência incerta, dependente de idioma, ruído e contexto |
| Personagens em várias línguas | Mesmo personagem associado a referências e motores compatíveis | Português e inglês podem ter qualidade e sotaque diferentes |
| Dublar mantendo a atuação | Conversão direta ou recriação guiada pela atuação original | Separação de vozes sobrepostas e preservação de fundo podem falhar |
| Melhores modelos locais | Comparação auditiva e de desempenho na máquina real | Popularidade ou resultado em GPU de laboratório não define o melhor para o A10 |

## 2 Equivalências com o Sal0 Karaoke

A referência foi examinada no commit `f87b4713e0f0f1227e0c1dddf8567137b7804305`. O README e o manual desse estado identificam a distribuição 9.8.0. A análise de aparência foi feita no HTML e CSS; não corresponde a um teste interativo da aplicação em execução. [R01–R04]

| Elemento da referência | Equivalente proposto |
| --- | --- |
| Criar com modos Rápido e Detalhado | Criar voz com configurações essenciais ou direção de fala por trecho |
| Gerar SRT | Legendar áudio original, áudio gerado ou vídeo, com tradução opcional |
| Biblioteca de originais, fundos e resultados | Biblioteca de referências, personagens, projetos, áudios, vídeos e legendas |
| Letra guia e revisão | Roteiro guia, transcrição revisável, pronúncia e direção de interpretação |
| Perfis de ajustes | Presets de narrador, diálogo, audiobook, atuação e dublagem |
| Progresso por etapa e fila persistente | Fila com checkpoints por segmento, cancelamento e retomada |
| Separação de voz e instrumental | Separação de diálogo e ambiente quando necessária, com audição das trilhas |
| Tema claro e escuro e interface responsiva | Mesma linguagem visual e operação no navegador do computador ou celular na rede local |
| Contas locais e biblioteca isolada | Um proprietário no início; contas locais opcionais em uma etapa posterior |
| Telegram e importação por URL | Extensões opcionais futuras; fora do funcionamento offline essencial |

**Reutilização recomendada:** identidade visual, componentes de formulário, biblioteca, conceitos de fila e funções de mídia que passarem por revisão. Extrair funções pequenas e verificáveis. O novo fluxo de personagens, roteiro e linha do tempo justifica módulos próprios.

**Mudanças deliberadas:** não herdar o limite de 25 trabalhos ativos por perfil descrito no manual; usar paginação e controle de recursos. Um projeto aguardando revisão deve liberar o executor para outro trabalho. Não acrescentar automaticamente a abertura silenciosa de três segundos do karaokê a um vídeo dublado, pois isso mudaria sua linha do tempo. Revalidar dependências em vez de copiar o arquivo de requisitos antigo, que usa PyTorch para CPU e versões próprias daquele projeto. A tradução deve apontar para serviço na própria máquina, não apenas para qualquer endereço configurável. [R02–R04]

## 3 Aparência e organização das telas

Preservar os tokens encontrados no projeto: fundo escuro `#050B12`, destaque `#49AEEF`, texto `#EEF8FF`, texto secundário `#91ADC0`, cartões azul-escuros e bordas discretas. No tema claro: fundo `#EDF7FD`, cartões brancos e destaque `#168BD2`. Cantos de 18, 12 e 8 pixels. O CSS utiliza Inter no corpo e Outfit nos títulos; distribuir as fontes localmente com seus avisos ou utilizar alternativas do sistema. Não solicitar Google Fonts durante a operação offline. [R03]

### Navegação principal

- **Criar:** Texto para voz, Trocar voz, Dublar vídeo e Gerar SRT. Cada modo oferece Rápido e Detalhado onde isso for útil.
- **Personagens:** criar, ouvir, testar, comparar versões, escolher referências e organizar interpretações.
- **Projetos:** roteiro, cenas, elenco, linha do tempo, revisão e versões dos resultados.
- **Biblioteca:** originais, referências, resultados e importação de arquivos locais.
- **Ajustes:** modelos, desempenho, armazenamento, instalação offline e diagnóstico.

Fila acessível em todas as telas. No desktop, formulários em cartões; no editor detalhado, área central para o roteiro e painel lateral para personagem e interpretação. Em telas estreitas, os painéis viram seções empilhadas. Não exigir rolagem horizontal da página para operar.

### Fluxo rápido de texto para voz

Selecionar personagem → colar texto → escolher português brasileiro ou inglês → ouvir prévia → gerar na melhor qualidade aprovada → revisar ou baixar. Exibir o motor e o modo de qualidade em linguagem simples. Para uma prévia feita com voz leve substituta, mostrar “Prévia de ritmo com outra voz”; nunca insinuar que representa a clonagem final.

### Editor detalhado

Roteiro segmentado por falante, com seleção de personagem, idioma, intenção, pausa, ritmo e pronúncia por trecho. A linha do tempo mostra forma de onda, falas e espaço disponível. Oferecer “Gerar este trecho”, “Comparar versões”, “Manter esta versão” e “Restaurar anterior”. Manter salvamento automático e desfazer/refazer de texto, tempos e atribuições.

### Estados que precisam ter desenho próprio

Primeiro uso; modelo não instalado; biblioteca vazia; amostra ruim; idioma incompatível; recurso sem suporte; falta de RAM; disco insuficiente; trabalho pausado; revisão pendente; exportação incompleta e resultado concluído. Nunca deixar apenas uma tela carregando sem informar a etapa. Toda ação deve ser operável pelo teclado; progresso e erros não podem depender só de cores.

## 4 Escopo funcional e prioridades

**P0** significa necessário para um primeiro produto útil; **P1**, necessário para atender o objetivo completo; **P2**, expansão. A classificação não representa garantia de desempenho no A10.

| ID | Requisito | Prioridade | Evidência de conclusão |
| --- | --- | --- | --- |
| RF01 | Texto para fala em pt-BR e inglês | P0 | Geração e exportação offline nos dois idiomas |
| RF02 | Projetos longos por blocos sem truncamento silencioso | P0 | Manifesto cobre todo o texto e retoma após reinício |
| RF03 | Personagens persistentes e versionados | P0 | Reabrir projeto preserva referências e versão escolhida |
| RF04 | Clonagem por amostra | P0 sujeito ao teste de viabilidade | Voz sintetizada avaliada contra referência; sem substituição oculta |
| RF05 | Editor de pausas, ritmo, emoção e reações | P0 básico e P1 expressivo | Suporte real identificado por motor e prévia por trecho |
| RF06 | SRT de áudio ou vídeo e do áudio gerado | P0 | Legendas correspondem ao arquivo final |
| RF07 | Conversão direta de uma voz para outra | P1 | Preserva conteúdo e atuação em amostras aprovadas |
| RF08 | Dublagem com elenco e ambiente | P1 | Exporta vídeo completo sem deriva acumulada |
| RF09 | Tradução local inglês e português | P1 | Texto revisável e dublagem alinhada à tradução aprovada |
| RF10 | Sugestão automática de emoção e prosódia | P1 | Sugestão corrigível e resultados de avaliação por idioma |
| RF11 | Aperfeiçoamento do personagem com novos exemplos | P1 | Curadoria e comparação entre versões sem regressão |
| RF12 | Treinamento específico e criação por descrição | P2 | Só habilitar com receita, licença e recursos validados |
| RF13 | Backup e restauração portáveis | P0 | Recupera projeto e personagem em instalação limpa |
| RF14 | Gravação pelo microfone | P1 | Seleção de entrada, medidor de nível e escuta da gravação |
| RF15 | Conversão de voz ao vivo e sincronização labial visual | P2 | Metas próprias; não fazem parte da promessa inicial |
| RF16 | Qualidade final no nível do ElevenLabs | Meta transversal | Comparação auditiva documentada por idioma e recurso, conforme capítulo 7 |

Importar WAV, FLAC, MP3, M4A, OGG e formatos de vídeo aceitos pelo FFmpeg. Importar roteiros TXT e SRT no início; outros documentos podem ser acrescentados depois. Exportar WAV/FLAC para arquivos de qualidade, MP3/Opus para compartilhamento, SRT/VTT, vídeo MP4/MKV e pacote de projeto com metadados. Sempre validar codecs, não apenas extensões.

## 5 Configuração realista para a máquina de casa

### Perfil inicial A10

- Processamento exclusivo pela CPU; uma tarefa pesada por vez, lote de tamanho 1.
- Instalação obrigatória por Docker Compose no ZimaOS, com imagem Linux `amd64` para CPU e ambientes isolados por motor dentro do container. Usar o Docker do servidor, sem instalar bibliotecas de IA diretamente no host.
- Interface no navegador e serviço gerenciado pelo ZimaOS; iniciar, parar e atualizar pela instalação Docker. O navegador pode estar em outro computador da rede doméstica.
- Síntese final com o motor de maior qualidade aprovado para o idioma e personagem. Kokoro ou Piper ficam como prévia ou alternativa opcional, sem substituir a clonagem final.
- Transcrição final comparando Faster-Whisper `medium` e `large-v3` em CPU INT8 quando suportado e dentro da memória. `small`, `base` e `tiny` ficam como rascunhos. Comparar qualidade real: tamanho maior não garante melhor resultado em toda mídia.
- Comparar primeiro VoxCPM2, Qwen3-TTS 1.7B Base e Chatterbox Multilingual V3, cada um isoladamente. Incluir Qwen 0.6B Base como alternativa de memória. Nenhum é considerado aprovado antes do ensaio em CPU.
- Desligar reconhecimento de emoção, separação e tradução quando não necessários. Carregar modelos por etapa e descarregá-los após uso.

**Orçamento de memória proposto, não medição:** reservar aproximadamente 4–6 GB para ZimaOS, serviços ativos e memória compartilhada da GPU. Iniciar com teto de aproximadamente 10 GB para o container completo e ajustar conforme RAM livre real. Não executar karaokê e geração de voz pesada simultaneamente; disponibilizar pausa de tarefas concorrentes. Pausar antes de esgotar a memória. Se o sistema consumir mais, reduzir esse teto; se houver margem comprovada, avaliar aumentá-lo. Swap em SSD pode ser um recurso opcional, se suportado e configurado no ZimaOS, mas não conta como RAM equivalente e pode tornar o processo impraticável. A soma dos modelos, buffers e processos não pode ser ignorada.

Testar 1, 2 e 4 threads de processamento e limitar as bibliotecas para não criarem vários conjuntos concorrentes. Mais threads podem reduzir a responsividade sem melhorar a velocidade. Usar prioridade de segundo plano e mostrar consumo, espaço restante e previsão baseada em trechos já concluídos.

**Armazenamento:** reservar inicialmente 40–80 GB para imagens Docker, conjunto de modelos de qualidade e ambientes, mais espaço para os projetos. É uma estimativa de planejamento; o instalador deve calcular os downloads reais antes de executá-los. Áudio estéreo PCM 48 kHz/24 bits ocupa cerca de 1,04 GB por hora; originais, trilhas separadas e versões multiplicam isso. Oferecer FLAC e limpeza seletiva de cache. Não escolher todos os modelos na primeira instalação.

### O que esperar de cada classe de recurso

| Recurso | Situação esperada no A10 | Decisão de produto |
| --- | --- | --- |
| Biblioteca, roteiro, fila e SRT manual | Adequado | Parte central desde o início |
| TTS com vozes prontas leves | Prévia opcional | Não define o motor do áudio final |
| ASR de arquivos | Plausível, potencialmente demorado | Melhor modelo que caiba na RAM e revisão |
| Clonagem expressiva | Dependente da memória e da execução em CPU | Avaliar qualidade de modelos maiores sem limite curto de espera |
| Conversão de voz e separação | Podem ser muito demoradas | Trechos, lotes noturnos e cancelamento |
| Dublagem completa de vídeos longos | Soma de várias etapas caras | Só avançar após medir cada componente |
| Ajuste fino de modelos grandes | Não recomendado como requisito nessa máquina | Curadoria de referências primeiro |
| Conversão de voz em tempo real | Não prometer | Tratar como expansão futura |

O tempo é informativo, sem peso na escolha de qualidade. Deve ser expresso por **RTF**, tempo de processamento dividido pela duração de áudio. RTF 10 significa que 1 minuto de áudio leva aproximadamente 10 minutos de processamento naquela etapa. Em um vídeo de uma hora, isso seria aproximadamente 10 horas apenas nessa etapa. Este é um exemplo matemático, não um desempenho medido do A10. Somar extração, ASR, separação, geração e exportação na previsão total.

## 6 Modelos e componentes candidatos

Esta seleção usa documentação oficial consultada na data do guia. “Candidato” significa que existe justificativa para testar, não que ele foi executado neste hardware. Instalar versões fixadas; reavaliar a seleção no início do desenvolvimento.

### Voz cotidiana e clonagem

| Modelo | Papel | Português e inglês | Situação no projeto |
| --- | --- | --- | --- |
| Kokoro 82M | TTS leve com vozes prontas | Inclui pt-BR e inglês | Prévia ou narração opcional; não faz clonagem arbitrária por amostra [F02] |
| Piper | TTS local leve | Depende das vozes instaladas | Alternativa econômica; conferir licença de cada voz; não confundir com clonagem imediata [F03] |
| Chatterbox Multilingual V3 | Clonagem multilíngue de 0,5B | Multilíngue e pacote específico pt-BR | Comparador principal de qualidade; testar pacote pt-BR e geral em CPU [F04–F05] |
| Qwen3-TTS 0.6B Base | Clonagem por referência | Português e inglês entre os idiomas suportados | Alternativa se a versão maior não couber ou se vencer na audição [F06–F07] |
| VoxCPM2 | Clonagem controlável e criação de voz | Português e inglês entre 30 idiomas | Candidato prioritário por unir clone e direção; testar CPU e rota C++/GGUF documentadas [F08] |
| Qwen3-TTS 1.7B | Clonagem ou criação, conforme variante | Português e inglês | Candidato prioritário em CPU; Base, CustomVoice e VoiceDesign têm funções diferentes [F06] |
| Fish Audio S2 Pro | Expressão por tags e múltiplos falantes | Inclui português e inglês | Candidato futuro, especialmente para direção de fala; documentação recomenda 24 GB de GPU [F09–F10] |
| OmniVoice | Clonagem e ampla cobertura linguística | Verificar a variante de idioma no adaptador | Comparação posterior; diversidade de idiomas não é prioridade sobre qualidade pt-BR/inglês [F11] |

**Seleção inicial proposta:** comparar VoxCPM2, Qwen 1.7B Base e Chatterbox V3 para qualidade final; Faster-Whisper medium/large-v3 como candidatos de transcrição; FFmpeg para mídia. Escolher o melhor motor por personagem e idioma, mantendo somente um carregado de cada vez. Qwen 0.6B, Kokoro e Piper são alternativas, não o padrão automático por serem menores.

**Memória antes de velocidade:** VoxCPM2 documenta execução CPU e uma rota C++ com BaseLM F16 ou Q8_0 mais um componente acústico. Comparar a implementação de referência e a otimizada com os mesmos trechos; quantização pode alterar o resultado. CPU FP16/BF16 não deve ser presumida eficiente ou compatível nesse A10; testar o tipo de dado e o runtime. Qwen 1.7B em FP32 exige vários gigabytes só para pesos, além de tokenizer, codec, ativações e buffers. Reduzir lote e contexto ajuda, mas não elimina a memória fixa do modelo. [F06, F08]

**Fish S2 Pro:** manter como candidato avançado, sem excluí-lo por velocidade. Há imagem CPU documentada, mas isso não comprova que a carga completa cabe em 16 GB. A recomendação publicada de 24 GB refere-se à GPU e não é uma medida de RAM em CPU. Testar apenas após calcular memória e confirmar runtime ou quantização compatível; não torná-lo dependência obrigatória do A10. [F09–F10]

**Controles diferentes exigem tratamento diferente.** No Qwen, a variante Base oferece clonagem; o controle de instruções e a criação por descrição pertencem às variantes documentadas para isso. Não presumir que um parâmetro de emoção funciona na voz clonada só porque existe em outro modelo da família. Chatterbox Turbo privilegia inglês e reações específicas; não atribuir automaticamente suas tags ao Multilingual V3. O adaptador deve declarar as capacidades da versão instalada. [F04, F06]

**Outros candidatos examinados:** IndexTTS 2.5 oferece controle de emoção e velocidade, mas a lista atual de idiomas não inclui português; não será o padrão pt-BR. CosyVoice 3 também não lista português entre seus nove idiomas principais. Ambos podem servir a extensões futuras, sem substituir o caminho prioritário. [F12–F13]

### Componentes de apoio

| Função | Candidato | Regra de integração |
| --- | --- | --- |
| Transcrição | Faster-Whisper | CPU INT8 onde suportado; preservar idioma e tempos [F14] |
| Alinhamento de palavras | WhisperX ou alinhador equivalente local | Carregar apenas quando necessário e com modelo do idioma [F15] |
| Separar quem fala quando | pyannote Community-1 | Opcional; baixar previamente pesos e aceitar termos aplicáveis; desativar telemetria [F16] |
| Conversão direta de voz | Seed-VC | Comparar preservação de atuação e timbre; repositório arquivado, exigir dependências fixadas e manutenção local [F17] |
| Conversão com personagem treinado | RVC | Alternativa posterior; precisa de dados e treinamento próprios [F18] |
| Separação de voz e fundo | Demucs como linha de base | Foi concebido para fontes musicais; validar em diálogos, efeitos e vozes simultâneas [F19] |
| Tradução | Argos Translate ou LibreTranslate na própria máquina | Instalar apenas pares necessários; revisar fidelidade e duração [F20] |
| Emoção | emotion2vec+ como ensaio opcional | Calibrar em pt-BR e inglês; conferir licença do checkpoint [F21] |
| Mixagem e exportação | FFmpeg/ffprobe | Manter linha do tempo e canais; filtros locais de loudness e ritmo [F22] |

**Licenças:** registrar separadamente código, pesos e vozes. Kokoro, Qwen e VoxCPM publicam componentes sob Apache-2.0; Chatterbox sob MIT; Piper usa GPL e as vozes têm condições próprias; Seed-VC usa GPL. Fish S2 permite pesquisa e uso não comercial conforme licença própria; IndexTTS e emotion2vec exigem leitura das condições específicas. Uso pessoal orienta a escolha, mas não transforma todas as licenças em equivalentes. Manter os textos das licenças junto aos modelos, sem introduzir um serviço de validação online. [F02–F12, F17, F21]

## 7 Benchmark que decide o motor

Executar na máquina de casa antes de investir na interface completa de clonagem. A sequência de decisão deve ser a mesma para qualquer modelo novo.

1. Inventariar sistema operacional, CPU, instruções suportadas pelo binário, RAM livre, disco e dispositivos de áudio. Não tentar ativar aceleração apenas porque existe uma GPU.
2. Verificar o funcionamento do container e da cadeia de áudio com uma frase curta; um motor leve pode servir apenas para diagnóstico.
3. Ensaiar VoxCPM2, Qwen 1.7B Base e Chatterbox V3 isoladamente, com uma referência limpa. Começar com 5–10 segundos de fala gerada, depois 30 segundos e 2 minutos. Se um não couber, testar a rota otimizada ou versão menor. Uma execução lenta, mas progredindo, não deve falhar por um timeout curto.
4. Repetir em pt-BR e inglês, separando inicialização fria de execução com modelo carregado. Medir RTF, pico de RAM da árvore de processos, disco temporário e erros.
5. Comparar duas ou três gerações por frase para detectar instabilidade. Não escolher apenas a melhor amostra.
6. Executar um projeto de dez minutos em blocos e testar pausa, encerramento forçado e retomada. Só depois tentar uma hora.

**Conjunto de avaliação:** vinte frases por idioma, incluindo números, datas, abreviações, nomes próprios, pergunta, exclamação, sussurro, tristeza, entusiasmo, mudança de idioma e frases compridas. Acrescentar três personagens com timbres distintos, quando existirem referências adequadas. Testar gravação limpa e uma versão com ruído moderado.

**Critérios mínimos propostos:** nenhuma troca ou omissão de frase no conjunto revisado; identidade reconhecível pelo proprietário; pronúncia compreensível; memória dentro do teto; resultado sem cortes ou silêncio inesperado; retomada sem duplicação. Usar notas de 1 a 5 para naturalidade, semelhança e interpretação, com alvo inicial de pelo menos 4 em cada dimensão relevante. Esses alvos são critérios do produto, não resultados já obtidos.

Para escolher entre candidatos que passam, ponderar semelhança 35%, naturalidade 25%, fidelidade ao texto 25% e interpretação 15%. Velocidade não entra na nota; memória e estabilidade são condições de viabilidade. Idioma incompatível, estouro de memória ou licença inadequada eliminam o candidato antes da pontuação. Avaliar português e inglês separadamente, permitindo motores distintos dentro do mesmo personagem quando necessário.

**Se nenhum clone for aceitável no A10:** entregar o editor e o TTS leve como versão parcial, mantendo clonagem explicitamente pendente. Antes de abandonar o recurso, testar um caminho de inferência CPU otimizado com equivalência comprovada. Se continuar inviável, registrar o gargalo e dimensionar hardware; não mascarar a ausência com uma voz genérica.

### Comparação com a referência ElevenLabs

Definir um conjunto de áudios de referência obtidos legitimamente e guardados localmente para avaliação. Registrar data, modelo, configurações, texto e voz utilizados quando essas informações estiverem disponíveis. Não usar apenas o nome da plataforma como padrão abstrato, pois o resultado depende da configuração e do material. Essa comparação não exige integrar o serviço ao app nem enviar referências de voz para fora da máquina.

Comparar pares A/B com identificação oculta, ordem alternada, mesmo texto e volume percebido equivalente. Para avaliar clonagem, usar a mesma voz de origem autorizada e condições comparáveis; se isso não for possível, limitar a conclusão à naturalidade, pronúncia e interpretação, sem alegar equivalência de identidade. Avaliar pelo menos vinte trechos em cada idioma, além de uma narração longa e uma cena de dublagem. Incluir falas neutras, emocionais, pausas, reações e mudanças de ritmo.

**Critério de aceite proposto para a meta:** o proprietário classifica o resultado local como equivalente ou superior em pelo menos 80% dos pares de cada idioma, com média mínima de 4 em 5 para naturalidade, fidelidade ao texto, semelhança quando comparável e interpretação solicitada. Exigir ausência de omissões e repetições não previstas nos trechos finais aprovados. Para dublagem, aplicar também os testes de sincronização e mixagem. O limiar é uma regra de aceitação deste projeto, não uma afirmação científica de equivalência universal.

Registrar separadamente os resultados por idioma, personagem e função; uma boa narração em inglês não comprova clonagem emocional em português. A aprovação pelo proprietário vale para seu uso pessoal; uma alegação pública de equivalência exigiria avaliação independente mais ampla. Se faltar referência comparável, marcar a meta como não avaliada. Se houver diferença perceptível, usar novas referências, ajustes de direção, outras tomadas ou outro motor antes de considerar mudança de hardware. Nenhum prazo curto ou objetivo de velocidade deve encerrar essa busca prematuramente.

## 8 Personagens e aprendizado

### Ficha de personagem

Identificador estável, nome, imagem opcional local, descrição de atuação, idioma principal, sotaque pretendido, motor preferido, versão, referências aprovadas, dicionário de pronúncia e presets de interpretação. A origem pode ser voz própria, voz autorizada, voz pronta licenciada ou voz criada por descrição. Não inferir idade real ou identidade a partir da voz.

Um personagem é independente de um único motor. Cada associação personagem–motor guarda seus próprios artefatos: prompt de clonagem, embedding, referências ou pesos ajustados. Embeddings de um motor não são automaticamente compatíveis com outro. Projetos devem apontar para uma versão imutável do personagem para evitar mudanças retroativas.

### Três formas de melhorar uma voz

**Clonagem por referência:** extrair características de uma ou mais amostras e usá-las durante a geração. Normalmente não modifica os pesos do modelo. É o caminho inicial.

**Curadoria progressiva:** gravar exemplos melhores, corrigir transcrições, identificar ruído, organizar registros neutro, alegre, triste e sussurrado, e comparar a nova versão com a anterior. Esse é o sentido prático de “aprender” na primeira versão do app.

**Treinamento específico:** ajustar pesos ou adaptadores somente quando o motor tiver receita compatível e quando os recursos forem suficientes. Exige conjunto de validação separado, checkpoints e comparação contra a versão anterior. Não executar treinamento contínuo em segundo plano no A10.

### Preparação das amostras

Manter o áudio original e produzir cópias de trabalho na taxa e no formato exigidos pelo motor. Gravar uma pessoa por vez, com microfone estável, sem música, eco forte, compressão agressiva ou cortes de fonemas. Exibir clipping, silêncio, ruído e trechos com mais de um falante para revisão.

Como plano de captura, começar com várias frases limpas de 5–15 segundos e selecionar as melhores; cada adaptador respeita o tamanho de referência aceito pelo modelo. Para repertório expressivo, organizar 5–15 minutos de material variado. Para treinamento futuro, planejar inicialmente 30–120 minutos bem transcritos, ajustando à receita e ao resultado. Essas faixas são orientações de coleta, não mínimos oficiais universais.

Guardar amostras em pt-BR e inglês quando disponíveis. Uma referência em português pode permitir geração em inglês, mas carregar o sotaque da referência. Preferir exemplos do idioma de destino quando isso melhorar a avaliação. Separar conjunto de teste por sessão de gravação para reduzir contaminação entre treino e validação.

### Criação sem uma pessoa real

Permitir personagens definidos por uma voz pronta e ajustes de performance desde o início. Criação por descrição livre depende de modelos de Voice Design aprovados. Quando disponível, gerar candidatos, escolher um áudio base e congelá-lo como referência do personagem; gerar novamente a descrição a cada frase pode mudar a identidade.

## 9 Linguagem de direção de fala

Criar uma sintaxe própria do aplicativo, chamada provisoriamente **Sal0 VoiceScript**. Ela será compilada para controles de cada motor. Os códigos abaixo são uma especificação proposta; não são comandos nativos universais dos modelos.

```text
[personagem=luna][idioma=pt-BR]
[emocao=alegria intensidade=0.6]
[ritmo=1.05]Você conseguiu![/ritmo]
[pausa=450ms]
[tom=sussurro]Agora venha comigo.[/tom]
[/emocao]
[reacao=suspiro]

[personagem=atlas][idioma=en-US]
[emocao=seriedade intensidade=0.4]
We have one more chance.
[/emocao]
```

| Controle | Significado | Implementação possível |
| --- | --- | --- |
| `personagem` e `idioma` | Identidade e língua do trecho | Resolver versão do personagem e capacidade do motor |
| `emocao` e `intensidade` | Intenção interpretativa | Instrução nativa, vetor suportado ou referência expressiva |
| `tom` | Sussurro, narração, grito ou outro estilo | Motor compatível; não reduzir sussurro a volume baixo |
| `ritmo` | Multiplicador; 1,05 significa 5% mais rápido | Controle nativo ou processamento moderado com preservação de altura |
| `altura` | Deslocamento relativo em semitons | Nativo ou pós-processamento; mudanças grandes alteram identidade |
| `volume` | Ganho relativo em dB | Mixagem determinística, respeitando limite de pico |
| `pausa` | Silêncio explícito em milissegundos | Inserção na linha do tempo, independente do modelo |
| `enfase` | Destacar uma palavra ou expressão | Instrução compatível; aproximação deve ser identificada |
| `reacao` | Suspiro, riso, hesitação, respiração | Geração nativa ou amostra autorizada do próprio personagem |
| `pronuncia` | Substituição ou fonema para leitura | Dicionário do app e sintaxe específica do motor |

As emoções iniciais podem incluir neutralidade, alegria, tristeza, raiva, medo, surpresa, calma, seriedade e ironia. Nem todas terão suporte em todos os motores. Os nomes são categorias editoriais, não diagnósticos sobre uma pessoa.

### Regras do compilador

Validar antes de gerar; apontar tag desconhecida e posição do erro. Separar conteúdo falado de metadados. Delimitar escopo e permitir retorno ao padrão. Normalizar valores e rejeitar combinações inválidas. Oferecer escape para colchetes literais. Não enviar tags incompatíveis como texto, pois elas poderiam ser pronunciadas.

Cada controle mostra **nativo**, **aproximado** ou **indisponível**. Se a reação não existir, oferecer trocar de motor, inserir uma amostra do personagem ou removê-la explicitamente. Nunca prometer “riso fiel” a partir de um simples efeito sonoro genérico. Pausas exatas são diferentes de pedir a um modelo uma pausa aproximada.

### Sugestão automática

Um botão “Sugerir interpretação” pode propor marcações a partir de pontuação, conteúdo e, quando houver, áudio original. Na versão leve, usar regras previsíveis. Um modelo de linguagem local opcional pode melhorar a sugestão no futuro, carregado fora da etapa de síntese. O texto original permanece preservado e as alterações são revisáveis. A interpretação manual sempre tem prioridade.

## 10 Emoção e prosódia a partir de áudio

Separar reconhecimento de palavras, identificação de falantes, características acústicas e inferência de emoção. Uma transcrição isolada não contém toda a atuação. “Tudo bem” pode soar calmo, irritado ou irônico com o mesmo texto.

Extrair por trecho: pausas, duração, energia, velocidade aproximada, frequência fundamental quando houver voz periódica e variação de altura. Manter valores ausentes quando a estimativa não for confiável. Sussurro, ruído, canto e vozes sobrepostas exigem tratamento particular; altura mais alta não significa automaticamente alegria.

O classificador emocional opcional produz categorias e escores. Não apresentar esses escores como probabilidades calibradas sem avaliação. Medir erros em amostras próprias de português e inglês; mostrar “incerto” quando o resultado não for robusto. Permitir correção humana e armazenar a sugestão original separada da decisão final. [F21]

No speech-to-speech direto, o objetivo é preservar o máximo possível da interpretação do áudio de entrada. Na recriação por TTS, transferir instruções, pausas e duração como orientação; aceitar que microvariações e reações podem não ser reproduzidas. A qualidade deve ser decidida pela audição, não apenas pela classificação automática.

## 11 Fluxo de texto para fala longa

1. Importar roteiro e preservar uma cópia original. Detectar capítulos, falantes e idiomas; permitir ajuste manual.
2. Validar VoiceScript e transformar em segmentos estruturados com texto falado, controles e personagem.
3. Normalizar números, siglas e pronúncias sem alterar o sentido. Mostrar a leitura normalizada se houver mudança relevante.
4. Dividir por frases, pontuação, troca de idioma ou personagem e limites do motor. O limite é de trabalho por bloco, não de projeto.
5. Selecionar referência estável para cada personagem e registrar motor, versão, parâmetros e semente quando suportada.
6. Gerar blocos sequencialmente, salvar resultado e atualizar manifesto de conclusão antes de iniciar o próximo.
7. Verificar áudio vazio, cortes, repetição, duração anormal e divergência de conteúdo; encaminhar os casos suspeitos à revisão.
8. Concatenar com pausas de roteiro. Usar pequenos crossfades somente em regiões seguras; nunca sobrepor palavras para esconder cortes.
9. Normalizar loudness no nível apropriado, preservando contraste dramático; exportar capítulos e arquivo completo quando o formato permitir.
10. Alinhar o texto com o áudio final para produzir SRT/VTT.

Não carregar um livro inteiro como uma única requisição nem concatenar todo o áudio na RAM. Usar leitura e escrita em fluxo. Guardar contexto de fronteira quando o motor suportar, evitando duplicar o texto falado.

Arquivos WAV convencionais têm limitações de tamanho; para saídas enormes, oferecer RF64 quando compatível, FLAC ou divisão em capítulos. Uploads devem ser retomáveis ou substituíveis pela seleção local de arquivo, sem que o navegador duplique dezenas de gigabytes em memória. Proxy, API, armazenamento e exportador precisam respeitar a mesma política de ausência de cotas arbitrárias.

## 12 Dois caminhos de speech to speech

### Trocar apenas a voz

Áudio original → isolamento opcional da fala → trechos → conversor de voz → recomposição nos tempos de origem → mixagem → saída.

O texto e o idioma permanecem os mesmos. Esta rota deve ser a primeira escolha quando o objetivo for ouvir a atuação original com o timbre de um personagem. Preservar o tempo de origem e conferir se o conversor alterou duração. Para um personagem totalmente novo, usar uma referência aprovada. Seed-VC é um candidato a comparar; RVC depende de um modelo treinado do personagem. [F17–F18]

### Recriar ou traduzir a fala

Áudio → transcrição → revisão → tradução opcional → direção de atuação → TTS do personagem → ajuste temporal → saída.

Esta rota permite mudar palavras e idioma, mas pode modificar a interpretação. A tradução inglês–português deve considerar contexto, nomes e espaço disponível. Separar “tradução fiel” de “adaptação para caber no tempo”; qualquer condensação precisa ficar visível para revisão.

O usuário deve escolher entre “Preservar a atuação” e “Recriar a fala”. Não trocar silenciosamente a conversão direta por ASR e TTS quando isso mudar o resultado. Falha de um motor deve conservar os insumos e permitir tentar outro.

## 13 Dublagem de vídeo e elenco

### Pipeline completo

1. Inspecionar contêiner, trilhas, canais, duração e timestamps com ffprobe. Permitir escolher a faixa original.
2. Preservar o vídeo original. Extrair áudio de trabalho sem perda desnecessária.
3. Preferir trilhas de diálogo e ambiente já separadas quando existirem. Se só houver mixagem final, experimentar separação local e ouvir vazamento de voz e perda de efeitos.
4. Detectar fala e, opcionalmente, separar quem fala quando. Atribuir “Falante 1”, “Falante 2” etc.; permitir unir, dividir e corrigir.
5. Mapear cada falante para um personagem. Não tratar diarização como isolamento de fontes: reconhecer duas pessoas falando juntas não produz automaticamente dois áudios limpos.
6. Transcrever e revisar. Para outro idioma, traduzir com contexto e aprovar o texto antes da síntese.
7. Converter diretamente ou recriar cada fala; salvar várias tomadas quando necessário.
8. Encaixar falas nas janelas originais, com ajuste moderado de ritmo e preservação de altura. Priorizar regeneração ou edição de texto quando o ajuste prejudicar naturalidade.
9. Ouvir voz isolada, fundo isolado e mixagem. Controlar volume por personagem, ambiente e reação.
10. Remontar vídeo preservando timestamps. Usar cópia da trilha de vídeo quando compatível e sem legendas queimadas; renderizar imagem somente quando necessário.
11. Exportar vídeo dublado, faixa de voz, ambiente quando disponível, SRT original, SRT traduzido e SRT correspondente à dublagem final.

### Sincronização

Guardar tempos como unidades inteiras de alta precisão, evitando soma de durações arredondadas. A origem temporal vem do arquivo, inclusive em vídeo com taxa de quadros variável. A duração de cada fala gerada deve ser medida. Controlar excesso e falta de fala por trecho, nunca acumulando deslocamento nas falas seguintes.

Definir inicialmente ajuste automático de ritmo de até aproximadamente 10% como política conservadora, configurável e sujeita à audição; não é um limite físico do filtro. Fora disso, sinalizar para revisão. Não cortar uma palavra para caber nem acelerar uma fala inteira sem mostrar o resultado.

**Sincronizar áudio com o vídeo não altera movimentos da boca.** Sincronização labial visual é outro módulo, com modelos, custo e critérios próprios, fora da primeira entrega. Música cantada também deve ser um modo separado de fala, pois exige tratamento de notas, duração e expressão musical.

### Casos difíceis

Falas simultâneas devem usar trilhas separadas quando disponíveis ou seguir para revisão manual. Efeitos, reverberação, respiração e música podem ficar presos à voz removida. Nenhum separador deve ser apresentado como restauração perfeita do fundo. Conservar uma cópia do original e oferecer comparação rápida antes/depois.

## 14 Legendas e arquivos SRT

Oferecer três origens: transcrição de mídia, roteiro alinhado ao áudio gerado e importação de SRT existente. Preservar SRT original separado de SRT traduzido e SRT da nova dublagem. Se a fala for regenerada, a legenda final deve ser realinhada; copiar tempos antigos sem conferir não é suficiente.

O editor mostra texto, início, fim, falante e reprodução do trecho. Permitir dividir, juntar, corrigir tempos e restaurar versão. Exportar UTF-8 e formato `HH:MM:SS,mmm`, com numeração válida e tempos crescentes por trilha. Tratar sobreposição deliberada de falantes sem apagar uma fala.

Adotar como perfil editorial inicial até duas linhas e aproximadamente 42 caracteres por linha, com aviso de velocidade de leitura configurável. Esses valores são defaults de interface, não regras universais. Quebrar frases por sentido e respeitar silêncios. Não inventar fala em trechos sem voz.

SRT não preserva toda a direção de interpretação nem um projeto multitrilha. Guardar emoção, personagem, palavras e parâmetros no arquivo JSON do projeto; opcionalmente exportar VTT ou ASS para recursos adicionais. Queimar legendas no vídeo é uma opção explícita e exige nova renderização.

## 15 Arquitetura proposta

**Interface local leve + API Python + executor sequencial + adaptadores de modelos + armazenamento persistente.** O navegador não deve carregar os modelos de IA. O serviço deve continuar trabalhando se a aba for fechada, e a interface recupera seu estado ao reabrir.

```text
Interface local
    |
API de projetos, personagens, mídia e trabalhos
    |
Fila persistente e coordenador de recursos
    |
Executor isolado por família de modelo
    |
TTS | Conversão de voz | ASR | Tradução | Alinhamento
    |
FFmpeg e exportação

SQLite + arquivos locais + manifesto de modelos
```

### Tecnologias e separação

Usar HTML/CSS/TypeScript com componentes leves, preservando o visual Sal0. Um framework é opcional; evitar dependência de um frontend pesado para o primeiro release. FastAPI serve a interface e a API na mesma origem local. SQLite guarda metadados e estado; áudio e vídeo ficam como arquivos. FFmpeg opera por subprocesso, com argumentos estruturados.

Um coordenador dentro do container inicia processos de IA em ambientes independentes, incluídos na imagem e fixados por motor. Não forçar Chatterbox, Qwen, alinhador e conversor à mesma versão de PyTorch. Cada adaptador possui ambiente fixado, comando de inicialização, contrato de entrada/saída e teste offline. A comunicação pode usar arquivos de solicitação e resultado JSON para trabalhos longos, evitando transferir áudio grande serializado em base64.

Não exigir Redis, banco remoto, Kubernetes, login na nuvem ou servidores de inferência orientados a GPUs potentes. O formato de distribuição é imagem Docker Linux amd64 e Compose importável no ZimaOS. Inicialmente, um único container com ambientes internos separados simplifica o controle de memória. Separar serviços depois somente quando houver necessidade de dependências ou manutenção. Não montar o socket Docker no app.

### Contrato dos adaptadores

Cada motor informa nome e revisão, idiomas, dispositivo aceito, limite por chamada, formatos, taxa de amostragem, suporte a clonagem, referência transcrita, emoções, reações, controle de duração e treinamento. O coordenador consulta isso antes de aceitar um trabalho.

Operações conceituais: `probe`, `prepare_voice`, `synthesize`, `convert_voice`, `transcribe`, `align`, `translate` e `unload`, apenas onde se aplicarem. Cada resposta deve incluir arquivos, duração, parâmetros efetivos, avisos e estado de erro estruturado. Capacidades não implementadas retornam erro explícito, nunca um resultado genérico com aparência de sucesso.

### Serviços de aplicação

Projetos e personagens; catálogo de modelos; validação de roteiro; segmentação; fila; monitor de memória e disco; revisão; exportação; backup; diagnóstico. Progresso enviado por eventos locais, como SSE, sem polling agressivo. Rotas de início de processamento retornam imediatamente um identificador; o trabalho não fica preso a uma requisição HTTP de horas.

## 16 Dados e persistência

| Entidade | Campos essenciais |
| --- | --- |
| Personagem | ID, nome, origem, idioma, descrição, versão ativa |
| Versão de voz | Personagem, motor/revisão, referências, artefatos, presets, avaliação |
| Mídia | ID, hash, nome, formato, duração, canais, caminho e origem |
| Projeto | ID, modo, elenco, mídia base, roteiro, idiomas, revisão |
| Segmento | ID, tempos de origem, texto original e aprovado, personagem, controles, estado |
| Tomada | Segmento, arquivo, duração, modelo, parâmetros, semente e avaliação |
| Trabalho | Projeto, etapa, progresso, checkpoint, tentativas, erro e timestamps |
| Modelo instalado | Fonte, revisão, hash, licença, arquivos, ambiente e benchmark |

```text
data/
  app.sqlite
  models/
  characters/<id>/versions/<versao>/
  media/originals/
  projects/<id>/project.json
  projects/<id>/segments/
  jobs/<id>/checkpoints/
  cache/
  exports/
  backups/
```

Usar caminhos relativos ao diretório de dados no projeto exportado. Nomes visíveis podem se repetir; IDs e hashes não. Registrar taxa de amostragem, versão do normalizador de texto e dependências relevantes. Alterar roteiro, referência, motor ou parâmetro deve invalidar somente os resultados dependentes.

### Exemplo de segmento persistido

```json
{
  "schema_version": 1,
  "id": "seg_00042",
  "character_id": "luna",
  "voice_version": 3,
  "language": "pt-BR",
  "source_start_ms": 12800,
  "source_end_ms": 15600,
  "spoken_text": "Agora venha comigo.",
  "direction": {"style": "whisper", "rate": 1.0},
  "review_status": "approved",
  "selected_take_id": null
}
```

O JSON é um exemplo de contrato de projeto. Não representa uma API existente. Na implementação, usar tempos com precisão superior a milissegundos quando exigido pelo alinhamento e registrar também a base temporal da mídia.

## 17 Fila sem cotas arbitrárias

Estados: aguardando, preparando, processando, aguardando revisão, pausado, concluído, cancelado e falhou. A máquina trabalha em uma etapa pesada por vez; outras tarefas podem ser editadas ou aguardarem revisão. Concluídos saem da fila ativa e ficam no histórico do projeto e na Biblioteca.

Salvar checkpoint após cada bloco concluído, com arquivo escrito de forma atômica. Na retomada, verificar hash e integridade antes de reutilizar. Se ocorrer falta de energia, repetir somente o bloco incompleto. Cancelar deve encerrar toda a árvore de processos do trabalho e preservar resultados já confirmados.

O cache usa conteúdo, motor, revisão, personagem, referência, idioma e parâmetros como chave. Dois trabalhos com o mesmo nome não compartilham resultado por esse motivo. Um texto corrigido não pode receber áudio antigo. O editor permite limpar temporários sem apagar referências ou tomadas escolhidas.

Antes de começar, estimar espaço para original, intermediários e exportação. Durante o trabalho, observar RAM e disco; ao atingir reserva mínima, pausar com explicação e opção de continuar após liberar recursos. O número de trabalhos é administrado pelo armazenamento e paginação, não por um teto artificial de minutos ou caracteres.

## 18 Instalação e operação offline

### Assistente inicial

1. Identificar versão do ZimaOS e Docker e verificar os binários CPU da imagem Linux amd64, incluindo instruções exigidas pelas bibliotecas. Um binário incompatível pode falhar mesmo com RAM suficiente.
2. Selecionar diretório de dados e apresentar orçamento de disco.
3. Importar o Compose no ZimaOS, conferir volumes e porta, iniciar o núcleo e instalar os candidatos de qualidade individualmente, com fonte, tamanho, licença e revisão visíveis.
4. Testar reprodução, gravação, exportação e uma frase em cada idioma.
5. Executar o benchmark de clonagem e salvar o perfil aprovado.
6. Ativar modo offline e repetir o fluxo com a rede externa bloqueada.

O instalador deve incluir tokenizadores, vocoders, dicionários, fonemizadores e modelos auxiliares, além dos pesos principais. Pacotes de tradução e diarização podem requerer download ou aceitação de termos antes do uso offline. Não deixar uma dependência descobrir na primeira dublagem que precisa acessar a internet.

Servir fontes, ícones, ajuda e scripts localmente. Desativar telemetria e atualização automática; no pyannote, definir explicitamente `PYANNOTE_METRICS_ENABLED=0`. Usar carregamento por caminho local e flags offline onde existirem. O teste de rede bloqueada é a validação final, não apenas uma opção marcada na interface. [F16]

### Pacote Docker para ZimaOS

Entregar `Dockerfile`, `compose.yaml`, exemplo de configuração, manual de importação, healthcheck, script de migração e imagem versionada para `linux/amd64`. Não publicar uma tag `latest` como única forma de recuperar uma instalação. Modelos e projetos ficam fora da camada gravável da imagem, sob `/data`.

A instalação deve permitir escolher o disco de dados. O caminho `/DATA/AppData/sal0-voz` abaixo é um exemplo a validar no gerenciador de armazenamento; não presumir que ele aponta para o maior disco. Para uma pasta de entrada do servidor, oferecer montagem somente leitura em `/imports`. Não montar `/app`, pois isso esconderia os arquivos da imagem.

O exemplo seguinte é um **contrato de implantação a implementar e testar**, não uma imagem já publicada. As variáveis `SAL0_*` e a rota de saúde fazem parte da especificação proposta. A imagem precisa ser construída ou carregada antes da importação definitiva.

```yaml
name: sal0-voz
services:
  sal0-voz:
    image: sal0-voz:0.1.0-cpu
    platform: linux/amd64
    init: true
    restart: unless-stopped
    ports:
      - "7886:7860"
    volumes:
      - /DATA/AppData/sal0-voz:/data
    environment:
      SAL0_DEVICE: cpu
      SAL0_QUALITY: best
      SAL0_MAX_ACTIVE_WORKERS: "1"
      SAL0_OFFLINE: "1"
      HF_HUB_OFFLINE: "1"
      HF_HUB_DISABLE_TELEMETRY: "1"
      PYANNOTE_METRICS_ENABLED: "0"
      TZ: America/Sao_Paulo
    mem_limit: 10g
    stop_grace_period: 5m
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
```

A porta 7886 é proposta para não usar a mesma porta padrão da referência, 7885; confirmar disponibilidade. O limite de 10 GB é inicial e inclui todos os processos do container. O gerenciador deve pausar antes do teto para evitar encerramento por falta de memória. A rota de saúde verifica o serviço, não exige que um trabalho de horas já tenha terminado. Ao receber sinal de parada, terminar ou interromper com segurança o bloco em andamento; retomar depois pelo checkpoint.

O perfil offline pressupõe que os modelos já estejam presentes. Criar um procedimento de preparação separado, com download explícito para `/data/models`, e depois voltar ao perfil offline. Para instalação sem rede, entregar arquivo da imagem exportada, modelos permitidos para distribuição e hashes, usando `docker load` ou o mecanismo compatível da instalação. Flags offline não bloqueiam toda rede por si só; testar saída para a internet bloqueada mantendo a rede local funcional.

Na interface do ZimaOS, oferecer nome, ícone, descrição e endereço de abertura. Se o app for empacotado para catálogo, usar os metadados `x-casaos` conforme a referência oficial e validar a compatibilidade do importador com o Compose escolhido. Testar volumes, limites de memória, healthcheck e reinício após boot. [F23]

Executar como usuário não privilegiado, preparar permissões do volume e rotacionar logs. O cache de modelos não deve ser apagado ao recriar o container. Backups consistentes devem pausar escrita ou usar o mecanismo de backup do SQLite, sem copiar apenas um banco ativo incompleto. Atualizações devem conservar `/data` e oferecer rollback da imagem e do esquema compatível.

**Microfone no navegador:** ao acessar pelo IP do ZimaOS via HTTP, navegadores podem bloquear captura por falta de contexto seguro. Prever HTTPS local confiável para gravação ou oferecer upload de áudio gravado no cliente. O microfone deve ser o do dispositivo do usuário, sem depender de placa de som no servidor. [F24]

### Operação segura e simples

No container, escutar em `0.0.0.0` na porta interna para permitir o acesso pela porta publicada do Docker. Na instalação ZimaOS, usar autenticação local e acesso pela rede doméstica; não configurar encaminhamento de porta no roteador. Validar origem e proteger rotas que alteram estado. Workers internos não publicam portas adicionais. Nunca expor caminhos arbitrários do disco em uma rota de download. Validar arquivos importados e não executar comandos contidos em roteiros, legendas ou metadados.

As referências de voz permanecem locais; registrar sua origem e autorização na ficha. Não enviar logs com áudio ou texto completo por padrão. Importar modelos apenas de fontes conhecidas, verificar hashes e dar preferência a formatos seguros quando disponíveis. A exclusão de um personagem deve avisar sobre projetos dependentes; backup deve incluir banco, referências, roteiro e tomadas aprovadas.

Atualizações são manuais, com backup e possibilidade de voltar à versão anterior. Não alterar pesos ou voz de um projeto antigo silenciosamente. Modelos ausentes após restaurar um backup devem ser identificados por revisão exata, com opção de restaurar a partir do pacote offline.

## 19 Plano de implementação

As fases são organizadas por dependência e evidência de conclusão. Não fixar prazo em semanas antes do ensaio no A10, porque instalação e velocidade dos modelos podem mudar o esforço significativamente.

### Fase 0 Viabilidade na máquina real

Inventário do ZimaOS, disco, outros containers, teste dos binários e comparação VoxCPM2/Qwen 1.7B/Chatterbox em CPU, mais ASR de qualidade. Produzir relatório com RAM, RTF e amostras. **Saída:** motor de qualidade escolhido por idioma e personagem, decisão explícita sobre clonagem e gargalos documentados. Se a clonagem falhar, decidir a alternativa antes de desenvolver seus controles avançados.

### Fase 1 Núcleo local e identidade Sal0

Imagem Docker CPU e Compose para ZimaOS, estrutura modular, tema claro/escuro, Criar, Personagens, Biblioteca, SQLite, trabalhos persistentes e volume de dados. **Saída:** importar arquivo, criar personagem e retomar um trabalho simulado ou leve sem perder estado.

### Fase 2 Texto para voz e personagens

Motor de maior qualidade aprovado, ficha de personagem, roteiro por blocos, prévia, tomadas e exportação de áudio; motor leve apenas como opção. **Saída:** gerar português e inglês, reabrir projeto e conservar identidade da voz. O checkpoint do produto deve informar se clonagem ainda está pendente.

### Fase 3 Direção e legendas

VoiceScript, pausa, ritmo, pronúncia, indicação de suporte por motor, ASR, revisão e SRT do áudio final. **Saída:** comandos não são pronunciados, nenhuma frase se perde e legendas seguem a versão aprovada.

### Fase 4 Conversão direta de voz

Adaptador de conversão, referências, tratamento de trechos, comparação antes/depois e recomposição temporal. **Saída:** trocar timbre mantendo texto em português e inglês, com avaliação de atuação e duração.

### Fase 5 Dublagem

Extração, elenco, identificação de falantes opcional, ambiente, tradução local, edição temporal, mixagem e vídeo exportado. **Saída:** vídeo curto com dois falantes aprovado, depois um vídeo de trinta minutos sem deriva e um projeto longo com retomada.

### Fase 6 Expressividade e aprendizado assistido

Reconhecimento de emoção avaliado, sugestões revisáveis, biblioteca de reações, criação por descrição e treinamento quando viável. **Saída:** melhora verificável sobre a base e possibilidade de voltar à versão anterior.

### Fase 7 Empacotamento e robustez

Importação do Compose em instalação limpa do ZimaOS, pacote offline da imagem e modelos, backup/restauração, diagnóstico, migrações, manual integrado e atualização reversível. **Saída:** todos os fluxos essenciais passam com rede externa bloqueada e na configuração de hardware documentada.

## 20 Critérios de aceite do produto

| Área | Teste obrigatório | Resultado esperado |
| --- | --- | --- |
| Offline | Reiniciar sem rede após preparar modelos e dependências | Criar, transcrever, converter e exportar sem chamadas externas obrigatórias |
| Texto longo | Roteiro com pelo menos 100 mil caracteres e mudança de capítulos | Sem truncamento; todos os segmentos têm saída ou erro explícito |
| Áudio longo | Projeto de duas horas em blocos | Memória limitada pelo bloco, não pela duração total; sem perda de final |
| Retomada | Interromper durante geração e durante exportação | Não duplicar falas e preservar blocos válidos |
| Personagem | Frases inéditas em pt-BR e inglês | Semelhança reconhecida e avaliação separada por idioma |
| VoiceScript | Tags válidas, inválidas e literais | Texto falado limpo e suporte explicado |
| Emoção | Amostras revisadas por idioma | Relatório de erros; correção manual sempre possível |
| SRT | Início, meio, fim, silêncio e nova tomada | Tempos coerentes com a mídia final e formato válido |
| Conversão de voz | Mesma fala em voz de personagem | Conteúdo preservado e artefatos revisados |
| Dublagem | Dois falantes, música e trecho sobreposto | Elenco correto; sobreposição não resolvida fica sinalizada |
| Sincronização | Vídeo longo com janelas marcadas | Sem deriva acumulada; meta de bordas em até 200 ms em falas simples revisadas |
| Recursos | Memória baixa e disco quase cheio | Pausa recuperável, sem corromper projeto |
| Backup | Restaurar em instalação limpa | Roteiro, personagem, mídia e tomadas acessíveis |
| Referência ElevenLabs | Comparação A/B do capítulo 7 em pt-BR e inglês | Meta aprovada por idioma e recurso ou diferença explicitamente registrada |

O teste de duas horas demonstra robustez daquela carga, não duração infinita. A ausência de cota deve resultar da arquitetura e da capacidade de processar sucessivos blocos. Testes caros podem usar geração leve para validar persistência, mas a qualidade da clonagem deve ser testada com o motor real.

Adicionar testes automatizados para parser, segmentação, invalidação de cache, estados da fila, retomada e validação de SRT. Usar pequenos arquivos conhecidos para integração de FFmpeg. A qualidade de voz exige avaliação auditiva; transcrever novamente o áudio ajuda a identificar omissões, mas não substitui a escuta nem prova semelhança.

## 21 Evolução de hardware e decisões pendentes

**Não comprar hardware antes da fase 0.** O relatório deve mostrar se o problema é memória, compatibilidade, disco ou qualidade do modelo. Tempo alto sozinho não justifica exigir upgrade, pois o proprietário aceita processamento demorado. Aumentar RAM não transforma a GPU integrada em acelerador moderno. SSD melhora carregamento e arquivos temporários; não elimina o custo da síntese neural.

Se houver upgrade, considerar uma plataforma mais moderna e uma GPU dedicada compatível com os motores escolhidos. Como faixas de planejamento, 12–16 GB de VRAM ampliam opções intermediárias; 24 GB ou mais dão mais margem para motores pesados. São classes de capacidade, não requisitos universais nem uma recomendação de compra específica. Fish S2 documenta 24 GB de GPU para inferência; outros motores precisam de medidas próprias. Conferir fonte, gabinete, refrigeração, conexões e sistema operacional antes de escolher uma placa. [F10]

| Decisão | Estado ou encaminhamento |
| --- | --- |
| Hardware base | Confirmado: A10-9700E, 16 GB, vídeo integrado |
| Idiomas | Confirmados: pt-BR e inglês |
| Finalidade | Confirmada: uso pessoal |
| Sistema operacional da máquina de casa | Confirmado: ZimaOS; registrar versão e Docker na fase 0 |
| Disco e espaço livre | Medir antes dos downloads |
| Prioridade de qualidade | Confirmada: máxima qualidade viável; tempo é apenas informativo |
| Referência desejada | Confirmada: resultados no nível do ElevenLabs, sujeitos à comparação auditiva |
| Motor principal de clonagem | VoxCPM2, Qwen 1.7B Base e Chatterbox V3, sujeitos ao benchmark |
| Distribuição e interface | Docker Compose no ZimaOS; interface web acessada pela rede doméstica |
| Conta única ou multiusuário | Conta única inicial; expansão opcional |
| Conversão ao vivo e lip sync visual | Fora do escopo inicial |

## 22 Orientação para iniciar o desenvolvimento

Criar um repositório independente para Sal0 Voz. Preservar os créditos e avisos dos componentes reutilizados. Começar pela fase 0 e implementar somente os motores que passarem nos testes. O desenho de dados e os adaptadores devem permitir substituição futura sem alterar os projetos existentes.

**Instrução de execução:** construir um app local distribuído obrigatoriamente em Docker Compose para ZimaOS, no AMD PRO A10-9700E com 16 GB de RAM, usando CPU, português brasileiro e inglês. A prioridade é a maior qualidade possível dentro da memória disponível, mesmo com processamento de muitas horas; velocidade não deve reduzir automaticamente a qualidade. Buscar resultados no nível do ElevenLabs e validar essa meta por comparação auditiva em pt-BR e inglês, sem depender de sua API ou de processamento remoto. Preservar a identidade visual do Sal0-Karaoke e oferecer modos simples e detalhados. Implementar processamento por blocos, personagens versionados, fila persistente, texto para fala, clonagem avaliada, VoiceScript, SRT, conversão de voz e dublagem por etapas. Não usar serviços externos para inferência. Não apresentar vozes prontas como clonagem, inferência como treinamento nem sugestões de emoção como certeza. Entregar cada fase com teste funcional e evidência de consumo na máquina alvo.

**Primeira sessão na máquina de casa:** levantar ZimaOS, Docker, armazenamento e containers concorrentes; importar o Compose de teste e configurar volumes; medir um candidato de qualidade em pt-BR e inglês; registrar memória, qualidade e tempo e então fechar a escolha dos motores.

## 23 Fontes e rastreabilidade

Fontes oficiais consultadas em 21/09/2026. Especificações publicadas são fatos de referência; arquitetura, prioridades, orçamentos e critérios de aceite deste guia são propostas. Não foram executados benchmarks na máquina de casa.

- **R01** [Sal0-Karaoke README no commit analisado](https://github.com/Sal0-Apps/Sal0-Karaoke/blob/f87b4713e0f0f1227e0c1dddf8567137b7804305/README.md).
- **R02** [Manual de operação do Sal0-Karaoke](https://github.com/Sal0-Apps/Sal0-Karaoke/blob/f87b4713e0f0f1227e0c1dddf8567137b7804305/MANUAL.md).
- **R03** [Interface e estilos do Sal0-Karaoke](https://github.com/Sal0-Apps/Sal0-Karaoke/blob/f87b4713e0f0f1227e0c1dddf8567137b7804305/app/templates/index.html).
- **R04** [Dependências do Sal0-Karaoke](https://github.com/Sal0-Apps/Sal0-Karaoke/blob/f87b4713e0f0f1227e0c1dddf8567137b7804305/app/requirements.txt).
- **F01** [AMD PRO A10-9700E](https://www.amd.com/en/support/downloads/drivers.html/processors/pro-a-series/pro-a-series-a10-apu-for-desktops/7th-gen-amd-pro-a10-9700e-apu.html) e [matrizes de compatibilidade ROCm](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibility.html).
- **F02** [Kokoro e idiomas](https://github.com/hexgrad/kokoro), [pesos Kokoro 82M](https://huggingface.co/hexgrad/Kokoro-82M) e [vozes disponíveis](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).
- **F03** [Piper mantido pela Open Home Foundation](https://github.com/OHF-Voice/piper1-gpl/blob/main/README.md).
- **F04** [Chatterbox e variantes](https://github.com/resemble-ai/chatterbox).
- **F05** [Chatterbox Multilingual pt-BR](https://huggingface.co/ResembleAI/Chatterbox-Multilingual-pt-br).
- **F06** [Qwen3-TTS e diferenças entre variantes](https://github.com/QwenLM/Qwen3-TTS).
- **F07** [Qwen3-TTS 0.6B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base).
- **F08** [VoxCPM2 e opções de inferência local](https://github.com/OpenBMB/VoxCPM).
- **F09** [Fish Speech](https://github.com/fishaudio/fish-speech) e [model card S2 Pro](https://huggingface.co/fishaudio/s2-pro).
- **F10** [Instalação e requisitos Fish Audio](https://speech.fish.audio/install/) e [inferência](https://speech.fish.audio/inference/).
- **F11** [OmniVoice](https://github.com/k2-fsa/OmniVoice).
- **F12** [IndexTTS e idiomas da versão 2.5](https://github.com/index-tts/index-tts) e [licença](https://github.com/index-tts/index-tts/blob/main/LICENSE).
- **F13** [CosyVoice](https://github.com/QwenAudio/CosyVoice).
- **F14** [Faster-Whisper e inferência CPU](https://github.com/SYSTRAN/faster-whisper).
- **F15** [WhisperX e alinhamento](https://github.com/m-bain/whisperX).
- **F16** [pyannote e telemetria](https://github.com/pyannote/pyannote-audio) e [Community-1 offline](https://huggingface.co/pyannote/speaker-diarization-community-1).
- **F17** [Seed-VC e situação do repositório](https://github.com/Plachtaa/seed-vc).
- **F18** [RVC](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI).
- **F19** [Demucs](https://github.com/adefossez/demucs).
- **F20** [Argos Translate](https://github.com/argosopentech/argos-translate); integração LibreTranslate da referência em R02.
- **F21** [emotion2vec+ e licença do checkpoint](https://huggingface.co/emotion2vec/emotion2vec_plus_large) e [repositório oficial](https://github.com/ddlBoJack/emotion2vec).
- **F22** [Filtros FFmpeg](https://ffmpeg.org/ffmpeg-filters.html).

- **F23** [ZimaOS e importação de Compose](https://www.zimaspace.com/docs/zimaos/features) e [referência Docker Compose e x-casaos](https://www.zimaspace.com/docs/developer/app-store-compose-x-casaos).
- **F24** [MDN getUserMedia e contexto seguro](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).
