# Sal0 Voz Android

Cliente Android nativo baseado no cliente do Sal0 Karaokê (`c20a6a71039235805fa729bcc336e7e43fa0478c`). O processamento continua no servidor CPU; o APK abre o estúdio em WebView e mantém a sessão.

Baixe o APK em [Releases](https://github.com/Sal0-Apps/Sal0-Voz/releases/tag/android-v0.5.1). Requer Android 8 ou posterior. Na primeira abertura, informe o endereço local do Sal0 Voz, por exemplo `http://192.168.1.50:7886` ou `http://voz.server`. Endereço externo e nome da rede Wi-Fi são opcionais. O app testa os endereços e reconecta ao voltar para primeiro plano.

Na versão 0.5.1, Force Dark e escurecimento algorítmico ficam desativados no
WebView para preservar os temas nativos e seus ícones. O cache da interface é
renovado sem remover cookies, sessão ou endereços. O rodapé mantém **Recarregar**
e **Conexão**. Atualize também o servidor para 0.5.1 ou posterior para usar Cristal,
Aurora, Wall e **Tema antigo**, com modos claro/escuro.

**Migração do APK público 0.4.1 para 0.5.1:** os certificados dos dois arquivos
publicados são diferentes. Anote os endereços local/externo e o SSID em
**Conexão** antes de reinstalar o cliente. A reinstalação remove as preferências
e a sessão locais; as vozes, os modelos e os trabalhos permanecem no servidor.

Ao abrir pelo Samsung Internet, o filtro próprio do navegador pode continuar
alterando cores: desative **Forçar modo escuro para conteúdo da web** no menu de
modo escuro do navegador e escolha a aparência no Sal0.

O seletor de arquivos usa o Android Files para enviar áudio ou vídeo, inclusive arquivos que o provedor não identifica com MIME específico. A conversão acontece no servidor. Downloads preservam a sessão e usam o nome definido no estúdio. A geração continua se o app for fechado.

Para compilar, use Java 17, Gradle 9.4.1 e Android SDK 36:

```sh
cd android
gradle :app:testDebugUnitTest :app:lintRelease :app:assembleRelease
```

O workflow publica APK e SHA-256. Assim como o cliente Karaokê, o APK de instalação direta usa assinatura de desenvolvimento quando não há chave de distribuição. O cache do CI reutiliza essa chave; uma chave perdida exige reinstalação do cliente. Para distribuição com identidade permanente, configure `ANDROID_KEYSTORE_PATH`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` e `ANDROID_KEY_PASSWORD` no ambiente de build. Nunca publique a chave no repositório.

HTTPS com certificado inválido é recusado. HTTP é aceito para o servidor local. A permissão de localização só é solicitada quando você configura o SSID para identificar a rede Wi-Fi. A telemetria de WebView foi desativada.

O CI também abre o APK num emulador Android 15, contra um servidor temporário sem executor. Verifica toques, navegação, edição de voz, seleção/exclusão com cancelamento, painéis, resultados, recarga com sessão e rotação. Não baixa pesos nem executa modelos neurais.
