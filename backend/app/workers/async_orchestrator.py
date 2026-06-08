import asyncio
import logging
from app.workers.tavily_dossier_agent import process_leads as run_tavily_dossier
from app.workers.fg_profiler_agent import process_fg_leads as run_gemini_profiler

logger = logging.getLogger(__name__)

async def leadgen_background_orchestrator():
    """Continuous async loop monitoring contact statuses for pipeline changes."""
    logger.info("Starting Asyncio LeadGen Orchestrator in background...")
    while True:
        try:
            # We run the synchronous functions in a threadpool to not block the FastAPI async event loop
            await asyncio.to_thread(run_tavily_dossier)
            await asyncio.to_thread(run_gemini_profiler)
        except Exception as e:
            logger.error(f"Error in background orchestrator: {e}")
        
        # Polling interval
        await asyncio.sleep(60)

