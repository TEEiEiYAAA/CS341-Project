import os, boto3, json
from io import BytesIO
from PIL import Image, ImageOps

s3 = boto3.client("s3")

BUCKET = os.getenv("BUCKET", "dermavision-offline")
DATASET = os.getenv("DATASET_NAME", "skin-2025-09")

RAW_PREFIX       = f"datasets/{DATASET}/raw/images/"
OUTPUT_PREFIX    = f"datasets/{DATASET}/preprocessed/images/"
READY_MARKER_KEY = f"datasets/{DATASET}/preprocessed/_READY"

# config
TARGET_SIDE     = int(os.getenv("TARGET_SIDE", "640"))   # 640 by default
PAD_COLOR       = (0, 0, 0)                               # black pad
MAX_PROCESSED   = int(os.getenv("MAX_PROCESSED", "5000"))  # safety cap

def _iter_s3_objects(bucket, prefix):
    token = None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix, MaxKeys=1000)
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        for obj in resp.get("Contents", []):
            # ข้าม "โฟลเดอร์" (key ที่ลงท้ายด้วย '/')
            if not obj["Key"].endswith("/"):
                yield obj
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")

def _head_ok(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def _out_key_for(raw_key: str) -> str:
    # เปลี่ยน prefix และบังคับนามสกุลเป็น .jpg
    base = os.path.basename(raw_key)
    if base.lower().endswith((".png", ".jpeg", ".jpg")):
        base = os.path.splitext(base)[0] + ".jpg"
    return os.path.join(OUTPUT_PREFIX, base).replace("\\", "/")

def _resize_letterbox(img: Image.Image, target_side: int) -> Image.Image:
    # แก้ orientation จาก EXIF ก่อน
    img = ImageOps.exif_transpose(img.convert("RGB"))
    w, h = img.size
    scale = min(target_side / w, target_side / h)
    new_w, new_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    img = img.resize((new_w, new_h), Image.BICUBIC)

    canvas = Image.new("RGB", (target_side, target_side), PAD_COLOR)
    off_x = (target_side - new_w) // 2
    off_y = (target_side - new_h) // 2
    canvas.paste(img, (off_x, off_y))
    return canvas

def handler(event, context):
    print(f"🚀 preprocess start dataset={DATASET} target={TARGET_SIDE}×{TARGET_SIDE}")
    processed = 0
    skipped   = 0

    for it in _iter_s3_objects(BUCKET, RAW_PREFIX):
        key = it["Key"]
        low = key.lower()
        if not (low.endswith(".jpg") or low.endswith(".jpeg") or low.endswith(".png")):
            continue

        out_key = _out_key_for(key)
        # ถ้ามีผลลัพธ์อยู่แล้วให้ข้าม
        if _head_ok(BUCKET, out_key):
            skipped += 1
            continue

        # อ่าน + แปลง
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        img = Image.open(BytesIO(obj["Body"].read()))
        img = _resize_letterbox(img, TARGET_SIDE)

        # เขียนกลับเป็น JPEG
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        buf.seek(0)
        s3.upload_fileobj(buf, BUCKET, out_key, ExtraArgs={"ContentType": "image/jpeg"})
        processed += 1

        if processed % 100 == 0:
            print(f"… processed {processed} images")

        if processed >= MAX_PROCESSED:
            print(f"⏹ reached MAX_PROCESSED={MAX_PROCESSED}, stop this run")
            break

    # เขียน READY ก็ต่อเมื่อรูปใน raw ถูกประมวลผลครบแล้ว (หรือมีอยู่แล้วครบ)
    # เช็คแบบหยาบ: ถ้าไม่มี “raw ที่ยังไม่มีผลลัพธ์” เหลืออยู่
    remaining = 0
    for it in _iter_s3_objects(BUCKET, RAW_PREFIX):
        key = it["Key"]
        if key.lower().endswith((".jpg", ".jpeg", ".png")) and not _head_ok(BUCKET, _out_key_for(key)):
            remaining += 1
            if remaining > 0:
                break

    if remaining == 0:
        s3.put_object(Bucket=BUCKET, Key=READY_MARKER_KEY, Body=b"ready", ContentType="text/plain")
        print(f"🏁 DONE processed={processed} (skipped={skipped}) — wrote {READY_MARKER_KEY}")
    else:
        print(f"ℹ️ processed={processed} (skipped={skipped}) remaining_raw_unprocessed≈{remaining}")

    return {
        "ok": True,
        "processed": processed,
        "skipped": skipped,
        "ready_written": remaining == 0,
        "ready_key": READY_MARKER_KEY
    }
