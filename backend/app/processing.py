import json
import subprocess
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError

from .db import DATA, Session, Asset

PIPELINE = 'thumbnail-v1'


def process_asset(asset_id: str):
    with Session() as db:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.status == 'ready':
            return
        asset.status = 'processing'
        asset.attempts += 1
        asset.error = None
        db.commit()
        target = DATA / 'thumbnails' / f'{asset.id}.jpg'
        temporary = target.with_suffix('.tmp.jpg')
        try:
            source = DATA / asset.original
            if asset.kind == 'image':
                with Image.open(source) as original:
                    original.load()
                    exif_date = original.getexif().get(36867)
                    if exif_date:
                        try:
                            asset.captured_at = datetime.strptime(str(exif_date), '%Y:%m:%d %H:%M:%S').isoformat()
                            asset.date_source = 'exif_original_local_time'
                        except ValueError:
                            pass
                    picture = ImageOps.exif_transpose(original)
                    asset.width, asset.height = picture.size
                    picture.thumbnail((640, 640))
                    picture.convert('RGB').save(temporary, 'JPEG', quality=85)
            else:
                probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(source)], capture_output=True, timeout=30, check=True)
                info = json.loads(probe.stdout)
                stream = next(s for s in info['streams'] if s.get('codec_type') == 'video')
                asset.width, asset.height = stream['width'], stream['height']
                asset.duration = float(info['format'].get('duration', 0))
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-frames:v', '1', '-vf', 'scale=640:640:force_original_aspect_ratio=decrease', str(temporary)], capture_output=True, timeout=120, check=True)
            temporary.replace(target)
            asset.thumbnail = str(target.relative_to(DATA))
            asset.status = 'ready'
            asset.pipeline_version = PIPELINE
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
            asset.status = 'failed'
            asset.error = 'ไม่สามารถอ่านสื่อหรือสร้างภาพตัวอย่างได้ ไฟล์อาจเสียหรือ codec ไม่รองรับ'
        finally:
            temporary.unlink(missing_ok=True)
            db.commit()
