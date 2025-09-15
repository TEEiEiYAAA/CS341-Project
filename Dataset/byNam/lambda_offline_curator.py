import os, io, json, zipfile, boto3, botocore
from tempfile import SpooledTemporaryFile

s3 = boto3.client("s3")

BUCKET = os.environ.get("BUCKET", "dermavision-offline")
DATASET = os.environ.get("DATASET_NAME", "skin-2025-09")
LANDING = os.environ.get("LANDING_PREFIX", "landing/")
PROCESSING = os.environ.get("PROCESSING_PREFIX", "landing/_processing/")
FAILED = os.environ.get("FAILED_PREFIX", "landing/_failed/")

RAW_IMAGES = f"datasets/{DATASET}/raw/images/"
RAW_ANN = f"datasets/{DATASET}/raw/annotations/coco.json"

def list_zip_candidates():
    cont = None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": LANDING, "MaxKeys": 1000}
        if cont: kw["ContinuationToken"] = cont
        r = s3.list_objects_v2(**kw)
        for it in r.get("Contents", []):
            k = it["Key"]
            if not k.lower().endswith(".zip"):
                continue
            # ข้ามไฟล์ในโฟลเดอร์ควบคุม
            if k.startswith(PROCESSING) or k.startswith(FAILED):
                continue
            yield k, it["ETag"].strip('"')  # เก็บ ETag ไว้กันชนกัน
        if not r.get("IsTruncated"): break
        cont = r.get("NextContinuationToken")

def move_to_processing(src_key, etag):
    # คีย์ปลายทาง
    dst_key = src_key.replace(LANDING, PROCESSING, 1)
    try:
        s3.copy_object(
            Bucket=BUCKET,
            CopySource={"Bucket": BUCKET, "Key": src_key},
            Key=dst_key,
            Tagging="project=dermavision&stage=processing",
            TaggingDirective="REPLACE",
            MetadataDirective="REPLACE",
            CopySourceIfMatch=etag  # มีใครจับไปก่อนจะ fail ที่นี่
        )
        # ลบต้นฉบับหลังคัดลอกสำเร็จ
        s3.delete_object(Bucket=BUCKET, Key=src_key)
        return dst_key
    except botocore.exceptions.ClientError as e:
        # ถ้า precondition failed แสดงว่ามีตัวอื่นจับไปแล้ว
        if e.response["Error"]["Code"] in ("PreconditionFailed",):
            return None
        raise

def extract_zip_to_raw(zip_key):
    # โหลดไฟล์ zip แบบสลับลงดิสก์ถ้าใหญ่
    obj = s3.get_object(Bucket=BUCKET, Key=zip_key)
    buf = SpooledTemporaryFile(max_size=200*1024*1024)  # 200MB in-memory ก่อนลงดิสก์
    for chunk in obj["Body"].iter_chunks(8*1024*1024):
        if chunk: buf.write(chunk)
    buf.seek(0)

    with zipfile.ZipFile(buf) as z:
        coco_written = False
        for name in z.namelist():
            if name.endswith("/"):
                continue
            data = z.read(name)
            lower = name.lower()
            if lower.endswith((".jpg", ".jpeg", ".png")):
                out_key = f"{RAW_IMAGES}{os.path.basename(name)}"
                s3.put_object(
                    Bucket=BUCKET, Key=out_key, Body=data,
                    ContentType="image/jpeg",
                    Tagging="project=dermavision&stage=raw"
                )
            elif lower.endswith(".json") and "coco" in lower:
                s3.put_object(
                    Bucket=BUCKET, Key=RAW_ANN, Body=data,
                    ContentType="application/json",
                    Tagging="project=dermavision&stage=raw"
                )
                coco_written = True
        return coco_written

def list_zip_under(prefix):
    cont = None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": prefix, "MaxKeys": 1000}
        if cont: kw["ContinuationToken"] = cont
        r = s3.list_objects_v2(**kw)
        for it in r.get("Contents", []):
            k = it["Key"]
            if k.endswith("/") or not k.lower().endswith(".zip"):
                continue
            yield k, it["ETag"].strip('"')
        if not r.get("IsTruncated"): break
        cont = r.get("NextContinuationToken")

def handler(event, context):
    processed = 0

    # 1) เก็บกวาดไฟล์ค้างใน _processing/ ให้เสร็จก่อน
    for proc_key, _ in list_zip_under(PROCESSING):
        try:
            ok = extract_zip_to_raw(proc_key)
            s3.delete_object(Bucket=BUCKET, Key=proc_key)
            processed += 1
        except Exception as e:
            fail_key = proc_key.replace(PROCESSING, FAILED, 1)
            s3.copy_object(
                Bucket=BUCKET,
                CopySource={"Bucket": BUCKET, "Key": proc_key},
                Key=fail_key,
                Tagging="project=dermavision&stage=failed",
                TaggingDirective="REPLACE"
            )
            s3.delete_object(Bucket=BUCKET, Key=proc_key)
            print(f"ERROR processing (proc): {proc_key}: {e}")

    # 2) รับไฟล์ใหม่จาก landing/ → ย้ายเข้า _processing/ → แตก
    for src_key, etag in list_zip_under(LANDING):
        # ข้ามไฟล์ควบคุม (กันซ้ำ)
        if src_key.startswith(PROCESSING) or src_key.startswith(FAILED):
            continue
        proc_key = move_to_processing(src_key, etag)
        if not proc_key:
            continue  # มี Lambda ตัวอื่นจับไปแล้ว
        try:
            ok = extract_zip_to_raw(proc_key)
            s3.delete_object(Bucket=BUCKET, Key=proc_key)
            processed += 1
        except Exception as e:
            fail_key = proc_key.replace(PROCESSING, FAILED, 1)
            s3.copy_object(
                Bucket=BUCKET,
                CopySource={"Bucket": BUCKET, "Key": proc_key},
                Key=fail_key,
                Tagging="project=dermavision&stage=failed",
                TaggingDirective="REPLACE"
            )
            s3.delete_object(Bucket=BUCKET, Key=proc_key)
            print(f"ERROR processing (land): {src_key}: {e}")

    return {"ok": True, "processed": processed}
