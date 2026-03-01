import re
import os
import httpx
import random
import asyncio
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def parse_confidence(text: str, default: int = 85) -> int:
    """Extracts confidence score from raw text blocks."""
    match = re.search(r"CONFIDENCE:\s*(\d+)", text)
    if match:
        return min(100, max(0, int(match.group(1))))
    return default

def parse_section(text: str, key: str) -> str:
    """Extracts a specific section (e.g., SUMMARY) from formatted text."""
    pattern = rf"{key}:\s*(.*?)(?=\n[A-Z ]+:|$)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()

# ─── SWARM CLASS ───────────────────────────────────────────────────────────────

class AuraSwarm:
    """
    Orchestrates Scout -> Skeptic -> Architect.
    Uses OpenWeatherMap for data and standard Python for logic.
    """

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.weather_api_key = os.getenv("OPENWEATHER_API_KEY")
        self.base_url = "https://api.openweathermap.org/data/2.5/weather"

    async def scout(self, query: str, context=None, knowledge_graph=None) -> dict:
        """
        SCOUT: Fetches real-time weather data based on the query (City).
        """
        params = {
            "q": query,
            "appid": self.weather_api_key,
            "units": "metric"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
                
                temp = data["main"]["temp"]
                desc = data["weather"][0]["description"]
                humidity = data["main"]["humidity"]
                city = data["name"]

                summary = f"Weather in {city}: {temp}°C, {desc.capitalize()}."
                
                # Formatted raw text to keep your frontend/parsing happy
                raw_text = f"""
SUMMARY: {summary}
KEY FINDINGS:
- Temperature: {temp}°C
- Humidity: {humidity}%
- Conditions: {desc}
SOURCES: OpenWeatherMap
CONFIDENCE: 100
"""
                
                return {
                    "raw": raw_text,
                    "summary": summary,
                    "findings": f"Temp: {temp}°C, Humidity: {humidity}%",
                    "confidence": 100,
                    "source_count": 1
                }
            except Exception as e:
                # Fallback if city is not found or API fails
                err_msg = f"Data retrieval failed for '{query}'."
                return {
                    "raw": f"SUMMARY: {err_msg}\nCONFIDENCE: 0",
                    "summary": err_msg,
                    "findings": "N/A",
                    "confidence": 0,
                    "source_count": 0
                }

    async def skeptic(self, scout_summary: str) -> dict:
        """
        SKEPTIC: Accepts a STRING (scout_result['summary']) from main.py.
        """
        # We check the string content since main.py only passes the summary string
        is_valid = "failed" not in scout_summary.lower() and "error" not in scout_summary.lower()
        
        raw_text = f"""
VERDICT: {"VALIDATED" if is_valid else "CHALLENGED"}
ISSUES: {"None" if is_valid else "The scout could not find data for this location."}
RECOMMENDATION: {"Proceed" if is_valid else "Verify the city name and try again."}
CONFIDENCE: {100 if is_valid else 0}
"""

        return {
            "raw": raw_text,
            "verdict": "VALIDATED" if is_valid else "CHALLENGED",
            "has_issues": not is_valid,
            "challenge": "Location Error" if not is_valid else "",
            "recommendation": "Check spelling" if not is_valid else "Proceed",
            "confidence": 100 if is_valid else 0,
        }

    async def architect(self, query: str, validated_summary: str) -> dict:
        """
        ARCHITECT: Accepts a STRING (scout_result['summary']) from main.py.
        """
        # Create a formatted report based on the weather data
        full_output = f"""## Weather Intelligence: {query}

### Summary
{validated_summary}

### Action Plan
1. Prepare for conditions: {validated_summary.split(':')[-1].strip()}.
2. Monitor real-time shifts via AURA OS dashboard.
3. Update local environment logs.

### Tags
weather, {query.lower()}, aura-swarm
"""
        return {
            "raw": "Architect Synthesis Complete",
            "summary": validated_summary,
            "full_output": full_output,
            "action_plan": "1. Check gear\n2. Monitor updates\n3. Execute",
            "tags": ["weather", query.lower()],
        }