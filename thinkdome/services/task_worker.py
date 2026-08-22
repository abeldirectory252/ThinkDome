"""Stable production worker entrypoint.

The implementation lives under ``platform.tasks``; this module keeps the
deployment command stable while the internal package layout evolves.
"""

from thinkdome.platform.tasks.worker import run_worker


if __name__ == "__main__":
    import asyncio
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    asyncio.run(run_worker())
