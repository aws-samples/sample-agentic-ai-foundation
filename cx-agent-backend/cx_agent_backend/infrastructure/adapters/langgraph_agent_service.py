"""LangGraph implementation of agent service."""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
import os
import logging
import base64
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger(__name__)

from cx_agent_backend.domain.entities.conversation import Message, MessageRole
from cx_agent_backend.domain.services.agent_service import (
    AgentRequest,
    AgentResponse,
    AgentService,
    AgentType,
)
from cx_agent_backend.domain.services.guardrail_service import GuardrailAssessment, GuardrailService
from cx_agent_backend.domain.services.llm_service import LLMService
from cx_agent_backend.infrastructure.adapters.tools import tools


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

    async def _setup_langfuse_otlp(self):
        """Setup Langfuse OTLP configuration."""
        logger.info("[LANGFUSE] Starting OTLP setup")
        
        # Disable ADOT to avoid conflicts
        os.environ["DISABLE_ADOT_OBSERVABILITY"] = "True"
        logger.info("[LANGFUSE] Disabled ADOT observability")
        
        # Clear conflicting environment variables
        for k in [
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
            "AGENT_OBSERVABILITY_ENABLED", 
            "OTEL_PYTHON_DISTRO",
            "OTEL_RESOURCE_ATTRIBUTES",
            "OTEL_PYTHON_CONFIGURATOR",
            "OTEL_PYTHON_EXCLUDED_URLS",
        ]:
            os.environ.pop(k, None)
        
        # Configure Langfuse OTLP
        public_key = self._langfuse_config.get("public_key")
        secret_key = self._langfuse_config.get("secret_key")
        host = self._langfuse_config.get("host")
        
        logger.info(f"[LANGFUSE] Config - host: {host}, public_key: {public_key[:10] if public_key else None}..., secret_key: {'***' if secret_key else None}")
        
        if not all([public_key, secret_key, host]):
            logger.error(f"[LANGFUSE] Missing config - host: {host}, public_key: {bool(public_key)}, secret_key: {bool(secret_key)}")
            return
        
        auth_token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        otlp_endpoint = host + "/api/public/otel"
        
        # Set Langfuse environment variables (like Strands example)
        os.environ["LANGFUSE_PUBLIC_KEY"] = public_key
        os.environ["LANGFUSE_SECRET_KEY"] = secret_key
        os.environ["LANGFUSE_HOST"] = host
        
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = otlp_endpoint
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {auth_token}"
        
        # Disable LangChain tracing to avoid LangSmith warnings
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        
        # Setup OpenTelemetry exporter (equivalent to StrandsTelemetry)
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            
            trace.set_tracer_provider(TracerProvider())
            otlp_exporter = OTLPSpanExporter(
                endpoint=otlp_endpoint + "/v1/traces",
                headers={"Authorization": f"Basic {auth_token}"}
            )
            span_processor = BatchSpanProcessor(otlp_exporter)
            trace.get_tracer_provider().add_span_processor(span_processor)
            
            logger.info("[LANGFUSE] OpenTelemetry exporter configured")
        except ImportError:
            logger.warning("[LANGFUSE] OpenTelemetry dependencies not found, install: opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp")
        
        logger.info(f"[LANGFUSE] OTLP configured - endpoint: {otlp_endpoint}")
        logger.info(f"[LANGFUSE] LangChain tracing enabled")

    async def process_request(self, request: AgentRequest) -> AgentResponse:
        """Process request through appropriate agent."""
        logger.info(
            "Processing request for user %s, session %s, agent type %s",
            request.user_id,
            request.session_id,
            request.agent_type,
        )
        
        # Setup OTLP instead of callback
        langfuse_enabled = self._langfuse_config.get("enabled")
        logger.info(f"[LANGFUSE] Langfuse enabled: {langfuse_enabled}")
        
        if langfuse_enabled:
            await self._setup_langfuse_otlp()
        else:
            logger.info("[LANGFUSE] Langfuse disabled, skipping OTLP setup")
        
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

        # Simplified config without callbacks - tracing happens automatically via OTLP
        config = RunnableConfig(
            configurable={
                "thread_id": f"{request.session_id}",
                "user_id": request.user_id,
            },
        )
        
        # Invoke agent
        logger.info(f"[LANGFUSE] Invoking agent with {len(lc_messages)} messages, session: {request.session_id}")
        logger.info(f"[LANGFUSE] OTEL env vars - endpoint: {os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')}, tracing: {os.environ.get('LANGCHAIN_TRACING_V2')}")
        
        response = await agent.ainvoke({"messages": lc_messages}, config=config)
        
        logger.info(f"[LANGFUSE] Agent response received, messages count: {len(response.get('messages', []))}")
        
        # Flush Langfuse traces
        if langfuse_enabled:
            try:
                from langfuse import Langfuse
                langfuse_client = Langfuse()
                langfuse_client.flush()
                logger.info("[LANGFUSE] Traces flushed")
            except Exception as e:
                logger.warning(f"[LANGFUSE] Failed to flush traces: {e}")
        # Extract response
        last_message = response["messages"][-1]
        tools_used = []
        citations = []
        knowledge_base_id = None

        # Check all messages for tool usage and extract citations
        import json
        message_types = []
        for msg in response["messages"]:
            message_types.append(type(msg).__name__)
            
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls"):
                if msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        tools_used.append(tool_call["name"])
            
            # Extract citations from ToolMessage responses
            from langchain_core.messages import ToolMessage
            if isinstance(msg, ToolMessage):
                try:
                    # Parse tool response content
                    if isinstance(msg.content, str):
                        tool_response = json.loads(msg.content)
                        if "citations" in tool_response:
                            citations.extend(tool_response["citations"])
                        if "knowledge_base_id" in tool_response:
                            knowledge_base_id = tool_response["knowledge_base_id"]
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass
        
        # Remove duplicates
        tools_used = list(set(tools_used))

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

        # Add metadata
        metadata = {
            "model": request.model,
            "agent_type": request.agent_type.value,
        }
        
        # Add citations to metadata if available
        if citations:
            metadata["citations"] = citations
        if knowledge_base_id:
            metadata["knowledge_base_id"] = knowledge_base_id
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
                "thread_id": f"{request.session_id}",
                "user_id": request.user_id,
            }
        )

        # Stream agent response
        async for chunk in agent.astream({"messages": lc_messages}, config=config):
            if "messages" in chunk:
                for message in chunk["messages"]:
                    if hasattr(message, "content") and message.content:
                        yield message.content
