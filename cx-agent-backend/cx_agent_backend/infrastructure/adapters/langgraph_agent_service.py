"""LangGraph implementation of agent service."""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
import os
import logging
from langgraph.prebuilt import create_react_agent
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
from bedrock_agentcore.memory import MemoryClient

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
from cx_agent_backend.infrastructure.aws.parameter_store_reader import AWSParameterStoreReader


parameter_store_reader = AWSParameterStoreReader()


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

    def _create_agent(self, agent_type: AgentType, model: str, memory_id: str = None, actor_id: str = None, session_id: str = None) -> any:
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
        
        # Add memory tool if memory parameters provided
        memory_tools = []
        memory_client = None
        if memory_id and actor_id and session_id:
            memory_client = MemoryClient(region_name=os.getenv('AWS_REGION', 'us-east-1'))
            
            @tool
            def get_conversation_history():
                """Retrieve recent conversation history when needed for context"""
                try:
                    events = memory_client.list_events(
                        memory_id=memory_id,
                        actor_id=actor_id,
                        session_id=session_id,
                        max_results=10
                    )
                    return f"Recent conversation history: {events}"
                except Exception as e:
                    return f"Could not retrieve history: {str(e)}"
            
            memory_tools = [get_conversation_history]

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

        # Combine existing tools with memory tools
        all_tools = tools + memory_tools
        
        return create_react_agent(llm, tools=all_tools, prompt=system_message), memory_client

    async def process_request(self, request: AgentRequest) -> AgentResponse:
        """Process request through appropriate agent."""
        logger.info(
            "Processing request for user %s, session %s, agent type %s",
            request.user_id,
            request.session_id,
            request.agent_type,
        )
        
        # Use trace_id from request if provided, otherwise create one
        langfuse = None
        predefined_trace_id = getattr(request, 'trace_id', None)
        if self._langfuse_config.get("enabled"):
            langfuse = get_client()
            if not predefined_trace_id:
                predefined_trace_id = Langfuse.create_trace_id(seed=request.session_id)
        
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

        # Get memory parameters from environment or request
        stm_memory_id = parameter_store_reader.get_parameter("/amazon/ac_stm_memory_id")
        if not stm_memory_id:
            logger.error("STM Memory ID not configured in parameter store")
            raise ValueError("STM Memory ID not configured")

        actor_id = request.user_id
        session_id = request.session_id
        
        agent, memory_client = self._create_agent(request.agent_type, request.model, stm_memory_id, actor_id, session_id)

        # Convert domain messages to LangChain format
        lc_messages = []
        for msg in request.messages:
            if msg.role == MessageRole.USER:
                lc_messages.append(HumanMessage(content=msg.content))
            elif msg.role == MessageRole.ASSISTANT:
                lc_messages.append(AIMessage(content=msg.content))

        # Create config with Langfuse callback if enabled
        trace_id = None
        response = None

        if self._langfuse_config.get("enabled"):
            os.environ["LANGFUSE_SECRET_KEY"] = self._langfuse_config.get("secret_key")
            os.environ["LANGFUSE_PUBLIC_KEY"] = self._langfuse_config.get("public_key")
            os.environ["LANGFUSE_HOST"] = self._langfuse_config.get("host")
            
            trace_id = predefined_trace_id
            
            langfuse_handler = CallbackHandler()
            
            with langfuse.start_as_current_span(
                name="langchain-request",
                trace_context={"trace_id": predefined_trace_id}
            ) as span:
                span.update_trace(
                    user_id=request.user_id,
                    input={"messages": [msg.content for msg in request.messages]}
                )
                
                config = RunnableConfig(
                    configurable={
                        "thread_id": f"{request.session_id}",
                        "user_id": request.user_id,
                    },
                    callbacks=[langfuse_handler],
                )
                
                # Invoke agent
                logger.debug("Invoking agent with %s messages", len(lc_messages))
                response = await agent.ainvoke({"messages": lc_messages}, config=config)
                
                # Save conversation to memory if available
                if memory_client and lc_messages:
                    try:
                        last_user_msg = next((msg.content for msg in reversed(lc_messages) if isinstance(msg, HumanMessage)), None)
                        assistant_response = response["messages"][-1].content if response["messages"] else ""
                        
                        if last_user_msg and assistant_response:
                            memory_client.create_event(
                                memory_id=stm_memory_id,
                                actor_id=actor_id,
                                session_id=session_id,
                                messages=[(last_user_msg, "USER"), (assistant_response, "ASSISTANT")]
                            )
                    except Exception as e:
                        logger.warning(f"Failed to save conversation to memory: {e}")
                
                span.update_trace(output={"response": response["messages"][-1].content if response["messages"] else ""})
        else:
            config = RunnableConfig(
                configurable={
                    "thread_id": f"{request.session_id}",
                    "user_id": request.user_id,
                },
            )
            
            # Invoke agent
            logger.debug("Invoking agent with %s messages", len(lc_messages))
            response = await agent.ainvoke({"messages": lc_messages}, config=config)
            
            # Save conversation to memory if available
            if memory_client and lc_messages:
                try:
                    last_user_msg = next((msg.content for msg in reversed(lc_messages) if isinstance(msg, HumanMessage)), None)
                    assistant_response = response["messages"][-1].content if response["messages"] else ""
                    
                    if last_user_msg and assistant_response:
                        memory_client.create_event(
                            memory_id=stm_memory_id,
                            actor_id=actor_id,
                            session_id=session_id,
                            messages=[(last_user_msg, "USER"), (assistant_response, "ASSISTANT")]
                        )
                except Exception as e:
                    logger.warning(f"Failed to save conversation to memory: {e}")
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

        # Add trace metadata
        metadata = {
            "model": request.model,
            "agent_type": request.agent_type.value,
            "trace_id": trace_id,
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
        agent, _ = self._create_agent(request.agent_type, request.model)

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
