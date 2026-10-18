# Mind Bloom — start from scratch (free self-hosted AI)

This bundle contains the existing Mind Bloom Flask project, its templates/static assets and animated videobot, a small local-AI bridge, Render configuration, and a sample Android WebView wrapper.

## Important free-hosting limitation

The Flask website can be deployed on Render, but a language model is too large for Render's free web-service memory budget. This zero-hosting-cost setup runs the model on **your own Windows laptop** using Ollama and securely exposes only the small bridge through a Cloudflare Quick Tunnel. Consequently, AI replies work on the deployed website and Android while your laptop, Ollama, bridge and tunnel are running. If your laptop is off or the tunnel URL changes, the remote AI will be unavailable until you restart/update it. For a reliable 24/7 AI endpoint, you need an always-on machine or paid/eligible hosted compute; no configuration can guarantee that for free.

## A. Prepare the project on Windows

1. Extract this ZIP to a folder such as `D:\Studyy\sem 5\Minor Project\Mind_Bloom_updated`.
2. Install **Python 3.11** (not Python 3.14 for this project, because the existing pandas/scikit-learn stack had wheel/build issues on 3.14). During installation, enable the Python launcher / PATH.
3. Open Command Prompt in the project folder and run `setup.bat` once.
4. Copy `.env.example` to `.env` if setup did not create it. Set `SECRET_KEY` to a long random value. Keep `.env` private.
5. Install Ollama from https://ollama.com/download.
6. In a new terminal, run `ollama pull qwen2.5:1.5b`. For a lower-memory computer use `ollama pull qwen2.5:0.5b` and change `OLLAMA_MODEL` in `ai_service/.env` to that exact model tag.

## B. Configure and run the local AI bridge

1. Open `ai_service` and run `setup_ai_service.bat`.
2. Edit `ai_service/.env`. Set `SERVICE_TOKEN` to a long random secret. You create this token yourself; it is **not** an AI provider API key. Do not share it publicly.
3. Copy that exact same token into the root `.env` as `AI_SERVICE_TOKEN`.
4. In the root `.env`, set `AI_MODEL_URL=http://127.0.0.1:7860/chat` for local testing.
5. Start Ollama (the Windows app/service usually starts it automatically). Confirm `ollama list` shows your model.
6. Run `ai_service/run_ai_service.bat` and leave that terminal open. Visit `http://127.0.0.1:7860/health`; it should show `status: ok` and `token_configured: true`.
7. In another terminal at the project root, run `run.bat`. Sign in and test Chat / VideoBot. If the AI bridge is down, the app may use its existing local fallback replies instead.

## C. Deploy the website to Render

1. Create a GitHub repository and upload the project. Do **not** upload `.env`, `ai_service/.env`, virtual environments, local database files, or user uploads.
2. Create a persistent PostgreSQL database on a free external provider and copy its connection string. Render's own free PostgreSQL offering may expire after its free retention period; choose storage deliberately if you need to preserve user accounts/journal data.
3. In Render, create a Web Service from the GitHub repository. The included `render.yaml` defines Python 3.11, `pip install -r requirements.txt`, and a Gunicorn start command. If you use Blueprint deployment, fill the unsynced variables manually in the Render dashboard.
4. Set these Render environment variables:
   - `SECRET_KEY`: generate a long random value (Render may generate it automatically from `render.yaml`).
   - `DATABASE_URL`: the external PostgreSQL connection string.
   - `AI_MODEL_URL`: initially leave blank or set after the tunnel step below.
   - `AI_SERVICE_TOKEN`: the same value as `SERVICE_TOKEN` in `ai_service/.env`.
5. Deploy and verify the Render website loads. If using an existing Render service, check its Python version and environment variables.

## D. Connect Render to your laptop-hosted AI without an AI API key

1. Install Cloudflare Tunnel (`cloudflared`) using https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/.
2. Keep Ollama and `ai_service/run_ai_service.bat` running.
3. Run `run_ai_tunnel.bat` in the project root (or run `cloudflared tunnel --url http://localhost:7860`).
4. Copy the HTTPS URL printed by Cloudflare, e.g. `https://example-name.trycloudflare.com`.
5. In Render environment variables, set `AI_MODEL_URL` to `https://example-name.trycloudflare.com/chat` and `AI_SERVICE_TOKEN` to the same secret token. Trigger a redeploy if Render asks; environment variable changes normally restart the service.
6. Test the Chat and VideoBot from your public Render URL. The backend sends chat messages to your laptop's Ollama model. The animated avatar and browser speech stay in the website frontend.

Quick Tunnel addresses are temporary and can change each time you restart the tunnel. If it changes, update `AI_MODEL_URL` in Render. Keep the laptop awake and connected to the internet. Never put `SERVICE_TOKEN` in HTML, JavaScript, or Android code.

## E. Android

Open `android-wrapper` in Android Studio, replace `YOUR-MIND-BLOOM.onrender.com` in `MainActivity.kt` with the real Render URL, sync Gradle, then run it on your phone. This wrapper opens the same website; it does not need a second chatbot or an AI key. Text chat works through the same backend. Voice recognition support depends on the phone's Android System WebView/browser.

## F. Render configuration and troubleshooting

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --workers 1 --threads 4 --timeout 120 app:app`
- Runtime: Python 3.11.11 (`runtime.txt` and `render.yaml`).
- `AI_MODEL_URL` must end in `/chat`; it is the bridge URL, not the Ollama URL.
- `AI_SERVICE_TOKEN` on Render must exactly match `SERVICE_TOKEN` in `ai_service/.env`.
- `503` from AI bridge: check Ollama is running, the model exists (`ollama list`), and the bridge/tunnel terminals are open.
- `401`: tokens do not match.
- If Render fails during dependency installation, confirm it is using Python 3.11 and inspect the first package build error in its logs.
- No Gemini API key is required for the self-hosted route. `GEMINI_API_KEY` is optional for the legacy fallback only; leave it blank if you do not want to use Gemini.

The local model generates responses but is smaller and less capable than a large hosted model. Do not present its outputs as medical diagnosis or emergency care.
