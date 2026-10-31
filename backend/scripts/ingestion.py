"""Run from backend: python -m scripts.ingestion migrate|worker|reconcile."""
import argparse
import asyncio
import logging
from pathlib import Path

from app.services import jobs


async def main(command):
    if command == 'migrate':
        async with jobs.connection() as conn:
            # Serialize setup across deploys; migrations are additive/idempotent.
            await conn.execute('SELECT pg_advisory_xact_lock(684202603)')
            await conn.execute((Path(__file__).resolve().parents[1] / 'migrations/001_ingestion.sql').read_text())
        print('Ingestion schema ready.')
    elif command == 'reconcile':
        from app.services.job_dispatch import dispatch
        for job_id in await jobs.pending_ids():
            await dispatch(job_id)
    else:
        from app.services.document_worker import process_one
        while True:
            await jobs.pending_ids()  # Expire abandoned input and recover stale leases.
            if not await process_one():
                await asyncio.sleep(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['migrate', 'worker', 'reconcile'])
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(parser.parse_args().command))
