"""Central configuration. Everything can be overridden with environment variables."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

JS_EXTENSIONS = {".js", ".mjs", ".cjs", ".jsx"}
IGNORED_DIRS = {
    "node_modules", ".git", "dist", "build", "coverage", ".next", "out",
    "vendor", "bower_components", ".cache", ".cartographer", "__pycache__",
}
MAX_FILE_BYTES = int(os.getenv("CARTO_MAX_FILE_BYTES", 1_000_000))

# Method / function names whose first string argument names a *tool* being invoked,
# e.g. `registry.invoke('openDeeplink', ...)`, `callTool("getWeather")`.
TOOL_INVOKE_NAMES = set(
    os.getenv(
        "CARTO_TOOL_INVOKE_NAMES",
        "invoke,invokeTool,callTool,runTool,executeTool,useTool,dispatchTool,execTool,tool",
    ).split(",")
)
# Method / function names that *register* a tool: `registry.register('name', handler)`.
TOOL_REGISTER_NAMES = set(
    os.getenv(
        "CARTO_TOOL_REGISTER_NAMES",
        "register,registerTool,addTool,defineTool,tool,createTool",
    ).split(",")
)

# Chunking
CHUNK_MAX_LINES = 60
CHUNK_WINDOW = 45
CHUNK_OVERLAP = 10

# Embeddings (CPU, ONNX via fastembed). Set CARTO_EMBED_MODEL=none to disable dense retrieval.
EMBED_MODEL = os.getenv("CARTO_EMBED_MODEL", "jinaai/jina-embeddings-v2-base-code")
MODEL_CACHE = os.getenv("CARTO_MODEL_CACHE", str(ROOT / ".models"))
EMBED_BATCH = int(os.getenv("CARTO_EMBED_BATCH", 16))
EMBED_MAX_CHARS = int(os.getenv("CARTO_EMBED_MAX_CHARS", 1500))

# Index storage
INDEX_HOME = Path(os.getenv("CARTO_INDEX_HOME", str(ROOT / ".cartographer")))

# Agent
AGENT_MAX_STEPS = int(os.getenv("CARTO_AGENT_MAX_STEPS", 8))
CALL_EXPANSION_DEPTH = int(os.getenv("CARTO_CALL_DEPTH", 3))

# LLM provider: auto | gemini | openai | groq | ollama | none
LLM_PROVIDER = os.getenv("CARTO_LLM", "auto")
