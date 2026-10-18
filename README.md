# Mind Bloom — Local AI edition

Mind Bloom Flask wellness app with the saved animated VideoBot assets, optional self-hosted local AI via Ollama, Render deployment configuration, and an Android WebView wrapper.

**Start here:** read [`START_HERE_LOCAL_AI.md`](START_HERE_LOCAL_AI.md) for the full Windows, Ollama, Cloudflare Tunnel, Render and Android setup.

No Gemini API key is required for the self-hosted AI path. The model runs on your own computer, so remote AI responses are available only while that computer and its tunnel are online. The Flask app keeps its existing fallback response logic if the local AI service is unavailable.

Do not commit `.env`, `ai_service/.env`, virtual environments, user databases, or uploaded journal media.
