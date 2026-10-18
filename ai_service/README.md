# Mind Bloom Local AI Bridge

This service does **not** call Gemini or any other AI API. It forwards authenticated chat requests to Ollama running on the same computer.

## Windows quick start
1. Install Ollama from https://ollama.com/download.
2. Open PowerShell and run `ollama pull qwen2.5:1.5b` (use `qwen2.5:0.5b` on a low-memory computer, and update `OLLAMA_MODEL` in `.env`).
3. Run `setup_ai_service.bat` once.
4. Edit this folder's `.env`; set `SERVICE_TOKEN` to a long random value. Keep it private.
5. Run `run_ai_service.bat`. It listens on port 7860.
6. Test `http://127.0.0.1:7860/health` in your browser.

The main Flask app must have `AI_MODEL_URL` set to `http://127.0.0.1:7860/chat` for local testing and `AI_SERVICE_TOKEN` set to the same token.

## Public Render deployment at zero hosting cost
Render cannot reach `127.0.0.1` on your laptop. To connect Render to this laptop-hosted model, install Cloudflare Tunnel and run:

`cloudflared tunnel --url http://localhost:7860`

Copy the generated HTTPS `trycloudflare.com` address and set Render's `AI_MODEL_URL` to that address plus `/chat`; set Render's `AI_SERVICE_TOKEN` to the same token. Do not put the token in browser JavaScript or Android code.

A Quick Tunnel URL can change, and the service is available only while your laptop, Ollama, AI bridge and tunnel are running. This is the no-cost trade-off; it is not a 24/7 production host.
