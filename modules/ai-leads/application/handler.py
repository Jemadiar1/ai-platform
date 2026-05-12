from typing import Any


def handle_task(task: dict[str, Any]) -> dict[str, Any]:
    return {"module": "ai-leads", "status": "received", "task": task}

