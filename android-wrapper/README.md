# Android WebView wrapper

1. Open this `android-wrapper` folder in Android Studio.
2. In `app/src/main/java/com/mindbloom/web/MainActivity.kt`, replace `https://YOUR-MIND-BLOOM.onrender.com` with your deployed Render URL.
3. Let Gradle sync, then run on an emulator or Android phone.

This wrapper displays the same deployed Mind Bloom website. The AI service token stays on the server and is never placed in this Android project. Browser speech recognition support varies by Android System WebView/device; the normal text chat does not depend on microphone support.
