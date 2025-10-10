import json, boto3, os
from io import BytesIO
from PIL import Image

s3 = boto3.client('s3')

BUCKET = os.getenv("BUCKET", "dermavision-offline")
DATASET_PREFIX = os.getenv("DATASET_PREFIX", "datasets/skin-2025-09/raw/images/")
OUTPUT_PREFIX  = os.getenv("OUTPUT_PREFIX",  "datasets/skin-2025-09/processed/")

def handler(event, context):
    print("Event:", json.dumps(event))
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=DATASET_PREFIX)
    if "Contents" not in r:
        return {"ok": True, "processed": 0, "note": "no images"}
    processed = 0
    for it in r["Contents"]:
        key = it["Key"]
        if not key.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        img_obj = s3.get_object(Bucket=BUCKET, Key=key)
        img = Image.open(BytesIO(img_obj["Body"].read())).convert("RGB")
        img = img.resize((224, 224))   # resize
        buf = BytesIO(); img.save(buf, format="JPEG"); buf.seek(0)
        out_key = key.replace(DATASET_PREFIX, OUTPUT_PREFIX, 1)
        s3.upload_fileobj(buf, BUCKET, out_key, ExtraArgs={"ContentType":"image/jpeg"})
        print(f"✅ {key} → {out_key}")
        processed += 1
    return {"ok": True, "processed": processed}
