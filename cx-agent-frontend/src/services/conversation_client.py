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
        self, conversation_id: str, content: str, model: str
    ) -> Optional[Dict]:
        """Send a message to the conversation."""
        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/invocations",
                json={"prompt": content, "conversation_id": conversation_id, "model": model},
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
                f"{self.base_url}/api/v1/feedback",
                json={"run_id": run_id, "session_id": session_id, "score": score, "comment": comment},
                timeout=30
            )
            response.raise_for_status()
            return True
        except Exception as e:
            st.error(f"Failed to submit feedback: {e}")
            return False
