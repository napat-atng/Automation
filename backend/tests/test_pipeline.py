import io
import os
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='media-tests-'))

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, func

from app.db import Base, engine, Session, Asset, ImportItem, DATA
from app.main import app
from app.processing import process_asset


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def photo():
    buf = io.BytesIO()
    Image.new('RGB', (100, 80), 'green').save(buf, 'PNG')
    return buf.getvalue()


def test_batch_dedup_corrupt_and_retry():
    with TestClient(app) as client:
        response = client.post('/api/imports', files=[('files', ('a.png', photo())), ('files', ('renamed.png', photo())), ('files', ('bad.jpg', b'broken')), ('files', ('notes.txt', b'text')), ('files', ('empty.png', b''))])
        assert response.status_code == 200
        items = response.json()['items']
        assert [i['status'] for i in items] == ['accepted', 'duplicate', 'accepted', 'rejected', 'rejected']
        good, broken = items[0]['asset']['id'], items[2]['asset']['id']
        for asset_id in (broken, good):
            process_asset(asset_id)
        assert client.get(f'/api/assets/{good}').json()['status'] == 'ready'
        assert client.get(f'/api/assets/{broken}').json()['status'] == 'failed'
        assert client.get(f'/api/assets/{good}/original').content == photo()
        thumbnail = client.get(f'/api/assets/{good}/thumbnail')
        assert thumbnail.status_code == 200
        assert Image.open(io.BytesIO(thumbnail.content)).size == (100, 80)
        process_asset(good)
        with Session() as db:
            assert db.get(Asset, good).attempts == 1
            assert db.scalar(select(func.count()).select_from(Asset)) == 2
            assert db.scalar(select(func.count()).select_from(ImportItem)) == 3
        assert client.post(f'/api/assets/{good}/retry').status_code == 409
        assert client.post(f'/api/assets/{broken}/retry').json()['status'] == 'pending'
        assert client.get(f'/api/assets/{good}').json()['captured_at'] is None


def test_limits_and_missing(monkeypatch):
    monkeypatch.setattr('app.main.MAX_BYTES', 4)
    with TestClient(app) as client:
        assert client.post('/api/imports', files={'files': ('large.png', photo())}).json()['items'][0]['status'] == 'rejected'
        assert client.get('/api/assets/missing/thumbnail').status_code == 404
        assert not list((DATA / 'tmp').iterdir())


def test_video_thumbnail(tmp_path):
    video = tmp_path / 'clip.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:d=1', '-c:v', 'mpeg4', str(video)], check=True)
    with TestClient(app) as client:
        item = client.post('/api/imports', files={'files': ('clip.mp4', video.read_bytes())}).json()['items'][0]
        process_asset(item['asset']['id'])
        result = client.get('/api/assets/' + item['asset']['id']).json()
        assert result['status'] == 'ready'
        assert result['duration'] >= 1
        assert client.get(result['thumbnail_url']).status_code == 200


def test_durable_reconciliation():
    if not os.getenv('TEST_REDIS_URL'):
        pytest.skip('Set TEST_REDIS_URL to run the Redis integration test')
    from redis import Redis
    from rq import Queue, SimpleWorker
    from app.worker import reconcile, recover_interrupted
    redis = Redis.from_url(os.environ['TEST_REDIS_URL'])
    redis.flushdb()  # Dedicated TEST Redis database only.
    with TestClient(app) as client:
        asset_id = client.post('/api/imports', files={'files': ('recover.png', photo())}).json()['items'][0]['asset']['id']
        reconcile(redis)
        queue = Queue('media', connection=redis)
        assert len(queue) == 1
        reconcile(redis)
        assert len(queue) == 1
        # Simulate losing Redis while PostgreSQL retains the queued job.
        redis.flushdb()
        reconcile(redis)
        assert len(queue) == 1
        # Simulate an interrupted work horse after the DB status was committed.
        from rq.job import Job
        job = Job.fetch(f'media-{asset_id}', connection=redis)
        queue.remove(job)
        job.set_status('started')
        from rq.executions import Execution
        with redis.pipeline() as pipeline:
            Execution.create(job, ttl=180, pipeline=pipeline)
            pipeline.execute()
        with Session() as db:
            asset = db.get(Asset, asset_id)
            asset.status = 'processing'
            asset.attempts = 1
            db.commit()
        recover_interrupted(redis)
        reconcile(redis)
        assert len(queue) == 1
        SimpleWorker([queue], connection=redis).work(burst=True)
        assert client.get('/api/assets/' + asset_id).json()['status'] == 'ready'
    engine.dispose()
    with TestClient(app) as restarted:
        assert restarted.get('/api/assets/' + asset_id).json()['status'] == 'ready'
