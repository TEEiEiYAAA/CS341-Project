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

    # 0) ถ้ามี hint จาก notify: {"bucket": "...", "key": "landing/xxx.zip"}
    #    ให้พยายามจัดการไฟล์นี้ก่อน (กันกรณี eventual consistency จากการ list)
    try:
        bucket_hint = event.get("bucket") if isinstance(event, dict) else None
        key_hint = event.get("key") if isinstance(event, dict) else None
    except Exception:
        bucket_hint = key_hint = None

    if bucket_hint == BUCKET and key_hint and key_hint.endswith(".zip") and key_hint.startswith(LANDING):
        try:
            # บางครั้งอัปเสร็จใหม่ๆ อาจยัง head ไม่เจอ → ลองซ้ำสั้นๆ
            etag = None
            for _ in range(3):
                try:
                    etag = s3.head_object(Bucket=BUCKET, Key=key_hint)["ETag"].strip('"')
                    break
                except s3.exceptions.NoSuchKey:
                    import time; time.sleep(0.5)  # wait a moment and retry
            if etag:
                proc_key = move_to_processing(key_hint, etag)
                if proc_key:
                    ok = extract_zip_to_raw(proc_key)
                    s3.delete_object(Bucket=BUCKET, Key=proc_key)
                    processed += 1
        except Exception as e:
            # ถ้าพัง โยนไฟล์จาก landing → _failed เพื่อไม่บล็อคงานถัดไป
            fail_key = key_hint.replace(LANDING, FAILED, 1)
            try:
                s3.copy_object(
                    Bucket=BUCKET,
                    CopySource={"Bucket": BUCKET, "Key": key_hint},
                    Key=fail_key,
                    Tagging="project=dermavision&stage=failed",
                    TaggingDirective="REPLACE"
                )
                s3.delete_object(Bucket=BUCKET, Key=key_hint)
            except Exception:
                pass
            print(f"ERROR direct process (notify): {key_hint}: {e}")

    # 1) เก็บกวาดไฟล์ค้างใน _processing/ ให้เสร็จก่อน
    for proc_key, _ in list_zip_under(PROCESSING):
        try:
            ok = extract_zip_to_raw(proc_key)
            s3.delete_object(Bucket=BUCKET, Key=proc_key)
            processed += 1
        except Exception as e:
            fail_key = proc_key.replace(PROCESSING, FAILED, 1)
            try:
                s3.copy_object(
                    Bucket=BUCKET,
                    CopySource={"Bucket": BUCKET, "Key": proc_key},
                    Key=fail_key,
                    Tagging="project=dermavision&stage=failed",
                    TaggingDirective="REPLACE"
                )
            finally:
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
            try:
                s3.copy_object(
                    Bucket=BUCKET,
                    CopySource={"Bucket": BUCKET, "Key": proc_key},
                    Key=fail_key,
                    Tagging="project=dermavision&stage=failed",
                    TaggingDirective="REPLACE"
                )
            finally:
                s3.delete_object(Bucket=BUCKET, Key=proc_key)
            print(f"ERROR processing (land): {src_key}: {e}")

    return {"ok": True, "processed": processed}

lambda_client = boto3.client("lambda")

# หลังแตก zip ทั้งหมดเสร็จ
lambda_client.invoke(FunctionName="preprocess-images", InvocationType="Event")
lambda_client.invoke(FunctionName="coco-to-rek-manifest", InvocationType="Event")