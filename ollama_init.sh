#!/bin/bash

# Start Ollama in the background
ollama serve &

# Wait for Ollama to be ready
echo "Waiting for Ollama to start..."
while ! curl -s http://localhost:11434/api/tags > /dev/null; do
    sleep 1
done

# Pull required models
echo "Pulling models..."
ollama pull qwen2.5-coder:7b
ollama pull llama3.2:3b
ollama pull nomic-embed-text

echo "Models ready. Keeping container alive..."
wait
