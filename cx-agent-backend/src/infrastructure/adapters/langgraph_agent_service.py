"""LangGraph implementation of agent service."""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
import os
import base64
import logging
from langgraph.prebuilt import create_react_agent
from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)

from domain.entities.conversation import Message, MessageRole
from domain.services.agent_service import (
    AgentRequest,
    AgentResponse,
    AgentService,
    AgentType,
)
from domain.services.guardrail_service import GuardrailAssessment, GuardrailService
from domain.services.llm_service import LLMService
from infrastructure.adapters.tools import tools


class LangGraphAgentService(AgentService):
    """LangGraph implementation of agent service."""

    def __init__(
        self,
        langfuse_config: dict | None = None,
        guardrail_service: GuardrailService | None = None,
        llm_service: LLMService | None = None,
    ):
        self._langfuse_config = langfuse_config or {}
        self._guardrail_service = guardrail_service
        self._llm_service = llm_service

    def _create_agent(self, agent_type: AgentType, model: str) -> any:
        """Create agent with specific model."""
        from langchain_openai import ChatOpenAI
        
        # Remove vendor prefix if present (format: vendor/model)
        processed_model = model.split("/", 1)[-1] if "/" in model else model
        
        # Create LLM with the specified model
        llm = ChatOpenAI(
            api_key=self._llm_service.api_key,
            base_url=self._llm_service.base_url,
            model=processed_model,
            temperature=0.7,
            streaming=True,
        )

        prompts = {
            AgentType.CUSTOMER_SERVICE: "You are a helpful customer service agent.",
            AgentType.RESEARCH: "You are a research assistant.",
            AgentType.GENERAL: "You are a helpful AI assistant.",
        }

        system_message = (
            "You are a professional customer service agent for AnyCompany. Your goal is to provide accurate, helpful responses while following company protocols.\n\n"
            "TOOL USAGE PRIORITY:\n"
            "1. ALWAYS start with retrieve_context to search our knowledge base for company information\n"
            "2. If knowledge base lacks sufficient details, supplement with web_search\n"
            "3. For ticket requests, use create_support_ticket with complete details\n"
            "4. Use get_support_tickets to check existing ticket status\n\n"
            "RESPONSE GUIDELINES:\n"
            "- Be concise but thorough in explanations\n"
            "- Always cite sources when using knowledge base or web information\n"
            "- For ticket creation, gather: subject, description, priority, and contact info\n"
            "- If you cannot find information, clearly state limitations and offer alternatives\n"
            "- Maintain a professional, empathetic tone throughout interactions"
        )

        return create_react_agent(llm, tools=tools, prompt=system_message)

    async def process_request(self, request: AgentRequest) -> AgentResponse:
        """Process request through appropriate agent."""
        logger.info(f"Processing request for user {request.user_id}, session {request.session_id}, agent type {request.agent_type}")
        
        # Check input guardrails if enabled
        if self._guardrail_service and request.messages:
            last_user_message = None
            for msg in reversed(request.messages):
                if msg.role == MessageRole.USER:
                    last_user_message = msg
                    break

            if last_user_message:
                input_result = await self._guardrail_service.check_input(
                    last_user_message
                )
                if input_result.assessment == GuardrailAssessment.BLOCKED:
                    return AgentResponse(
                        content=input_result.message,
                        agent_type=request.agent_type,
                        tools_used=[],
                        metadata={
                            "blocked_categories": ",".join(
                                input_result.blocked_categories
                            )
                        },
                    )

        agent = self._create_agent(request.agent_type, request.model)

        # Convert domain messages to LangChain format
        lc_messages = []
        for msg in request.messages:
            if msg.role == MessageRole.USER:
                lc_messages.append(HumanMessage(content=msg.content))
            elif msg.role == MessageRole.ASSISTANT:
                lc_messages.append(AIMessage(content=msg.content))

        # Create config with Langfuse callback if enabled
        callbacks = []
        trace_id = None

        if self._langfuse_config.get("enabled"):
            os.environ["LANGFUSE_SECRET_KEY"] = self._langfuse_config.get("secret_key")
            os.environ["LANGFUSE_PUBLIC_KEY"] = self._langfuse_config.get("public_key")
            os.environ["LANGFUSE_HOST"] = self._langfuse_config.get("host")
            
            langfuse_handler = CallbackHandler()
            callbacks.append(langfuse_handler)
            trace_id = str(f"{request.user_id}_{request.session_id}")

        config = RunnableConfig(
            configurable={
                "thread_id": f"{request.user_id}_{request.session_id}",
                "user_id": request.user_id,
            },
            callbacks=callbacks,
        )

        # Invoke agent
        logger.debug(f"Invoking agent with {len(lc_messages)} messages")
        response = await agent.ainvoke({"messages": lc_messages}, config=config)
        logger.debug(f"Agent response contains {len(response['messages'])} messages")
        # Extract response
        last_message = response["messages"][-1]
        tools_used = []

        # Check all messages for tool usage

        message_types = []
        for msg in response["messages"]:
            message_types.append(type(msg).__name__)
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls"):
                if msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        tools_used.append(tool_call["name"])
        # Remove duplicates
        tools_used = list(set(tools_used))
        logger.info(f"Agent completed. Tools used: {tools_used}")

        # Check output guardrails if enabled
        if self._guardrail_service:
            output_message = Message.create_assistant_message(last_message.content)
            output_result = await self._guardrail_service.check_output(output_message)
            if output_result.assessment == GuardrailAssessment.BLOCKED:
                return AgentResponse(
                    content=output_result.message,
                    agent_type=request.agent_type,
                    tools_used=tools_used,
                    metadata={
                        "blocked_categories": ",".join(output_result.blocked_categories)
                    },
                )

        # Add trace metadata
        metadata = {
            "model": request.model,
            "agent_type": request.agent_type.value,
            "trace_id": trace_id,
            "debug_message_count": len(response["messages"]),
            "debug_message_types": message_types,
            "debug_tools_found": len(tools_used) > 0,
        }

        logger.info(f"Returning response for session {request.session_id}")
        return AgentResponse(
            content=last_message.content,
            agent_type=request.agent_type,
            tools_used=tools_used,
            metadata=metadata,
        )

    async def stream_response(self, request: AgentRequest):
        """Stream response from agent."""
        agent = self._create_agent(request.agent_type, request.model)

        # Convert domain messages to LangChain format
        lc_messages = []
        for msg in request.messages:
            if msg.role == MessageRole.USER:
                lc_messages.append(HumanMessage(content=msg.content))
            elif msg.role == MessageRole.ASSISTANT:
                lc_messages.append(AIMessage(content=msg.content))

        # Create config
        config = RunnableConfig(
            configurable={
                "thread_id": f"{request.user_id}_{request.session_id}",
                "user_id": request.user_id,
            }
        )

        # Stream agent response
        async for chunk in agent.astream({"messages": lc_messages}, config=config):
            if "messages" in chunk:
                for message in chunk["messages"]:
                    if hasattr(message, "content") and message.content:
                        yield message.content
