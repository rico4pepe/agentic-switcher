"""FastAPI application entry point for Agentic Switcher."""

from fastapi import FastAPI


app = FastAPI(
    title="Agentic Switcher",
    description="Agentic transaction orchestration and operations platform",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Return the health status of the API."""
    return {
        "status": "ok",
        "service": "agentic-switcher-api",
    }
