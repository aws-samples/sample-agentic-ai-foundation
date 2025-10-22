"""FastAPI application definition"""

from datetime import datetime
import time
import logging
import sys

from fastapi import FastAPI, HTTPException, Request
import structlog

# Configure basic logging to terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

from cx_agent_backend.infrastructure.config.container import Container
from cx_agent_backend.infrastructure.config.settings import settings
from cx_agent_backend.presentation.api.conversation_router import (
    router as conversation_router,
    send_message
)
from cx_agent_backend.presentation.schemas.conversation_schemas import SendMessageRequest


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
            "cx_agent_backend.presentation.api.conversation_router",
        ]
    )

    # Include routers
    app.include_router(conversation_router)
    
    # Add AgentCore-compliant endpoints directly to app
    @app.get("/ping")
    async def ping():
        """Container health check endpoint"""
        
        return {"status": "Healthy", "time_of_last_update": int(time.time())}
    
    @app.post("/invocations")
    async def invocations(request: dict, http_request: Request):
        """AgentCore-compatible endpoint to invoke the agent (send message & get response)"""
        
        # Extract session information
        session_id = http_request.headers.get("x-amzn-bedrock-agentcore-runtime-session-id", "N/A")
        
        # Extract data from input object
        input_data = request.get("input", {})
        prompt = input_data.get("prompt")
        feedback = input_data.get("feedback")
        user_id = input_data.get("user_id")
        
        if not prompt and not feedback:
            raise HTTPException(status_code=400, detail="Either prompt or feedback must be provided in input.")
        
        # Convert to internal format
        internal_request = SendMessageRequest(
            prompt=prompt,
            conversation_id=None,
            model=settings.default_model,
            user_id=user_id,
            feedback=feedback
        )
        
        # Call internal endpoint
        response = await send_message(internal_request)
        
        # Return agent contract format with metadata
        output = {
            "message": response.response,
            "timestamp": datetime.utcnow().isoformat(),
            "model": internal_request.model
        }
        
        # Add metadata if available
        if hasattr(response, 'metadata') and response.metadata:
            output["metadata"] = response.metadata
            
        return {"output": output}

    # Store container in app state
    app.container = container

    logger.info("Application created", settings=settings.model_dump())

    return app
