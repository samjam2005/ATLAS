"""
Aether Intelligence — FastAPI Application

Startup sequence:
  1. Load .env
  2. Initialize TerpAI API bridge (validates JWT token)
  3. Set up agent (find/create "Aether Study Assistant")
  4. Serve requests

On shutdown:
  1. Close httpx client
"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

from routers import chat, generate, parse, graph, data, knowledge, catalog, career
from services.terpai import bridge as terpai_bridge


async def _init_agent_layer():
    """
    Initialize the Aether Agent Layer and set up the agent.
    Runs at startup. Errors are logged but don't crash the server.
    """
    try:
        await terpai_bridge.start()

        if terpai_bridge._ready:
            # Find or create the Aether agent
            try:
                await terpai_bridge.setup_or_find_agent()
            except Exception as e:
                log.warning(f"⚠️  Agent setup skipped: {e}")

            log.info("✅ Aether Agent Layer initialized")
        else:
            log.warning(
                "⚠️  Aether Agent Layer not ready. "
                "Set AGENT_TOKEN (TERPAI_TOKEN) in .env to enable it. "
                "Falling back to Gemini for all requests."
            )
    except Exception as e:
        log.error(f"❌ Agent layer init failed: {e}. Falling back to Gemini for all requests.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: start the agent layer on boot, close on shutdown."""
    await _init_agent_layer()
    yield
    log.info("🛑 Shutting down Aether Agent Layer...")
    await terpai_bridge.stop()


app = FastAPI(title="Aether Intelligence API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Person 4: Voice / ElevenLabs
try:
    from routers import voice
    app.include_router(voice.router, prefix="/api")
except ImportError:
    log.warning("⚠️  Voice router not found — Person 4 hasn't pushed yet. Skipping.")

# Person 2: AI-powered routes
app.include_router(chat.router, prefix="/api")
app.include_router(generate.router, prefix="/api")
app.include_router(parse.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(career.router, prefix="/api")

# Person 4: Mastery endpoint
try:
    from routers import mastery
    app.include_router(mastery.router, prefix="/api")
except ImportError:
    log.warning("⚠️  Mastery router not found — Person 4 hasn't pushed yet. Skipping.")

# ZO email agent
try:
    from routers import zo
    app.include_router(zo.router, prefix="/api")
    log.info("✅ ZO email agent router registered")
except ImportError:
    log.warning("⚠️  ZO router not found. Skipping.")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "agent_layer_ready": terpai_bridge._ready,
        "agent_url": terpai_bridge._agent_chat_url,
    }
