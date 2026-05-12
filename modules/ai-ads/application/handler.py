from typing import Any


def handle_task(task: dict[str, Any]) -> dict[str, Any]:
    return {"module": "ai-ads", "status": "received", "task": task}

