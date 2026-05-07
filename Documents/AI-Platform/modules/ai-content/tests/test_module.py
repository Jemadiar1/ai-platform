from application.handler import handle_task


def test_handle_task_returns_module_name() -> None:
    result = handle_task({"task_id": "1"})
    assert result["module"] == "ai-content"

