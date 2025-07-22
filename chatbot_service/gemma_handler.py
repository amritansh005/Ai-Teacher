import requests
from typing import List
from shared.config import Config
import re

class GemmaHandler:
    def __init__(self):
        # Inform user of integration
        print("Using Ollama Gemma3n:e2b model via Ollama API (http://localhost:11434)")
        # You may add a configuration check or connection test here if desired

    def build_teacher_prompt(self, conversation_history: List[str], user_input: str) -> str:
        """Build a dynamic teacher prompt based on conversation context"""

        context_messages = []
        for msg in conversation_history[-6:]:  # Last 6 messages for context
            if "::" in msg:
                role, content = msg.split("::", 1)
                context_messages.append(f"{role.capitalize()}: {content}")

        system_prompt = """You are an AI Teacher, a helpful and knowledgeable educational assistant. Your role is to:

1. Explain concepts clearly and patiently
2. Adapt your explanations to the student's level of understanding  
3. Ask clarifying questions when needed
4. Provide examples to illustrate points
5. Encourage learning and critical thinking
6. Handle interruptions gracefully and continue from where you left off
7. Be supportive and maintain a positive learning environment

Guidelines:
- Keep responses concise but comprehensive
- Use simple language for complex topics
- Encourage questions and curiosity
- If interrupted, acknowledge the interruption and address it before continuing
- Always be patient and supportive

Previous conversation context:
"""
        if context_messages:
            system_prompt += "\n".join(context_messages)
        else:
            system_prompt += "This is the start of a new learning session."

        full_prompt = f"{system_prompt}\n\nStudent: {user_input}\nAI Teacher:"
        return full_prompt

    def generate_response(self, conversation_history: List[str], user_input: str) -> str:
        """Generate AI teacher response using Ollama Gemma3n:e2b"""
        try:
            prompt = self.build_teacher_prompt(conversation_history, user_input)
            # Call Ollama's API with the prompt
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": "gemma3n:e2b", "prompt": prompt},
                timeout=90
            )
            response.raise_for_status()
            # Ollama may return multiple JSON objects (JSONL), so parse line by line
            print("Ollama raw response:")
            print(response.text)
            lines = [line for line in response.text.splitlines() if line.strip()]
            ai_response_parts = []
            for line in lines:
                try:
                    data = __import__("json").loads(line)
                    print("Parsed Ollama line:", data)
                    if "response" in data and data["response"]:
                        ai_response_parts.append(data["response"])
                except Exception as e:
                    print("Error parsing Ollama line:", e)
                    continue
            ai_response = "".join(ai_response_parts).strip()
            # Clean up the response
            ai_response = self.clean_response(ai_response)
            print("Final cleaned AI response:", ai_response)
            return ai_response

        except Exception as e:
            print(f"Error generating response with Ollama: {e}")
            return "I apologize, but I encountered an error processing your question. Could you please try again?"

    def clean_response(self, response: str) -> str:
        """Clean and format the AI response, but never return empty if model output is non-empty"""
        response = response.strip()
        # Remove leading role label if present
        response = re.sub(r'^(AI Teacher:|Teacher:|Assistant:)\s*', '', response, flags=re.IGNORECASE)
        # If "Student:" appears, cut off at that point, but only if it's not at the very start
        idx = response.find("Student:")
        if idx > 10:
            response = response[:idx].strip()
        # Collapse multiple spaces
        response = re.sub(r'\s+', ' ', response)
        # If cleaning results in empty, fall back to original
        if not response:
            response = response.strip()
        return response
