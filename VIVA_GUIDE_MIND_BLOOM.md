# Mind Bloom — Viva Guide (Local AI Project)

## 1. Project overview

Mind Bloom is a web-based wellness and journaling application. The Flask server handles accounts, sessions, database operations, and AI requests. HTML/Jinja templates render pages, CSS styles and animates the interface, and JavaScript handles interactive behaviour in the browser. The Android wrapper is a WebView shell that opens the deployed website; it is not a separate native implementation of all the features.

The local-AI bundle has three possible response paths, in priority order:
1. **Self-hosted AI bridge** when `AI_MODEL_URL` and `AI_SERVICE_TOKEN` are configured.
2. **Gemini API** when the local bridge is not configured/does not return a usable response and `GEMINI_API_KEY` is available.
3. **Rule-based fallback replies** when neither AI path is available. This fallback is not a full language model and can be less flexible.

Important distinction for the viva: the current ZIP contains the **local animated SVG VideoBot** and local-AI bridge. It does not contain the original third-party Live Avatar API integration's complete source. Explain the Live Avatar version as the original hosted-avatar design only to the extent you remember its exact provider workflow; do not claim the local SVG animation is a generated photorealistic video.

## 2. Architecture and request flow

### Browser to backend
1. The user opens a page such as Journal, Meditation, Chat, Exercise, or Video Companion.
2. Flask routes in `app.py` decide what data is needed and render a Jinja template in `templates/`.
3. The browser loads CSS from `static/css/style.css` and JavaScript from `static/js/`.
4. When the user clicks a control, JavaScript either updates the page locally or sends an HTTP request with `fetch()`.
5. Flask validates the request and current logged-in user, queries or updates SQLAlchemy models, and returns HTML or JSON/streamed response data.
6. The browser updates the visible UI.

### Main technology roles
- **HTML / Jinja:** page structure, forms, loops, conditional sections, and server-rendered user-specific values.
- **CSS:** colours, layout, responsive sizing, buttons, transitions, keyframe animations, and avatar appearance.
- **JavaScript:** click handlers, media recording/playback, countdown timers, `fetch()`, speech recognition/synthesis, and animated avatar state.
- **Python / Flask:** routes, login/session checks, input validation, database access, file upload/delete, AI orchestration, and PDF export.
- **Flask-SQLAlchemy / SQLAlchemy:** Python objects mapped to database tables.
- **SQLite:** convenient local development database by default. `DATABASE_URL` can point to PostgreSQL in deployment.
- **Ollama:** runs a downloadable language model on the developer's computer.
- **FastAPI:** small authenticated HTTP bridge that accepts chat requests from Flask and forwards them to Ollama.
- **Gunicorn:** production WSGI server used to run the Flask application on Render.
- **Render:** hosts the web server.
- **GitHub:** source-code version control and repository used by deployment.
- **UptimeRobot:** can periodically request the public URL to check availability; it does not keep a sleeping service truly running or guarantee uptime.
- **Android WebView wrapper:** opens the same responsive website inside an Android app container.

## 3. Database and models

`models.py` defines SQLAlchemy models. A model is a Python class mapped to a database table. `db.Column` defines fields, primary keys uniquely identify rows, and foreign keys connect related records.

Important models include:
- `User`: username, password hash, name, age/profile preferences, language/theme, reminders and settings.
- `JournalEntry`: owner (`user_id`), date, title, text, mood, tags, pin/favourite flags and timestamps.
- `JournalMedia`: journal entry foreign key, stored filename, media type (`photo`, `video`, or `audio`) and upload timestamp.
- `MoodLog` and `DailyCheckin`: mood and daily wellbeing check-in data.
- `TestResult`: saved assessment scores.
- `MeditationSession`: duration, post-session feeling, note and timestamp.
- `ChatSession` / `ChatMessage`: chat sessions and their user/assistant messages.
- `Habit` / `HabitLog`, `SleepLog`, `GratitudeEntry`, `ExerciseLog`, and `FeatureAnnouncement`: other app features.

