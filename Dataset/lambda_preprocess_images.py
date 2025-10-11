import json, boto3, os
from io import BytesIO
from PIL import Image

s3 = boto3.client('s3')

BUCKET = os.getenv("BUCKET", "dermavision-offline")
DATASET = os.getenv("DATASET_NAME", "skin-2025-09")

RAW_PREFIX       = f"datasets/{DATASET}/raw/images/"
OUTPUT_PREFIX    = f"datasets/{DATASET}/preprocessed/images/"
READY_MARKER_KEY = f"datasets/{DATASET}/preprocessed/_READY"

TARGET_SIZE = (640, 640)  # ให้ตรงกับ width/height ใน coco.json

def handler(event, context):
    print(f"🚀 preprocess start | dataset={DATASET} target={TARGET_SIZE}")
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=RAW_PREFIX)
    if "Contents" not in r:
        print("⚠️ no raw images")
        return {"ok": True, "processed": 0, "note": "no raw images"}

    processed = 0
    for it in r["Contents"]:
        key = it["Key"]
        if not key.lower().endswith((".jpg", ".jpeg", ".png")):
            continue

        # read
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        img = Image.open(BytesIO(obj["Body"].read())).convert("RGB")

        # resize
        img = img.resize(TARGET_SIZE)

        # write
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        out_key = key.replace(RAW_PREFIX, OUTPUT_PREFIX, 1)
        s3.upload_fileobj(buf, BUCKET, out_key, ExtraArgs={"ContentType": "image/jpeg"})

        print(f"✅ {key} → {out_key}")
        processed += 1

    # READY marker
    s3.put_object(Bucket=BUCKET, Key=READY_MARKER_KEY, Body=b"ready", ContentType="text/plain")
    print(f"🏁 DONE processed={processed} wrote {READY_MARKER_KEY}")

    return {"ok": True, "processed": processed, "ready_key": READY_MARKER_KEY}
