#!/usr/bin/env bash
# The temporary server has its worker disabled. Test only the APK and UI.
set -u
gradle -p android --no-daemon :app:connectedDebugAndroidTest
sal0_android_result=$?
mkdir -p android-ui-evidence
adb logcat -d > android-ui-evidence/logcat.txt
adb pull /sdcard/Android/data/com.sal0.voz/files/ android-ui-evidence/ >/dev/null 2>&1 || true
if [ -f "${RUNNER_TEMP:-/tmp}/sal0-android-ui.log" ]; then
  cp "${RUNNER_TEMP:-/tmp}/sal0-android-ui.log" android-ui-evidence/server.log
fi
exit "$sal0_android_result"