Relationships such as `User.journal_entries` and `JournalEntry.media` let SQLAlchemy navigate related records. `cascade='all, delete-orphan'` means deleting a parent ORM record can also delete related child records. The code must still remove uploaded files from disk explicitly because a database row deletion does not automatically delete the physical file.

Passwords are stored as hashes using Werkzeug's password-hashing functions, not as readable plaintext. In deployment, `SECRET_KEY` should be a long random environment variable. Do not commit `.env`, API keys, service tokens, real user databases, or journal uploads to GitHub.

## 4. How Gemini API replies work

In the Gemini version, the browser normally sends the message to the Flask backend; the browser should not expose a private API key in client-side JavaScript. The backend reads `GEMINI_API_KEY` from an environment variable and calls the Google GenAI SDK.

The conceptual request sequence is:
1. User types/speaks a message.
2. JavaScript sends it to a Flask route using HTTP `POST` and JSON.
3. Flask checks the session, adds the conversation history and system/persona instructions, and calls the Gemini SDK using the server-side key.
4. Google's service authenticates the request, checks project/quota/rate limits, runs the model, and returns generated text.
5. Flask stores messages as appropriate and returns the answer, in this app often as a streamed sequence of JSON lines.
6. JavaScript reads the stream and updates the caption progressively. When the final answer is ready, the VideoBot calls browser speech synthesis to speak it.

The API key does not independently “turn on” when a user types. It is included by the backend when a request is made to the provider. The provider validates the key and quota on every request. If the free quota is exhausted, the provider may return a quota/rate-limit error; code should show a fallback/error rather than assuming the request succeeded.

Safe viva answer: “The API key is stored as a server environment variable. The frontend sends the user's message to Flask. Flask authenticates the user, builds the prompt and conversation history, calls the Gemini API, receives the generated response and sends it back to the browser.”

## 5. How the local AI works in this ZIP

The local AI is **not running inside the browser** and it is not the same as a canned-response script. Ollama runs the selected language model on the developer's computer. The website can still be hosted on Render, while Flask contacts the developer's local AI bridge through a secure tunnel.

Flow:
1. Flask's `stream_companion_response()` checks whether `AI_MODEL_URL` and `AI_SERVICE_TOKEN` are configured.
2. Flask sends the newest message, recent history, and persona/system prompt to the configured bridge endpoint with the `X-Service-Token` header.
3. The FastAPI app in `ai_service/app.py` checks that a service token is configured and compares the received token securely.
4. The bridge packages the system prompt, recent messages and newest user message into Ollama's `/api/chat` request.
5. Ollama runs the selected model (configured by `OLLAMA_MODEL`, default shown in this project is `qwen2.5:1.5b`) and returns generated text.
6. The bridge returns JSON containing `reply`; Flask streams the reply to the browser.
7. If the bridge fails, Flask can try Gemini if configured; otherwise it uses its rule-based fallback.

The bridge uses `SERVICE_TOKEN` to protect the endpoint. That token is an app-to-app secret, **not** a model API key. Keep it only in server-side environment variables. A Cloudflare Quick Tunnel can expose the bridge temporarily over HTTPS so Render can reach the laptop; its URL can change, and the laptop, Ollama, bridge and tunnel must remain online. Thus this architecture is suitable for a demonstration, but it is not a guaranteed 24/7 production service.

## 6. Animated VideoBot, lip movement and voice

In this local project, the companion is drawn as inline SVG markup in the Video page and styled by CSS. It is a 2D animated illustration, not a newly generated video file.

