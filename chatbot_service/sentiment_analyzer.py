import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from typing import List
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from shared.config import Config

# Download VADER lexicon if not already present
try:
    nltk.data.find('vader_lexicon')
except LookupError:
    nltk.download('vader_lexicon')

class SentimentAnalyzer:
    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()
    
    def analyze_conversation(self, messages: List[str]) -> str:
        """Analyze sentiment from recent conversation messages"""
        if not messages:
            return "default"
        
        # Get recent messages for analysis
        recent_messages = messages[-Config.SENTIMENT_WINDOW_SIZE:]
        
        # Calculate average sentiment
        scores = []
        for message in recent_messages:
            if "::" in message:
                _, content = message.split("::", 1)
                score = self.analyzer.polarity_scores(content)
                scores.append(score['compound'])
        
        if not scores:
            return "default"
        
        avg_score = sum(scores) / len(scores)
        
        # Map scores to emotions
        if avg_score >= 0.5:
            return "cheerful"
        elif avg_score >= 0.3:
            return "excited"
        elif avg_score >= 0.1:
            return "friendly"
        elif avg_score > -0.1:
            return "default"
        elif avg_score > -0.3:
            return "sad"
        elif avg_score > -0.5:
            return "angry"
        else:
            return "terrified"
    
    def analyze_single_message(self, message: str) -> dict:
        """Analyze sentiment of a single message"""
        scores = self.analyzer.polarity_scores(message)
        return {
            "positive": scores['pos'],
            "neutral": scores['neu'],
            "negative": scores['neg'],
            "compound": scores['compound']
        }
