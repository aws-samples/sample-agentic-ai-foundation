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
    router as conversation_router
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
        from cx_agent_backend.domain.services.conversation_service import ConversationService
        
        # Get conversation service from container
        conversation_service = container.conversation_service()
        
        # Extract session information
        # session_id = http_request.headers.get("x-amzn-bedrock-agentcore-runtime-session-id")
        
        # Extract data from input object
        input_data = request.get("input", {})
        prompt = input_data.get("prompt")
        feedback = input_data.get("feedback")
        conversation_id_str = input_data.get("conversation_id")
        user_id = input_data.get("user_id")
        
        # Convert conversation_id to UUID
        from uuid import UUID
        conversation_id = UUID(conversation_id_str) if conversation_id_str else None
        
        if not prompt and not feedback:
            raise HTTPException(status_code=400, detail="Either prompt or feedback must be provided in input.")
        
        try:
            # Process feedback if provided
            if feedback:
                feedback_score = 1 if feedback.get("score", 0) > 0.5 else 0
                await conversation_service.log_feedback(
                    user_id, 
                    feedback.get("session_id"), 
                    feedback.get("run_id"), 
                    feedback_score, 
                    feedback.get("comment")
                )
            
            # If no prompt, this is feedback-only request
            if not prompt:
                return {"output": {"message": "Feedback received", "timestamp": datetime.utcnow().isoformat()}}
            
            message, tools_used = await conversation_service.send_message(
                conversation_id=conversation_id,
                user_id=user_id,
                content=prompt,
                model=settings.default_model,
            )
            
            # Return agent contract format with metadata
            output = {
                "message": message.content,
                "timestamp": datetime.utcnow().isoformat(),
                "model": settings.default_model
            }
            
            # Add metadata if available
            if hasattr(message, 'metadata') and message.metadata:
                output["metadata"] = message.metadata
                
            return {"output": output}
            
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to process request: {str(e)}")

    # Store container in app state
    app.container = container

    logger.info("Application created", settings=settings.model_dump())

    return app