- The SVG contains face shapes and mouth shapes, including closed/open mouth elements.
- CSS defines avatar appearance, glow/halo effects, and keyframe animations.
- In `static/js/video_call.js`, `setSpeaking(true)` adds the `speaking` class to the SVG when speech begins; `setSpeaking(false)` removes it when speech ends or errors.
- In `static/css/style.css`, selectors such as `.av-svg.speaking .m-open` animate the open mouth, while the closed mouth is hidden. This is simple speech-state animation, not phoneme-accurate lip-sync.
- `SpeechRecognition` / `webkitSpeechRecognition` can convert the user's microphone speech into text when supported. The UI also allows typed messages.
- `SpeechSynthesisUtterance` and `window.speechSynthesis` ask the browser/operating system to read the assistant reply aloud. The browser's installed voices, language support, volume, and autoplay policy affect whether sound is heard. A visible “Hear reply again” control lets the user replay the latest response after an autoplay or voice-start issue.
- The AI model creates the **text reply**; it does not create the SVG, voice waveform, or mouth animation. JavaScript sends the text to the speech engine and toggles the avatar animation during playback.

If speech is not audible, check device volume, browser site sound permissions, available OS text-to-speech voices, and WebView/browser support. Browser speech synthesis is platform-dependent; a guaranteed custom voice requires a dedicated TTS service or a native Android TextToSpeech bridge. The current implementation uses the browser's built-in speech synthesis.

The original Live Avatar API version is conceptually different: a hosted avatar service may generate or stream a more realistic talking avatar and may supply audio/video output. Its API key and session flow are separate from the local SVG avatar. Present only the provider details you actually implemented in the original app.

## 7. Journal media: recording, playback and deletion

The Journal stores the journal entry's text/metadata in the database and stores uploaded media as files under `static/uploads/journal/<user_id>/`. The `journal_media` table stores the filename and media type so the page can find each file.

The browser's `MediaRecorder` can record microphone audio or camera video after the user grants permission. File input controls allow uploads. JavaScript previews newly selected files with `URL.createObjectURL(file)`. After saving, the server stores the file and creates a `JournalMedia` row.

The fixed media controls use native HTML `<video controls>` and `<audio controls>`, so saved video can be played and scrubbed and saved audio can be listened to again. Media deletion now asks for confirmation before sending the delete request. Entry deletion also asks for confirmation. Flask must verify that the media/entry belongs to the logged-in user before deleting it.

## 8. Meditation module

The meditation module now uses a countdown timer only; the stopwatch was removed. The user can choose a preset or enter a custom number of minutes. JavaScript stores the total seconds, updates the displayed countdown each second, and calls `onTimerComplete()` at zero.

When the timer finishes, the page plays a short chime using the Web Audio API oscillator/gain nodes, flashes the timer card, shows a toast, and can show a browser notification if permission was granted. Browsers can restrict sound until a user interaction, so starting the timer first helps unlock audio. The supplied MP3 is stored at `static/audio/meditation-track.mp3` and is played using a native HTML audio element. Session duration, feeling and note can be saved as a `MeditationSession`.

## 9. Exercise mode and animations

The app's exercise pages are rendered from Jinja templates, including `templates/exercise.html`. CSS controls layout, visual states, transitions and keyframe animations. JavaScript can respond to selecting an exercise, updating timers/counters, changing the active step, and displaying progress. The Python backend saves exercise logs through the relevant route/model. When explaining a particular exercise animation in the viva, point to the actual selector/function in the version you demonstrate rather than claiming that CSS alone calculates exercise form or posture.

## 10. Assessment / machine-learning component

The app includes a CSV dataset and saved scikit-learn artifacts (`model/knn_model.pkl`, `scaler.pkl`, `encoder.pkl`). The app imports pandas, NumPy and scikit-learn for the assessment component. A K-nearest-neighbours (KNN) classifier compares a feature vector to nearby training examples; `StandardScaler` scales numeric features, and `LabelEncoder` converts categorical labels into numeric values. The dataset and feature pipeline need to match the saved model's training process. Treat outputs as an educational wellbeing indicator, not a medical diagnosis.

## 11. GitHub, Render and UptimeRobot

**GitHub** stores source code and its history. Git tracks changes as commits, supports branches and rollback, and allows Render to deploy from a repository. A `.gitignore` prevents secrets, virtual environments, local databases and uploaded media from being committed.

