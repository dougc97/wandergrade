# Optional: container image for hosting the dashboard (Render, Fly, Railway, etc.)
FROM python:3.11-slim
WORKDIR /app
COPY . .
# Platforms inject $PORT; server.py reads it and binds 0.0.0.0 when it's set.
ENV PORT=8000
EXPOSE 8000
CMD ["python3", "server.py"]
