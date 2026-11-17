import asyncio

from app import main
from app.integrations import scheduler


def test_all_background_tasks_stop_with_application(client, monkeypatch):
    """Enabling provider schedulers must not lose the CRM task on shutdown."""
    started, stopped = set(), set()

    def loop(name):
        async def run():
            started.add(name)
            try:
                await asyncio.Event().wait()
            finally:
                stopped.add(name)
        return run

    monkeypatch.setenv("SYNC_SCHEDULER", "true")
    monkeypatch.setattr(main.crm_bridge, "configured", lambda: True)
    monkeypatch.setattr(main.crm_bridge, "projection_loop", loop("crm"))
    for name in ("scheduler_loop", "publish_loop", "messages_loop"):
        monkeypatch.setattr(scheduler, name, loop(name))

    async def run():
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
        assert stopped == started == {"crm", "scheduler_loop", "publish_loop", "messages_loop"}

    asyncio.run(run())
