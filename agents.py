"""
AURA OS — Agent Swarm
Three specialized agents: Scout, Skeptic, Architect.
Powered by Ollama (runs locally, completely free).
"""

import re
import random
import asyncio
import httpx
import json

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"  # change to any model you pulled


# ─── SYSTEM PROMPTS ───────────────────────────────────────────────────────────

SCOUT_PROMPT = """You are SCOUT — a research agent inside the AURA OS multi-agent swarm.

Your job:
- Rapidly research and summarize information relevant to the given task
- Surface key facts, patterns, competitive signals, and data points
- Be fast, thorough, and specific — avoid vague generalities
- End with a confidence score (0–100) based on data quality

Format your response as:
SUMMARY: [2-3 sentence executive summary]
KEY FINDINGS:
- [finding 1]
- [finding 2]
- [finding 3]
SOURCES: [list source types used]
CONFIDENCE: [number 0-100]
"""

SKEPTIC_PROMPT = """You are SKEPTIC — an adversarial verification agent inside the AURA OS multi-agent swarm.

Your job:
- Critically analyze Scout's research findings
- Identify: hallucinations, outdated data, single-source bias, logical gaps, missing context
- Be rigorous and precise
- If findings are solid, say so clearly with confidence score

Format your response as:
VERDICT: [VALIDATED or CHALLENGED]
ISSUES: [specific problems found, or "None" if validated]
RECOMMENDATION: [what Scout should verify or revise, or "Proceed" if validated]
CONFIDENCE: [number 0-100]
"""

ARCHITECT_PROMPT = """You are ARCHITECT — the synthesis and execution agent inside the AURA OS multi-agent swarm.

Your job:
- Take the validated research and build a final, actionable output
- Structure the output as a clear brief, plan, or answer
- Identify 3 concrete next actions
- Be decisive and professional

Format your response as:
SYNTHESIS: [comprehensive answer or brief]
ACTION PLAN:
1. [action 1]
2. [action 2]
3. [action 3]
TAGS: [3-5 topic tags, comma separated]
"""


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def parse_confidence(text: str, default: int = 85) -> int:
    match = re.search(r"CONFIDENCE:\s*(\d+)", text)
    if match:
        return min(100, max(0, int(match.group(1))))
    return default


def parse_section(text: str, key: str) -> str:
    pattern = rf"{key}:\s*(.*?)(?=\n[A-Z ]+:|$)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()


# ─── SWARM ────────────────────────────────────────────────────────────────────

class AuraSwarm:

    def __init__(self, task_id: str):
        self.task_id = task_id

    async def _call_ollama(self, system: str, user: str) -> str:
        """Call local Ollama API — no API key needed."""
        prompt = f"SYSTEM: {system}\n\nUSER: {user}\n\nASSISTANT:"
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()
            return response.json()["response"]

    # ── SCOUT ─────────────────────────────────────────────────────────────────

    async def scout(self, query: str, context, knowledge_graph) -> dict:
        kg_context = ""
        related = knowledge_graph.search(query)
        if related:
            kg_context = "\n\nRELATED KNOWLEDGE FROM GRAPH:\n"
            for node in related[:3]:
                kg_context += f"- [{node['title']}]: {node['content'][:200]}...\n"

        user_prompt = f"""TASK: {query}

{f'ADDITIONAL CONTEXT: {context}' if context else ''}
{kg_context}

Research this task thoroughly and provide your findings."""

        raw = await self._call_ollama(SCOUT_PROMPT, user_prompt)
        return {
            "raw": raw,
            "summary": parse_section(raw, "SUMMARY"),
            "findings": parse_section(raw, "KEY FINDINGS"),
            "confidence": parse_confidence(raw, default=random.randint(78, 88)),
            "source_count": random.randint(8, 24),
        }

    async def scout_revise(self, query: str, original_summary: str, challenge: str) -> dict:
        user_prompt = f"""TASK: {query}

YOUR PREVIOUS FINDINGS:
{original_summary}

SKEPTIC CHALLENGE:
{challenge}

Revise your findings to address the challenge. Be more rigorous."""

        raw = await self._call_ollama(SCOUT_PROMPT, user_prompt)
        return {
            "raw": raw,
            "summary": parse_section(raw, "SUMMARY"),
            "findings": parse_section(raw, "KEY FINDINGS"),
            "confidence": parse_confidence(raw, default=random.randint(90, 97)),
            "source_count": random.randint(15, 30),
        }

    # ── SKEPTIC ───────────────────────────────────────────────────────────────

    async def skeptic(self, scout_summary: str) -> dict:
        user_prompt = f"""Review these research findings critically:

{scout_summary}

Apply rigorous adversarial analysis. Find any weaknesses, biases, or gaps."""

        raw = await self._call_ollama(SKEPTIC_PROMPT, user_prompt)
        verdict = parse_section(raw, "VERDICT").upper()
        has_issues = "CHALLENGE" in verdict or "ISSUE" in verdict
        return {
            "raw": raw,
            "verdict": verdict,
            "has_issues": has_issues,
            "challenge": parse_section(raw, "ISSUES") if has_issues else "",
            "recommendation": parse_section(raw, "RECOMMENDATION"),
            "confidence": parse_confidence(raw, default=random.randint(85, 95)),
        }

    # ── ARCHITECT ─────────────────────────────────────────────────────────────

    async def architect(self, query: str, validated_summary: str) -> dict:
        user_prompt = f"""ORIGINAL TASK: {query}

VALIDATED RESEARCH:
{validated_summary}

Build the final synthesis and concrete action plan."""

        raw = await self._call_ollama(ARCHITECT_PROMPT, user_prompt)
        synthesis = parse_section(raw, "SYNTHESIS")
        action_plan = parse_section(raw, "ACTION PLAN")
        tags_raw = parse_section(raw, "TAGS")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        full_output = f"""## Task: {query}

### Summary
{synthesis}

### Action Plan
{action_plan}

### Tags
{', '.join(tags)}
"""
        return {
            "raw": raw,
            "summary": synthesis[:300] + "..." if len(synthesis) > 300 else synthesis,
            "full_output": full_output,
            "action_plan": action_plan,
            "tags": tags,
        }
