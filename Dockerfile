FROM python:3.11-slim

# Node is needed by the MCP child servers (tavily-mcp, mongodb-mcp-server).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn cmd.api.main:app --host ${HOST} --port ${PORT}"]
