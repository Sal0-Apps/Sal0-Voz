# Sal0 Voz Android

Cliente Android nativo baseado no cliente do Sal0 Karaokê (`c20a6a71039235805fa729bcc336e7e43fa0478c`). O processamento continua no servidor CPU; o APK abre o estúdio em WebView e mantém a sessão.

Baixe o APK em [Releases](https://github.com/Sal0-Apps/Sal0-Voz/releases/tag/android-v0.3.1). Requer Android 8 ou posterior. Na primeira abertura, informe o endereço local do Sal0 Voz, por exemplo `http://192.168.1.50:7886` ou `http://voz.server`. Endereço externo e nome da rede Wi-Fi são opcionais. O app testa os endereços e reconecta ao voltar para primeiro plano.

O seletor de arquivos usa o Android Files para enviar áudio ou vídeo, inclusive arquivos que o provedor não identifica com MIME específico. A conversão acontece no servidor. Downloads preservam a sessão e usam o nome definido no estúdio. A geração continua se o app for fechado.

Para compilar, use Java 17, Gradle 9.4.1 e Android SDK 36:

```sh
cd android
gradle :app:testDebugUnitTest :app:lintRelease :app:assembleRelease
```

O workflow publica APK e SHA-256. Assim como o cliente Karaokê, o APK de instalação direta usa assinatura de desenvolvimento quando não há chave de distribuição. O cache do CI reutiliza essa chave; uma chave perdida exige reinstalação do cliente. Para distribuição com identidade permanente, configure `ANDROID_KEYSTORE_PATH`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` e `ANDROID_KEY_PASSWORD` no ambiente de build. Nunca publique a chave no repositório.

HTTPS com certificado inválido é recusado. HTTP é aceito para o servidor local. A permissão de localização só é solicitada quando você configura o SSID para identificar a rede Wi-Fi. A telemetria de WebView foi desativada.
