"""FastAPI application entry point."""

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from infrastructure.config.container import Container
from infrastructure.config.settings import settings
from presentation.api.conversation_router import router as conversation_router

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


def create_app() -> FastAPI:
    """Create FastAPI application."""
    # Initialize container
    container = Container()

    # Create FastAPI app
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=settings.api_description,
        debug=settings.debug,
    )

    # Wire container
    container.wire(
        modules=[
            "presentation.api.conversation_router",
        ]
    )

    # Include routers
    app.include_router(conversation_router)
    
    # Add AgentCore-compliant endpoints directly to app
    @app.get("/ping")
    async def ping():
        import time
        return {"status": "Healthy", "time_of_last_update": int(time.time())}
    
    @app.post("/invocations")
    async def invocations(request: dict, http_request: Request):
        from fastapi import HTTPException, Request
        from presentation.api.conversation_router import send_message
        from presentation.schemas.conversation_schemas import SendMessageRequest
        from datetime import datetime
        
        # Extract session information
        session_id = http_request.headers.get("x-amzn-bedrock-agentcore-runtime-session-id", "N/A")
        
        # Extract prompt from input object
        input_data = request.get("input", {})
        prompt = input_data.get("prompt", "")
        
        if not prompt:
            raise HTTPException(status_code=400, detail="No prompt found in input. Please provide a 'prompt' key in the input.")
        
        # Convert to internal format
        internal_request = SendMessageRequest(
            prompt=prompt,
            conversation_id=None,
            model=settings.default_model
        )
        
        # Call internal endpoint
        response = await send_message(internal_request)
        
        # Return agent contract format
        return {
            "output": {
                "message": response.response,
                "timestamp": datetime.utcnow().isoformat(),
                "model": internal_request.model
            }
        }

    # Store container in app state
    app.container = container

    logger.info("Application created", settings=settings.model_dump())

    return app


app = create_app()
