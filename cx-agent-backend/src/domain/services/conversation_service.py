"""Domain service for conversation business logic."""

from uuid import UUID

from domain.entities.conversation import Conversation, Message
from domain.repositories.conversation_repository import ConversationRepository
from domain.services.agent_service import AgentRequest, AgentService, AgentType
from domain.services.guardrail_service import GuardrailAssessment, GuardrailService


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
        self, conversation_id: UUID, content: str, model: str = "gpt-4o-mini"
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
        try:
            import os
            from langfuse import Langfuse
            
            if self._langfuse_config.get("enabled"):
                os.environ["LANGFUSE_SECRET_KEY"] = self._langfuse_config.get("secret_key")
                os.environ["LANGFUSE_PUBLIC_KEY"] = self._langfuse_config.get("public_key")
                os.environ["LANGFUSE_HOST"] = self._langfuse_config.get("host")
                
                langfuse = Langfuse()
                
                langfuse.create_score(
                    trace_id=str(f"{user_id}_{session_id}"),
                    name="user-feedback",
                    value=score,
                    data_type="NUMERIC",
                    comment=comment,
                )
        except Exception as e:
            print(f"Failed to log feedback to Langfuse: {e}")
