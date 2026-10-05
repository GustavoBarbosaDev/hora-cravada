from app.worker.settings import WorkerSettings, ping


async def test_ping_task_answers_pong() -> None:
    assert await ping({}) == "pong"


def test_ping_is_registered_in_worker() -> None:
    assert ping in WorkerSettings.functions
