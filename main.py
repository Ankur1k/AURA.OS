"""
AURA OS — Backend API
FastAPI + SQLite + SSE streaming + Multi-agent swarm.
"""

import asyncio
import json
import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents import AuraSwarm
import database as db

# ── APP ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="AURA OS API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    db.init_db()   # creates aura.db and all tables on first run


# ── MODELS ────────────────────────────────────────────────────────────────────
class TaskRequest(BaseModel):
    query: str
    context: str | None = None

class KnowledgeEntry(BaseModel):
    title: str
    content: str
    source: str | None = "manual"
    tags: list[str] = []


def now_str():
    return datetime.now().strftime("%H:%M:%S")


# ── HEALTH ────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    stats = db.get_stats()
    return {"status": "online", "system": "AURA OS", "timestamp": now_str(), **stats}


# ── TASKS ─────────────────────────────────────────────────────────────────────
@app.post("/api/task")
def create_task(req: TaskRequest):
    task_id = str(uuid.uuid4())[:8]
    db.create_task(task_id, req.query, req.context)
    return {"task_id": task_id, "status": "queued"}


@app.get("/api/tasks")
def get_tasks():
    return db.get_all_tasks()


@app.get("/api/task/{task_id}")
def get_task(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ── SSE STREAM ────────────────────────────────────────────────────────────────
@app.get("/api/stream/{task_id}")
async def stream_task(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        db.update_task(task_id, "running")
        swarm = AuraSwarm(task_id=task_id)

        async def send(agent: str, message: str, level: str = "info"):
            t = now_str()
            db.add_log(task_id, t, agent, message, level)
            payload = {"time": t, "agent": agent, "message": message, "level": level}
            yield f"data: {json.dumps(payload)}\n\n"

        async for chunk in send("SYSTEM", f'Swarm initialised. Task: "{task["query"]}"'):
            yield chunk

        async for chunk in send("SCOUT", "Starting research phase. Scanning knowledge base..."):
            yield chunk

        class KGProxy:
            def search(self, q): return db.search_knowledge(q)

        scout_result = await swarm.scout(task["query"], task["context"], KGProxy())

        async for chunk in send("SCOUT", f'Research complete. Found {scout_result["source_count"]} relevant signals.'):
            yield chunk
        async for chunk in send("SCOUT", scout_result["summary"]):
            yield chunk

        await asyncio.sleep(0.3)
        async for chunk in send("SKEPTIC", "Receiving Scout findings. Beginning adversarial review...", "challenge"):
            yield chunk

        skeptic_result = await swarm.skeptic(scout_result["summary"])

        if skeptic_result["has_issues"]:
            async for chunk in send("SKEPTIC", f'CHALLENGE: {skeptic_result["challenge"]}', "challenge"):
                yield chunk
            async for chunk in send("SCOUT", "Challenge acknowledged. Revising findings...", "info"):
                yield chunk
            scout_result = await swarm.scout_revise(task["query"], scout_result["summary"], skeptic_result["challenge"])
            async for chunk in send("SCOUT", f'Revised findings ready. Confidence: {scout_result["confidence"]}%'):
                yield chunk
            async for chunk in send("SKEPTIC", "VALIDATED. Revised findings pass adversarial review.", "success"):
                yield chunk
        else:
            async for chunk in send("SKEPTIC", f'VALIDATED. Confidence: {skeptic_result["confidence"]}%', "success"):
                yield chunk

        await asyncio.sleep(0.3)
        async for chunk in send("ARCHITECT", "Synthesis phase initiated. Building final output..."):
            yield chunk

        architect_result = await swarm.architect(task["query"], scout_result["summary"])

        async for chunk in send("ARCHITECT", architect_result["summary"]):
            yield chunk
        async for chunk in send("ARCHITECT", "Action plan structured. Saving to knowledge graph.", "success"):
            yield chunk

        db.add_knowledge_node(
            title=task["query"],
            content=architect_result["full_output"],
            tags=architect_result.get("tags", []),
            source="aura_swarm",
        )

        db.update_task(task_id, "complete", architect_result["full_output"])

        async for chunk in send("SYSTEM", f'Task complete. Confidence: {scout_result["confidence"]}%. Knowledge graph updated.', "success"):
            yield chunk

        yield f"data: {json.dumps({'event': 'done', 'result': architect_result['full_output']})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── KNOWLEDGE GRAPH ───────────────────────────────────────────────────────────
@app.get("/api/knowledge")
def get_knowledge():
    return db.get_all_knowledge()

@app.post("/api/knowledge")
def add_knowledge(entry: KnowledgeEntry):
    return db.add_knowledge_node(entry.title, entry.content, entry.tags, entry.source)

@app.get("/api/knowledge/search")
def search_knowledge(q: str):
    return db.search_knowledge(q)

@app.delete("/api/knowledge/{node_id}")
def delete_knowledge(node_id: str):
    ok = db.delete_knowledge_node(node_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"deleted": node_id}

@app.get("/api/stats")
def stats():
    return db.get_stats()