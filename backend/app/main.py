import hashlib
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import DATA, Session, Asset, ImportItem, init_db

TYPES = {'.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.webp': 'image', '.mp4': 'video', '.mov': 'video'}
MAX_BYTES = int(os.getenv('MAX_FILE_BYTES', str(250 * 1024 * 1024)))


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title='AI Media Organizer — Phase A', lifespan=lifespan)


def asset_dict(asset):
    return {column.name: getattr(asset, column.name) for column in Asset.__table__.columns if column.name not in ('original', 'thumbnail')} | {
        'original_url': f'/api/assets/{asset.id}/original',
        'thumbnail_url': f'/api/assets/{asset.id}/thumbnail' if asset.thumbnail else None,
    }


@app.get('/api/health')
def health():
    with Session() as db:
        db.execute(select(Asset.id).limit(1))
    return {'status': 'ok', 'phase': 'A', 'max_file_bytes': MAX_BYTES, 'supported_extensions': list(TYPES)}


@app.post('/api/imports')
def import_files(files: list[UploadFile] = File(...)):
    if len(files) > 50:
        raise HTTPException(400, 'นำเข้าได้สูงสุดครั้งละ 50 ไฟล์')
    results = []
    for upload in files:
        filename = Path((upload.filename or 'unnamed').replace('\\', '/')).name
        suffix = Path(filename).suffix.lower()
        temp = DATA / 'tmp' / str(uuid.uuid4())
        try:
            if suffix not in TYPES:
                results.append({'filename': filename, 'status': 'rejected', 'error': 'ชนิดไฟล์ไม่รองรับ'})
                continue
            digest, size = hashlib.sha256(), 0
            with temp.open('wb') as output:
                while chunk := upload.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        break
                    digest.update(chunk)
                    output.write(chunk)
            if not size or size > MAX_BYTES:
                results.append({'filename': filename, 'status': 'rejected', 'error': f'ไฟล์ว่างหรือเกิน {MAX_BYTES / 1024 / 1024:g} MiB'})
                continue
            sha = digest.hexdigest()
            with Session() as db:
                asset = db.scalar(select(Asset).where(Asset.sha256 == sha))
                duplicate = asset is not None
                if asset is None:
                    original = f'originals/{sha}'
                    # Same-content concurrent imports share the same immutable path.
                    os.replace(temp, DATA / original)
                    asset = Asset(id=str(uuid.uuid4()), sha256=sha, filename=filename, kind=TYPES[suffix], size=size, original=original, status='pending')
                    db.add(asset)
                    try:
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                        asset = db.scalar(select(Asset).where(Asset.sha256 == sha))
                        duplicate = True
                db.add(ImportItem(id=str(uuid.uuid4()), asset_id=asset.id, filename=filename, duplicate=duplicate))
                db.commit()
                results.append({'filename': filename, 'status': 'duplicate' if duplicate else 'accepted', 'asset': asset_dict(asset)})
        finally:
            temp.unlink(missing_ok=True)
            upload.file.close()
    return {'items': results}


@app.get('/api/assets')
def assets():
    with Session() as db:
        return [asset_dict(a) for a in db.scalars(select(Asset).order_by(Asset.imported_at.desc()).limit(1000))]


@app.get('/api/assets/{asset_id}')
def detail(asset_id: str):
    with Session() as db:
        asset = db.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404, 'ไม่พบไฟล์')
        return asset_dict(asset)


@app.get('/api/assets/{asset_id}/{variant}')
def media_file(asset_id: str, variant: str):
    if variant not in ('original', 'thumbnail'):
        raise HTTPException(404)
    with Session() as db:
        asset = db.get(Asset, asset_id)
        if not asset or not getattr(asset, variant):
            raise HTTPException(404)
        return FileResponse(DATA / getattr(asset, variant), filename=asset.filename if variant == 'original' else None, content_disposition_type='inline', headers={'X-Content-Type-Options': 'nosniff'})


@app.post('/api/assets/{asset_id}/retry')
def retry(asset_id: str):
    with Session() as db:
        asset = db.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404)
        if asset.status != 'failed':
            raise HTTPException(409, 'เริ่มใหม่ได้เฉพาะงานที่ล้มเหลว')
        asset.status, asset.error, asset.attempts = 'pending', None, 0
        db.commit()
        return asset_dict(asset)
