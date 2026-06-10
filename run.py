"""Entry point: uvicorn serving the API + dashboard, orchestrator inside."""
import logging

import uvicorn

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)

if __name__ == "__main__":
    uvicorn.run(
        "app.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
