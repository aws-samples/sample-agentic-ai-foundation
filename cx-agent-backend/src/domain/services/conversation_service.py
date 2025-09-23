"""Domain service for conversation business logic."""

import logging
import os
from uuid import UUID

from langfuse import get_client, Langfuse

from domain.entities.conversation import Conversation, Message
from domain.repositories.conversation_repository import ConversationRepository
from domain.services.agent_service import AgentRequest, AgentService, AgentType
from domain.services.guardrail_service import GuardrailAssessment, GuardrailService

logger = logging.getLogger(__name__)

class ConversationService:
    """Service for conversation business logic."""

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        agent_service: AgentService,
        guardrail_service: GuardrailService | None = None,
        langfuse_config: dict | None = None,
    ):
        self._conversation_repo = conversation_repo
        self._agent_service = agent_service
        self._guardrail_service = guardrail_service
        self._langfuse_config = langfuse_config or {}

    async def start_conversation(self, user_id: str) -> Conversation:
        """Start a new conversation."""
        conversation = Conversation.create(user_id)
        await self._conversation_repo.save(conversation)
        return conversation

    async def send_message(
        self, conversation_id: UUID, content: str, model: str
    ) -> tuple[Message, list[str]]:
        """Send a message and get AI response."""
        # Get conversation
        conversation = await self._conversation_repo.get_by_id(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Add user message
        user_message = Message.create_user_message(content)

        # Check input guardrails
        if self._guardrail_service:
            guardrail_result = await self._guardrail_service.check_input(user_message)
            if guardrail_result.assessment == GuardrailAssessment.BLOCKED:
                blocked_message = Message.create_assistant_message(
                    content=guardrail_result.message,
                    metadata={
                        "blocked_categories": ",".join(
                            guardrail_result.blocked_categories
                        )
                    },
                )
                conversation.add_message(user_message)
                conversation.add_message(blocked_message)
                await self._conversation_repo.save(conversation)
                return blocked_message, []

        conversation.add_message(user_message)

        # Generate AI response through agent
        agent_request = AgentRequest(
            messages=conversation.messages,
            agent_type=AgentType.CUSTOMER_SERVICE,
            user_id=conversation.user_id,
            model=model,
            session_id=str(conversation.id),
            trace_id=None,  # Can be set from FastAPI layer
        )
        agent_response = await self._agent_service.process_request(agent_request)

        # Create AI message
        ai_message = Message.create_assistant_message(
            content=agent_response.content,
            metadata={
                "agent_type": agent_response.agent_type.value,
                "tools_used": ",".join(agent_response.tools_used),
            },
        )

        # Check output guardrails
        if self._guardrail_service:
            guardrail_result = await self._guardrail_service.check_output(ai_message)
            if guardrail_result.assessment == GuardrailAssessment.BLOCKED:
                ai_message = Message.create_assistant_message(
                    content=guardrail_result.message,
                    metadata={
                        "blocked_categories": ",".join(
                            guardrail_result.blocked_categories
                        )
                    },
                )

        conversation.add_message(ai_message)

        # Save conversation
        await self._conversation_repo.save(conversation)

        return ai_message, agent_response.tools_used

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        """Get conversation by ID."""
        return await self._conversation_repo.get_by_id(conversation_id)

    async def get_user_conversations(self, user_id: str) -> list[Conversation]:
        """Get all conversations for a user."""
        return await self._conversation_repo.get_by_user_id(user_id)

    async def log_feedback(self, user_id: str, session_id: str, message_id: str, score: int, comment: str = "") -> None:
        """Log user feedback to Langfuse."""
        
        # Log feedback attempt
        feedback_msg = f"[FEEDBACK] Attempting to log feedback - user_id: {user_id}, session_id: {session_id}, message_id: {message_id}, score: {score}"
        logger.info(feedback_msg)
        
        try:
            
            logger.info("[FEEDBACK] Langfuse config - enabled: %s, host: %s", 
                       self._langfuse_config.get("enabled"), 
                       self._langfuse_config.get("host"))
            
            if self._langfuse_config.get("enabled"):
                logger.info("[FEEDBACK] Langfuse is enabled, setting environment variables")
                os.environ["LANGFUSE_SECRET_KEY"] = self._langfuse_config.get("secret_key")
                os.environ["LANGFUSE_PUBLIC_KEY"] = self._langfuse_config.get("public_key")
                os.environ["LANGFUSE_HOST"] = self._langfuse_config.get("host")
                
                langfuse = get_client()
                predefined_trace_id = Langfuse.create_trace_id(seed=session_id)
                
                logger.info("[FEEDBACK] Calling span.score_trace")
                with langfuse.start_as_current_span(
                    name="langchain-request",
                    trace_context={"trace_id": predefined_trace_id}
                ) as span:
                    result = span.score_trace(
                        name="user-feedback",
                        value=score,
                        data_type="NUMERIC",
                        comment=comment
                    )
                
                logger.info("[FEEDBACK] Successfully created score: %s", result)
            else:
                logger.info("[FEEDBACK] Langfuse is not enabled in config")
        except Exception as e:
            logger.error(f"[FEEDBACK] Failed to log feedback to Langfuse: {e}")
