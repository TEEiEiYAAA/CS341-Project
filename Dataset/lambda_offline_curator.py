import os, io, json, zipfile, boto3, botocore, time
from tempfile import SpooledTemporaryFile

s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")

BUCKET      = os.environ.get("BUCKET", "dermavision-offline")
DATASET     = os.environ.get("DATASET_NAME", "skin-2025-09")
LANDING     = os.environ.get("LANDING_PREFIX", "landing/")
PROCESSING  = os.environ.get("PROCESSING_PREFIX", "landing/_processing/")
FAILED      = os.environ.get("FAILED_PREFIX", "landing/_failed/")

RAW_IMAGES  = f"datasets/{DATASET}/raw/images/"
RAW_ANN     = f"datasets/{DATASET}/raw/annotations/coco.json"
READY_KEY   = f"datasets/{DATASET}/preprocessed/_READY"

PREPROCESS_FN = os.environ.get("PREPROCESS_FN", "preprocess-images")
MANIFEST_FN   = os.environ.get("MANIFEST_FN", "coco-to-rek-manifest")

def s3_exists(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def move_to_processing(src_key, etag):
    dst_key = src_key.replace(LANDING, PROCESSING, 1)
    try:
        s3.copy_object(
            Bucket=BUCKET,
            CopySource={"Bucket": BUCKET, "Key": src_key},
            Key=dst_key,
            Tagging="project=dermavision&stage=processing",
            TaggingDirective="REPLACE",
            MetadataDirective="REPLACE",
            CopySourceIfMatch=etag
        )
        s3.delete_object(Bucket=BUCKET, Key=src_key)
        return dst_key
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "PreconditionFailed":
            print(f"⏭️ skip {src_key}: ETag changed")
            return None
        raise

def extract_zip_to_raw(zip_key):
    print(f"📦 extract: {zip_key}")
    obj = s3.get_object(Bucket=BUCKET, Key=zip_key)
    buf = SpooledTemporaryFile(max_size=200*1024*1024)
    for chunk in obj["Body"].iter_chunks(8*1024*1024):
        if chunk: buf.write(chunk)
    buf.seek(0)

    wrote = {"images": 0, "coco": False}
    with zipfile.ZipFile(buf) as z:
        for name in z.namelist():
            if name.endswith("/"):  # skip folders
                continue
            data = z.read(name)
            lower = name.lower()
            if lower.endswith((".jpg", ".jpeg", ".png")):
                out_key = f"{RAW_IMAGES}{os.path.basename(name)}"
                s3.put_object(Bucket=BUCKET, Key=out_key, Body=data,
                              ContentType="image/jpeg",
                              Tagging="project=dermavision&stage=raw")
                wrote["images"] += 1
            elif lower.endswith(".json") and "coco" in lower:
                s3.put_object(Bucket=BUCKET, Key=RAW_ANN, Body=data,
                              ContentType="application/json",
                              Tagging="project=dermavision&stage=raw")
                wrote["coco"] = True
    print(f"📤 extracted images={wrote['images']} coco={wrote['coco']}")
    return wrote

def wait_ready(timeout=180, interval=5):
    waited = 0
    while waited < timeout:
        if s3_exists(BUCKET, READY_KEY):
            return True
        time.sleep(interval)
        waited += interval
    return False

def handler(event, context):
    print(f"🚀 curator start | dataset={DATASET}")

    # 1) ย้าย zip จาก landing → _processing แล้วแตก
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=LANDING)
    processed_archives = 0
    for it in r.get("Contents", []):
        k = it["Key"]
        if not k.lower().endswith(".zip"): 
            continue
        etag = it["ETag"].strip('"')
        proc_key = move_to_processing(k, etag)
        if not proc_key:
            continue
        try:
            extract_zip_to_raw(proc_key)
        finally:
            s3.delete_object(Bucket=BUCKET, Key=proc_key)
        processed_archives += 1

    # 2) เรียก preprocess แบบรอผล
    resp = lambda_client.invoke(FunctionName=PREPROCESS_FN, InvocationType="RequestResponse",
                                Payload=json.dumps({"dataset": DATASET}).encode("utf-8"))
    print("🧪 preprocess invoked status:", resp.get("StatusCode"))

    # 3) รอ READY แล้วค่อยเรียก manifest
    if wait_ready():
        r2 = lambda_client.invoke(FunctionName=MANIFEST_FN, InvocationType="Event",
                                  Payload=json.dumps({"dataset": DATASET}).encode("utf-8"))
        print("🧾 manifest invoked status:", r2.get("StatusCode"))
    else:
        print("⚠️ READY not found, skip manifest this round")

    return {"ok": True, "processed_archives": processed_archives}
