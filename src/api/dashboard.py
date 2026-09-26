"""
FastAPI Dashboard with Real-Time WebSocket Streaming & Metrics
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from src.config import settings
from src.graph.test_graph import test_automation_graph
from src.models.schemas import TestInput, HumanReviewAction
from src.models.state import TestAutomationState
from src.utils.logger import get_logger

logger = get_logger("dashboard")

app = FastAPI(
    title=f"{settings.app.name} Dashboard",
    version=settings.app.version,
)

# Ensure artifact directories exist and mount static route
artifacts_dir = Path(settings.storage.screenshots_dir.parent)
artifacts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir)), name="artifacts")

# In-memory storage for run history
RUN_HISTORY: Dict[str, Dict[str, Any]] = {}


def _persist_run_artifacts(run_id: str, payload: Dict[str, Any]) -> None:
    """Persist a completed run to disk for later inspection/export."""
    reports_dir = Path(settings.storage.reports_dir)
    data_dir = Path(settings.storage.data_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    artifact_summary = {
        "screenshots": [],
        "traces": [],
        "videos": [],
    }
    for result in payload.get("execution_results", []):
        if result.get("screenshot_path"):
            artifact_summary["screenshots"].append(result["screenshot_path"])
        if result.get("trace_path"):
            artifact_summary["traces"].append(result["trace_path"])
        if result.get("video_path"):
            artifact_summary["videos"].append(result["video_path"])

    persisted = {
        "run_id": run_id,
        "status": payload.get("status"),
        "summary": payload.get("summary", {}),
        "tests": payload.get("tests", []),
        "execution_results": payload.get("execution_results", []),
        "failures": payload.get("failures", []),
        "healed_tests": payload.get("healed_tests", []),
        "human_review_queue": payload.get("human_review_queue", []),
        "report": payload.get("report"),
        "timestamp": payload.get("timestamp"),
        "artifacts_summary": artifact_summary,
    }

    report_path = reports_dir / f"{run_id}.json"
    report_path.write_text(json.dumps(persisted, indent=2, default=str), encoding="utf-8")

    latest_path = data_dir / "latest_run.json"
    latest_path.write_text(json.dumps(persisted, indent=2, default=str), encoding="utf-8")

    logger.info("run_artifacts_persisted", run_id=run_id, report_path=str(report_path), latest_path=str(latest_path))


test_runs_total = Counter(
    "ai_test_automation_runs_total",
    "Total number of test automation runs requested",
)
last_run_tests = Gauge(
    "ai_test_automation_last_run_tests",
    "Number of tests in the most recent run",
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("websocket_connected", total_connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("websocket_disconnected", total_connections=len(self.active_connections))

    async def broadcast(self, message: Dict[str, Any]):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                cmd_type = payload.get("type", "ping")
            except Exception:
                cmd_type = "ping"

            await websocket.send_json({
                "type": "pong" if cmd_type == "ping" else "ack",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/v1/tests/run")
async def run_tests(input_data: TestInput):
    """
    Trigger an autonomous AI test automation run.
    Streams state progress via WebSocket to connected dashboard clients.
    """
    now_str = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    run_id = f"run-{now_str}-{abs(hash(input_data.requirements)) % 10000}"

    initial_state = TestAutomationState(
        requirements=input_data.requirements,
        source_code=input_data.source_code,
        api_docs=input_data.api_docs,
        test_plan=input_data.test_plan,
        generated_tests=[],
        execution_results=[],
        failures=[],
        healed_tests=[],
        human_review_queue=[],
        explanation=None,
        current_step="init",
        iteration_count=0,
        max_iterations=settings.app.max_healing_iterations,
        trace_id=run_id,
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=None,
        metrics={},
    )

    test_runs_total.inc()

    await manager.broadcast({
        "type": "run_started",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    try:
        result = await test_automation_graph.ainvoke(initial_state)
        last_run_tests.set(len(result.get("generated_tests", [])))

        summary = {
            "total": len(result.get("generated_tests", [])),
            "passed": sum(1 for t in result.get("generated_tests", []) if t["status"] == "passed"),
            "failed": sum(1 for t in result.get("generated_tests", []) if t["status"] == "failed"),
            "healed": sum(1 for t in result.get("generated_tests", []) if t["status"] == "healed"),
            "needs_review": len(result.get("human_review_queue", [])),
        }

        run_response = {
            "run_id": run_id,
            "status": "completed",
            "summary": summary,
            "tests": result.get("generated_tests", []),
            "execution_results": result.get("execution_results", []),
            "failures": result.get("failures", []),
            "healed_tests": result.get("healed_tests", []),
            "human_review_queue": result.get("human_review_queue", []),
            "report": result.get("explanation"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        RUN_HISTORY[run_id] = run_response
        _persist_run_artifacts(run_id, run_response)

        await manager.broadcast({
            "type": "run_completed",
            "run_id": run_id,
            "summary": summary,
            "tests": result.get("generated_tests", []),
            "human_review_queue": result.get("human_review_queue", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return run_response
    except Exception as e:
        logger.error("run_execution_failed", run_id=run_id, error=str(e), exc_info=True)
        await manager.broadcast({
            "type": "run_failed",
            "run_id": run_id,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if getattr(e, "status_code", None) == 429 or "429" in str(e):
            raise HTTPException(
                status_code=429,
                detail=(
                    "The configured LLM provider is temporarily rate-limited. "
                    "Wait briefly, use another LLM_MODEL, or configure your own provider key."
                ),
            )
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@app.post("/api/v1/tests/review")
async def review_test(action: HumanReviewAction):
    """
    Approve or reject a low-confidence healed test case from human review queue.
    """
    target_run = None
    target_run_id = None
    for rid, rdata in RUN_HISTORY.items():
        for item in rdata.get("human_review_queue", []):
            if item.get("test_id") == action.test_id:
                target_run = rdata
                target_run_id = rid
                break
        if target_run:
            break

    if not target_run:
        # Fallback to latest run if available
        if RUN_HISTORY:
            target_run_id = list(RUN_HISTORY.keys())[-1]
            target_run = RUN_HISTORY[target_run_id]
        else:
            raise HTTPException(status_code=404, detail=f"No run found containing test {action.test_id}")

    tests = target_run.get("tests", [])
    review_queue = target_run.get("human_review_queue", [])

    new_status = "healed" if action.action == "approve" else "failed"
    for test in tests:
        if test.get("id") == action.test_id:
            test["status"] = new_status
            if action.fixed_code:
                test["code"] = action.fixed_code
            test["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Update item in human_review_queue
    for item in review_queue:
        if item.get("test_id") == action.test_id:
            item["approved"] = (action.action == "approve")
            item["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            item["reviewer_notes"] = action.notes or f"Action: {action.action}"

    # Recalculate summary
    summary = {
        "total": len(tests),
        "passed": sum(1 for t in tests if t.get("status") == "passed"),
        "failed": sum(1 for t in tests if t.get("status") == "failed"),
        "healed": sum(1 for t in tests if t.get("status") == "healed"),
        "needs_review": sum(1 for t in tests if t.get("status") == "needs_review"),
    }
    target_run["summary"] = summary

    await manager.broadcast({
        "type": "review_updated",
        "run_id": target_run_id,
        "test_id": action.test_id,
        "action": action.action,
        "new_status": new_status,
        "summary": summary,
        "tests": tests,
        "human_review_queue": review_queue,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "status": "success",
        "test_id": action.test_id,
        "new_status": new_status,
        "summary": summary,
    }


@app.get("/api/v1/runs")
async def list_runs():
    """List historical execution runs."""
    return [
        {
            "run_id": rid,
            "timestamp": rdata.get("timestamp"),
            "status": rdata.get("status"),
            "summary": rdata.get("summary"),
        }
        for rid, rdata in RUN_HISTORY.items()
    ]


@app.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str):
    """Get full details of a past execution run."""
    if run_id not in RUN_HISTORY:
        raise HTTPException(status_code=404, detail="Run not found")
    return RUN_HISTORY[run_id]


@app.get("/api/v1/metrics")
async def get_metrics():
    """Get current system metrics."""
    return {
        "app": settings.app.name,
        "version": settings.app.version,
        "model": settings.llm.model,
        "max_healing_iterations": settings.app.max_healing_iterations,
        "confidence_threshold": settings.app.confidence_threshold,
        "active_connections": len(manager.active_connections),
    }


@app.get("/health")
async def health_check():
    """Return lightweight liveness status."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Expose application metrics in Prometheus text format."""
    return PlainTextResponse(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/")
async def dashboard():
    """Serve the standalone frontend dashboard file."""
    return FileResponse(Path(__file__).resolve().parents[2] / "frontend" / "index.html")
