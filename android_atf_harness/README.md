# A11y ATF Harness (Android)

A tiny instrumentation project that runs **Google's real Accessibility Test
Framework (ATF)** against a **black-box target app** — no source or Espresso
integration required in the app under test.

It launches the target package, then for each screen snapshots the foreground
window's `AccessibilityNodeInfo` tree via `UiAutomation`, builds an ATF
`AccessibilityHierarchy`, runs `AccessibilityCheckPreset.LATEST`, and writes
`results.json` + per-screen screenshots to the harness app's external files dir.

## Why this design
Appium's UiAutomator2 driver does **not** run ATF (validated). For arbitrary APKs
you usually can't add an Espresso `AccessibilityChecks` pass, so this harness uses
`UiAutomation`'s cross-app access to audit any foreground app.

## Build
```bash
cd android_atf_harness
gradle wrapper            # once, if no ./gradlew yet (needs Gradle installed)
./gradlew assembleDebug assembleDebugAndroidTest
# outputs:
#   app/build/outputs/apk/debug/app-debug.apk
#   app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
```

## Run (normally invoked by backend/app/scanners/android/atf.py)
```bash
adb install -r -t app/build/outputs/apk/debug/app-debug.apk
adb install -r -t app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w \
  -e targetPackage com.example.target -e maxScreens 20 \
  com.a11yaudit.harness.test/androidx.test.runner.AndroidJUnitRunner
adb pull /sdcard/Android/data/com.a11yaudit.harness/files/a11y ./out
```

## Notes / [re-verify]
- Only ATF **ERROR** (and WARNING, for triage) results are exported; the Python
  normalizer emits `fail` findings **only** for ERROR severity. WARNING/INFO and
  all screen-reader-dependent behaviour → Needs Manual Review (TalkBack pass).
- Exact ATF artifact/version resolves transitively via
  `androidx.test.espresso:espresso-accessibility`. Verify the resolved ATF
  version and the `AccessibilityHierarchyAndroid.newBuilder(...)` overload at
  build time; record it in `third_party/VERSIONS.lock`.
- Authenticated flows: extend `AtfAuditTest` with a scripted login (UiAutomator),
  or drive login via the Appium navigator before triggering the audit.