**Render** runs the Flask web service on a server. The project has `render.yaml` and a Gunicorn start command. Environment variables such as `SECRET_KEY`, `DATABASE_URL`, `AI_MODEL_URL`, and `AI_SERVICE_TOKEN` are configured in the hosting dashboard. PostgreSQL is appropriate for persistent shared deployment data; a local SQLite file on an ephemeral host may not survive rebuilds/redeploys.

**UptimeRobot** is an external monitoring service that periodically requests the deployed URL and alerts when it appears unavailable. It may incidentally keep some free services warm, but it is not a reliable way to defeat sleep policies or guarantee service uptime.

## 12. Android APK process

The included `android-wrapper` is a native Android project containing a `WebView`. `MainActivity.kt` enables JavaScript and DOM storage, configures `WebViewClient` and `WebChromeClient`, and loads the Render URL. This means the app mostly displays the same website rather than duplicating its HTML/CSS/Python code in Android.

Typical process:
1. Open `android-wrapper` in Android Studio.
2. Replace `https://YOUR-MIND-BLOOM.onrender.com` in `MainActivity.kt` with the real HTTPS website URL.
3. Sync Gradle and wait for dependencies/build setup.
4. Test on an emulator or phone.
5. Use **Build > Build Bundle(s) / APK(s) > Build APK(s)** in Android Studio.
6. Install the generated debug APK for testing; create a signed release APK from **Generate Signed Bundle / APK** for distribution.

The wrapper needs internet access because the website and backend are hosted remotely. Microphone, camera, speech and media capabilities depend on WebView permissions, site HTTPS and Android settings. The current manifest has internet permission; if camera/microphone capture is needed in the wrapper, verify the required runtime permissions and WebChromeClient permission handling for the tested Android version.

## 13. Quick viva questions

**Why Flask?** It is a lightweight Python web framework for routes, templates, sessions and APIs.

**Why SQLAlchemy?** It maps Python classes to relational tables and handles queries/relationships without writing every SQL statement manually.

**Why JavaScript?** To make the page interactive without reloading for every action, read streamed AI responses, record media, run timers and trigger speech/animations.

**Why CSS animations?** To add visual feedback and motion through selectors, transitions and keyframes without requiring a video file.

**Why store media on disk and metadata in SQL?** Large binary files are better stored as files/object storage, while the database stores the owner, filename, type and relationship to the journal entry. For production, durable object storage is safer than ephemeral local disk.

**What happens when the free Gemini quota ends?** Gemini calls can fail due to quota. The local-AI configuration routes requests through Flask to Ollama instead, provided the bridge/tunnel are online; otherwise the app can fall back to simple rule-based replies.

**Does local AI require an internet connection?** Ollama can generate locally without sending prompts to an AI provider, but this project's public Render website still needs internet to reach the bridge tunnel. Running the whole app locally with Ollama can work without the tunnel.

**Is the local VideoBot generated by the local model?** No. The model generates text. The SVG avatar is authored frontend markup; CSS animates the mouth when browser speech is playing. Voice comes from the browser/OS speech engine.

**What are the limitations?** Small local models may be less capable; browser TTS/recognition support varies; a temporary tunnel can change or go offline; free hosting/database storage may have limits; and the wellness app is not a substitute for professional care.

## 14. Files to know for demonstration

- `app.py` — Flask setup, routes, auth, upload APIs and AI orchestration.
- `models.py` — database tables and relationships.
- `templates/journal_entry.html` — journal entry form, media controls and delete confirmations.
- `templates/journal_meditate.html` — countdown, sound, music and session logging.
- `templates/video.html` — VideoBot page and SVG avatar markup.
- `static/js/video_call.js` — chat requests, speech synthesis/recognition, avatar speaking state.
- `static/css/style.css` — shared design and speaking-mouth animation.
- `ai_service/app.py` — token-protected bridge to Ollama.
- `requirements.txt` / `ai_service/requirements.txt` — Python dependencies.
- `render.yaml` — deployment configuration.
- `android-wrapper/` — Android WebView shell.
- `.env.example` — names of configuration variables; fill real secrets privately in `.env` or hosting environment settings.
