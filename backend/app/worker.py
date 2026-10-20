"""Single worker with durable reconciliation. Run only one instance in Phase A."""
import os
import time

from redis import Redis
from rq import Queue, Worker
from rq.job import Job
from rq.exceptions import NoSuchJobError
from sqlalchemy import select

from .db import Session, Asset, init_db
from .processing import process_asset


def connection():
    return Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))


def reconcile(redis):
    queue = Queue('media', connection=redis)
    with Session() as db:
        for asset in db.scalars(select(Asset).where(Asset.status.in_(['pending', 'queued', 'processing']))):
            job_id = f'media-{asset.id}'
            try:
                job = Job.fetch(job_id, connection=redis)
                state = job.get_status(refresh=True)
            except NoSuchJobError:
                job, state = None, None
            if state in ('queued', 'started', 'deferred', 'scheduled'):
                continue
            if asset.attempts >= 3:
                asset.status = 'failed'
                asset.error = 'งานถูกขัดจังหวะครบ 3 ครั้ง กรุณาตรวจไฟล์แล้วลองใหม่'
                continue
            if job:
                job.delete()
            asset.status = 'queued'
            db.commit()
            queue.enqueue(process_asset, asset.id, job_id=job_id, job_timeout=180, result_ttl=3600)
        db.commit()



def recover_interrupted(redis):
    """Single-worker deployment: all previous executions are now abandoned."""
    queue = Queue('media', connection=redis)
    queue.started_job_registry.cleanup(timestamp=float('inf'))


def main():
    init_db()
    redis = connection()
    # This deployment has exactly one worker. Clear stale RQ state left by a killed process.
    for worker in Worker.all(connection=redis):
        worker.register_death()
    queue = Queue('media', connection=redis)
    while True:
        try:
            recover_interrupted(redis)
            reconcile(redis)
            Worker([queue], connection=redis).work(burst=True, with_scheduler=False, logging_level="WARNING")
        except Exception:
            # Do not log filenames, OCR, or other personal content.
            print('Worker connection interrupted; retrying in 3 seconds', flush=True)
        time.sleep(3)


if __name__ == '__main__':
    main()
