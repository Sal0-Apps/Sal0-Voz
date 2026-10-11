# Sal0 Voz 0.3.0: instalação e clonagem em CPU

O Sal0 Karaokê prepara seus modelos na construção da imagem (`app/Dockerfile`, `download_models.py`). O Voz anterior iniciava downloads de modelos no servidor depois de abrir o aplicativo. A versão 0.3.0 adota a preparação na imagem para os dois modelos necessários ao fluxo principal de clonagem.

| Aspecto | Voz anterior | Voz 0.3.0 |
|---|---|---|
| Primeira clonagem | Dependia de downloads após iniciar | Qwen 1.7B e large-v3-turbo incluídos na imagem |
| Tela inicial | Voz simples e opções técnicas expostas | Enviar gravação → escrever texto → gerar |
| Referência sem texto | Clonagem reduzida por vetor de voz | Transcrição automática, áudio e texto na clonagem completa |
| Transcrição padrão | Whisper medium | Faster-Whisper large-v3-turbo, CPU INT8 |
| Vários trechos | Recarregava o modelo por trecho | Uma sessão Qwen por trabalho, com referência preparada em cache |
| Novo texto | Seleção precisava ser refeita | Preserva a voz e o perfil; trabalho anterior continua na fila |
| Recursos do Compose | Duas CPUs e 10 GiB | Quatro CPUs e 12 GiB, reservando parte dos 16 GB para o sistema |
| Download opcional interrompido | Exigia intervenção no trabalho | Preserva a fila, mostra progresso e permite retomar preparação |

O Whisper transcreve a gravação de referência e gera legendas. O Qwen Base é o motor de clonagem. O perfil padrão 1.7B prioriza fidelidade; 0.6B é uma opção com menor custo de memória e CPU. Não há troca automática por uma voz simples quando o clone falha.

Os pesos padrão ficam em `/opt/sal0-models/models`, fora do volume `/data`. Cada construção verifica os hashes da revisão fixa. O volume preserva vozes, textos, trabalhos, resultados e modelos opcionais. Os motores executam sem CUDA, com telemetria desativada, uma tarefa pesada por vez e transcrição encerrada antes de carregar Qwen.

O fluxo recebe gravações com pelo menos três segundos, recomenda de 6 a 30 e usa os primeiros 30 segundos na preparação automática. Uma transcrição manual exige áudio de até 30 segundos. O idioma da referência é separado do idioma do texto novo. A versão salva da voz é preservada.

O CI publica a imagem somente após testes de código, interface e inferência real offline com 0.6B/Turbo. A qualidade com a voz do proprietário e o consumo real de 1.7B no servidor de quatro núcleos/16 GB ainda precisam ser medidos. Consulte [VALIDACAO.md](VALIDACAO.md) e [MANUAL.md](MANUAL.md).
