"""Conversation API client."""

from typing import Dict, Optional

import requests
import streamlit as st


class ConversationClient:
    """Client for conversation API."""

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.session = requests.Session()

    def create_conversation(self, user_id: str) -> Optional[str]:
        """Create a new conversation."""
        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/", json={"user_id": user_id}
            )
            response.raise_for_status()
            return response.json()["id"]
        except Exception as e:
            st.error(f"Failed to create conversation: {e}")
            return None

    def send_message(
        self, conversation_id: str, content: str, model: str, user_id: str = None, feedback: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Send a message to the conversation with optional feedback."""
        try:
            payload = {"prompt": content, "conversation_id": conversation_id, "model": model}
            if user_id:
                payload["user_id"] = user_id
            if feedback:
                payload["feedback"] = feedback
            
            response = self.session.post(
                f"{self.base_url}/api/v1/invocations",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Failed to send message: {e}")
            return None

    def get_conversation(self, conversation_id: str) -> Optional[Dict]:
        """Get conversation details."""
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/{conversation_id}"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"Failed to get conversation: {e}")
            return None

    def submit_feedback(self, run_id: str, session_id: str, score: float, comment: str = "") -> bool:
        """Submit feedback for a message."""
        try:
            response = self.session.post(
                f"{self.base_url}/invocations",
                json={"input": {"feedback": {"run_id": run_id, "session_id": session_id, "score": score, "comment": comment}}},
                timeout=30
            )
            response.raise_for_status()
            return True
        except Exception as e:
            st.error(f"Failed to submit feedback: {e}")
            return False
