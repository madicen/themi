# Use an AI server of your own

Themi can use a model running on a computer you own, with Ollama or LM Studio, or any
other server that speaks the OpenAI API. Nothing leaves your home, and it costs nothing
to run, but it needs a computer strong enough for the model.

1. Install [Ollama](https://ollama.com) or [LM Studio](https://lmstudio.ai) on a computer
   Themi can reach.
2. Download a model in it and start its server.
3. In Themi, open [My AI](/ai) and add a backend with the server's address and the model's
   name.

If Themi runs in Docker, `localhost` means the container, not the computer it runs on.
Use the computer's address on your network instead.
