"""Chat components."""

import streamlit as st

from models.message import Message
from services.conversation_client import ConversationClient


def render_message(message: Message, client: ConversationClient = None):
    """Render a single message."""
    with st.chat_message(message.role):
        st.write(message.content)

        # Add feedback buttons for assistant messages
        if message.role == "assistant" and client:
            message_id = str(message.metadata.get("message_id", hash(message.content)))
            
            # Check if feedback already given
            feedback_key = f"feedback_given_{message_id}"
            if feedback_key not in st.session_state:
                st.session_state[feedback_key] = False
            
            if not st.session_state[feedback_key]:
                st.markdown("---")
                st.markdown("**Was this helpful?**")
                
                col1, col2, col3 = st.columns([2, 2, 6])
                
                with col1:
                    if st.button("👍 Helpful", key=f"up_{message_id}", use_container_width=True):
                        if client.submit_feedback(message_id, st.session_state.get("conversation_id", "default"), 1.0, ""):
                            st.session_state[feedback_key] = True
                            st.success("✓ Thank you for your feedback!")
                            st.rerun()
                
                with col2:
                    if st.button("👎 Not helpful", key=f"down_{message_id}", use_container_width=True):
                        with st.expander("📝 Tell us more (optional)", expanded=True):
                            feedback_text = st.text_area(
                                "How can we improve?",
                                key=f"text_{message_id}",
                                placeholder="Your feedback helps us improve...",
                                height=80
                            )
                            if st.button("📤 Submit Feedback", key=f"submit_{message_id}", type="primary"):
                                if client.submit_feedback(message_id, st.session_state.get("conversation_id", "default"), 0.0, feedback_text):
                                    st.session_state[feedback_key] = True
                                    st.success("✓ Thank you for your feedback!")
                                    st.rerun()
            else:
                st.markdown("<div style='color: #28a745; font-size: 0.9em;'>✓ Feedback submitted</div>", unsafe_allow_html=True)

        # Show tool calls if available
        if message.metadata and "tools_used" in message.metadata:
            tools_str = message.metadata["tools_used"]
            if tools_str:
                tools_used = [tool.strip() for tool in tools_str.split(",") if tool.strip()]
                if tools_used:
                    st.markdown("**🔧 Tools Used:**")
                    for tool in tools_used:
                        st.markdown(f"• `{tool}`")

        # Show metadata if available
        if message.metadata:
            with st.expander("Message Details", expanded=False):
                st.json(message.metadata)


def render_sidebar():
    """Render sidebar with configuration."""
    with st.sidebar:
        st.header("Configuration")

        # Model selection
        model = st.selectbox(
            "Model",
            options=[
                "bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "openai/gpt-4o-mini",
                "openai/gpt-4o",
                "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
                "bedrock/anthropic.claude-3-5-haiku-20241022-v1:0",
            ],
            index=0,
        )

        # User ID
        user_id = st.text_input("User ID", value=st.session_state.user_id)
        st.session_state.user_id = user_id

        # Conversation controls
        st.header("Conversation")

        if st.button("New Conversation", type="primary"):
            st.session_state.conversation_id = None
            st.session_state.messages = []
            st.rerun()

        if st.session_state.conversation_id:
            st.success(f"Active: {st.session_state.conversation_id[:8]}...")

        return model
