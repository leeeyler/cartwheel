"""Local browser workbench for HW1, using the unmodified course agent loop.

Run: uv run python -m server.workbench
Open: http://127.0.0.1:8011

This is a personal test harness with a demo-user selector. It binds to loopback
by default. In GitHub Codespaces use --host 0.0.0.0 and keep the forwarded port
private. The separate HW2 server and homework placeholders remain untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from agents import RunConfig, Runner, SQLiteSession
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agent import db
from agent.agent import DEFAULT_MODEL, build_agent, prompt_version
from agent.auth import AuthContext
from agent.config import REPO_ROOT, database_scope, db_path, policies_dir
from observability.instrument import load_env

MAX_TURNS = 12
STATIC_DIR = Path(__file__).with_name("workbench_static")
IDENTITIES = [
    {"role": "shopper", "user_id": 1, "store_id": None, "label": "Shopper 1"},
    {"role": "merchant", "user_id": 9002, "store_id": 2, "label": "Merchant 9002 · store 2"},
    {"role": "support", "user_id": 9501, "store_id": None, "label": "Support 9501"},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _parsed(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def collect_tool_calls(items: list[Any]) -> list[dict[str, Any]]:
    """Preserve the actual SDK tool requests and outputs, in invocation order."""
    outputs = {
        item.call_id: _parsed(item.output)
        for item in items
        if item.type == "tool_call_output_item" and item.call_id is not None
    }
    calls = []
    for item in items:
        if item.type != "tool_call_item":
            continue
        raw = item.raw_item
        arguments = raw.get("arguments") if isinstance(raw, dict) else getattr(raw, "arguments", None)
        calls.append({
            "name": item.tool_name,
            "arguments": _parsed(arguments),
            "result": outputs.get(item.call_id),
        })
    return calls


def model_configuration() -> dict[str, Any]:
    model = os.environ.get("CARTWHEEL_MODEL") or DEFAULT_MODEL
    if model.startswith("gpt-"):
        provider, variable = "OpenAI", "OPENAI_API_KEY"
    elif model.startswith(("claude-", "anthropic/")):
        provider, variable = "Anthropic", "ANTHROPIC_API_KEY"
    elif model.startswith(("glm-", "together_ai/")):
        provider, variable = "Together AI", "TOGETHER_API_KEY"
    else:
        return {"model": model, "provider": "Custom", "provider_configured": False,
                "key_variable": None,
                "message": "Select a course-supported model in CARTWHEEL_MODEL, then restart the server."}
    configured = bool(os.environ.get(variable, "").strip())
    return {"model": model, "provider": provider, "provider_configured": configured,
            "key_variable": variable,
            "message": ("Model credentials are configured. Your first message will test API access."
                        if configured else f"Add {variable} to your server's .env file or Codespaces secret, then restart the server.")}


def specification_requirements() -> list[dict[str, str]]:
    text = (REPO_ROOT / "SPEC.md").read_text(encoding="utf-8")
    rows: dict[str, str] = {}
    for match in re.finditer(r"\*\*([A-Z]+-\d+)\.\*\*\s*([^\n]+)", text):
        rows[match[1]] = match[2].strip()
    for line in text.splitlines():
        match = re.match(r"\|\s*(TOOL-\d+)\s*\|\s*`([^`]+)`\s*\|", line)
        if match:
            rows[match[1]] = match[2].replace("_", " ")
    return [{"id": key, "text": value} for key, value in rows.items()]


class NewConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["shopper", "merchant", "support"]
    user_id: int


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=12000)
    expected: str | None = Field(default=None, max_length=6000)


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected: str = Field(min_length=1, max_length=6000)
    requirement: str | None = None
    met_requirement: StrictBool
    problem_source: Literal["prompt", "tool", "specification"] | None

    @model_validator(mode="after")
    def check_assessment(self):
        if not self.expected.strip():
            raise ValueError("Describe the expected behavior before saving.")
        if self.met_requirement and self.problem_source is not None:
            raise ValueError("A passing conversation must have no problem source.")
        if not self.met_requirement and self.problem_source is None:
            raise ValueError("Select a problem source for a failing conversation.")
        return self


def create_app(state_dir: Path | None = None, records_path: Path | None = None) -> FastAPI:
    load_env()
    state = state_dir or Path(os.environ.get("CARTWHEEL_WORKBENCH_STATE", REPO_ROOT / ".workbench"))
    records = records_path or Path(os.environ.get("CARTWHEEL_HW1_RECORDS", REPO_ROOT / "hw1-session.jsonl"))
    locks: dict[str, asyncio.Lock] = {}
    record_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_app):
        load_env()
        yield

    app = FastAPI(title="Cartwheel · HW1 workbench", lifespan=lifespan)
    hosts = ["127.0.0.1", "localhost", "[::1]", "testserver"]
    if os.environ.get("CODESPACES") == "true":
        hosts += ["*.app.github.dev", "*.githubpreview.dev"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
            if urlsplit(origin).netloc != request.headers.get("host", ""):
                return JSONResponse({"detail": "Open the workbench directly to perform this action."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        return response

    def conversation_dir(identifier: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise HTTPException(404, "Conversation not found.")
        return state / "conversations" / identifier

    def read_conversation(identifier: str) -> dict[str, Any]:
        path = conversation_dir(identifier) / "conversation.json"
        if not path.is_file():
            raise HTTPException(404, "Conversation not found. Start a new conversation.")
        return json.loads(path.read_text(encoding="utf-8"))

    def count_records() -> int:
        if not records.exists():
            return 0
        return sum(bool(line.strip()) for line in records.read_text(encoding="utf-8").splitlines())

    def require_data():
        if not db_path().is_file() or not policies_dir().is_dir():
            raise HTTPException(503, "Generate the course data first: uv run python -m seed.generate")

    @app.get("/api/status")
    def status():
        config = model_configuration()
        data_ready = db_path().is_file() and policies_dir().is_dir()
        return {**config, "ready": config["provider_configured"] and data_ready,
                "data_ready": data_ready, "saved_count": count_records(),
                "identities": IDENTITIES, "requirements": specification_requirements(),
                "prompt_version": prompt_version(), "records_path": records.name,
                "message": config["message"] if data_ready else "Run uv run python -m seed.generate to create the sample shopping data."}

    @app.get("/api/spec", response_class=PlainTextResponse)
    def spec():
        return (REPO_ROOT / "SPEC.md").read_text(encoding="utf-8")

    @app.post("/api/conversations")
    async def new_conversation(body: NewConversation):
        require_data()
        if not any(row["role"] == body.role and row["user_id"] == body.user_id for row in IDENTITIES):
            raise HTTPException(403, "Choose one of the three course demo identities.")
        with db.connection() as conn:
            user = db.get_user(conn, body.user_id)
            if user is None or user.role != body.role:
                raise HTTPException(403, "The selected identity does not match the course database.")
            ctx = AuthContext(user_id=user.id, role=user.role, store_id=user.store_id)
            identifier = uuid4().hex
            directory = conversation_dir(identifier)
            directory.mkdir(parents=True)
            with sqlite3.connect(directory / "world.db") as destination:
                conn.backup(destination)
        config = model_configuration()
        value = {"id": identifier, "role": ctx.role, "user_id": ctx.user_id,
                 "store_id": ctx.store_id, "model": config["model"],
                 "prompt_version": prompt_version(), "created_at": _now(),
                 "turns": [], "expected": "", "saved": False, "failed": False}
        _write_json(directory / "conversation.json", value)
        return value

    @app.get("/api/conversations/{identifier}")
    def get_conversation(identifier: str):
        return read_conversation(identifier)

    @app.post("/api/conversations/{identifier}/messages")
    async def send_message(identifier: str, body: Message):
        message = body.message.strip()
        if not message:
            raise HTTPException(422, "Enter a message first.")
        config = model_configuration()
        if not config["provider_configured"]:
            raise HTTPException(503, config["message"])
        lock = locks.setdefault(identifier, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "A response is already running for this conversation.")
        async with lock:
            value = read_conversation(identifier)
            if value["saved"] or value["failed"]:
                raise HTTPException(409, "This conversation is closed. Start a new conversation.")
            if value["prompt_version"] != prompt_version() or value["model"] != config["model"]:
                raise HTTPException(409, "The model or prompt changed. Start a new conversation.")
            if not value["turns"]:
                if not body.expected or not body.expected.strip():
                    raise HTTPException(422, "Describe the expected behavior before the first message.")
                value["expected"] = body.expected.strip()
            ctx = AuthContext(user_id=value["user_id"], role=value["role"], store_id=value["store_id"])
            directory = conversation_dir(identifier)
            session = SQLiteSession(identifier, str(directory / "messages.db"))
            try:
                with database_scope(directory / "world.db"):
                    result = await Runner.run(
                        build_agent(ctx, model=value["model"]), message, session=session,
                        context=ctx, max_turns=MAX_TURNS, run_config=RunConfig(tracing_disabled=True),
                    )
                calls = collect_tool_calls(result.new_items)
                reply = str(result.final_output)
            except Exception as exc:
                value["failed"] = True
                value["error_type"] = type(exc).__name__
                value["failed_request"] = message
                _write_json(directory / "conversation.json", value)
                raise HTTPException(502, f"The model run failed ({type(exc).__name__}). Check the provider key, credits, and model setting. Start a new conversation before retrying; partial tool actions may have occurred.") from None
            finally:
                session.close()
            turn = {"request": message, "response": reply, "tool_calls": calls, "created_at": _now()}
            value["turns"].append(turn)
            _write_json(directory / "conversation.json", value)
            return {"conversation_id": identifier, "reply": reply, "tool_calls": calls,
                    "turns": value["turns"], "prompt_version": value["prompt_version"]}

    @app.post("/api/conversations/{identifier}/save")
    async def save_conversation(identifier: str, assessment: Assessment):
        lock = locks.setdefault(identifier, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "Wait for the current response before saving.")
        async with lock, record_lock:
            value = read_conversation(identifier)
            if value["failed"] or not value["turns"]:
                raise HTTPException(409, "Only completed model conversations can be saved.")
            requirement = assessment.requirement or None
            known = {row["id"] for row in specification_requirements()}
            if requirement is not None and requirement not in known:
                raise HTTPException(422, "Choose a requirement from SPEC.md, or leave it unassigned.")
            existing = records.read_text(encoding="utf-8") if records.exists() else ""
            for line in existing.splitlines():
                if line.strip() and json.loads(line).get("conversation_id") == identifier:
                    value["saved"] = True
                    _write_json(conversation_dir(identifier) / "conversation.json", value)
                    return {"saved": True, "saved_count": count_records()}
            record = {"role": value["role"], "user_id": value["user_id"], "store_id": value["store_id"],
                      "request": value["turns"][0]["request"],
                      "tool_calls": [call for turn in value["turns"] for call in turn["tool_calls"]],
                      "response": value["turns"][-1]["response"],
                      **assessment.model_dump(), "requirement": requirement,
                      "conversation_id": identifier, "model": value["model"],
                      "prompt_version": value["prompt_version"], "turns": value["turns"],
                      "initial_expected": value["expected"], "saved_at": _now()}
            records.parent.mkdir(parents=True, exist_ok=True)
            # Rewrite atomically so a crash cannot leave a half-written JSONL line.
            temporary = records.with_name(records.name + ".tmp")
            prefix = existing if not existing or existing.endswith("\n") else existing + "\n"
            temporary.write_text(prefix + json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.replace(records)
            value["saved"] = True
            value["assessment"] = assessment.model_dump()
            _write_json(conversation_dir(identifier) / "conversation.json", value)
            return {"saved": True, "saved_count": count_records()}

    @app.get("/api/records/download")
    def download_records():
        text = records.read_text(encoding="utf-8") if records.exists() else ""
        return Response(text, media_type="application/x-ndjson",
                        headers={"Content-Disposition": 'attachment; filename="hw1-session.jsonl"'})

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
    return app


app = create_app()


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="Open the Cartwheel HW1 browser workbench.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
