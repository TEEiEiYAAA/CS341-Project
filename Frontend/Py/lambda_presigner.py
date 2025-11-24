import os, json, uuid, datetime as dt, boto3
import logging
import secrets # <- เพิ่ม import นี้

# ตั้งค่า logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

ALLOWED_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "heic": "image/heic"}
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://dermavision.s3.us-east-1.amazonaws.com")

s3 = boto3.client("s3") # <- ย้าย s3 client มาไว้ข้างนอก

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "Access-Control-Allow-Origin": CORS_ORIGIN,
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }

def generate_unique_user_id(bucket: str, s3_client) -> str:
    """
    สุ่มรหัสผู้ใช้ (8 ตัวอักษร) และตรวจสอบว่ายังไม่มีใน S3 bucket
    """
    max_tries = 10
    for _ in range(max_tries):
        # สุ่มตัวอักษรและตัวเลข 8 ตัว (hex 4 bytes = 8 chars)
        user_id = secrets.token_hex(4) 
        prefix = f"uploads/user={user_id}/" # <- นี่คือ "folder" ที่เราจะเช็ก

        # ตรวจสอบว่ามี object ที่ขึ้นต้นด้วย prefix นี้หรือไม่
        response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            MaxKeys=1 # เราแค่ต้องการรู้ว่ามี "อย่างน้อย 1" หรือไม่
        )
        
        # ถ้า 'Contents' ไม่มีอยู่ หรือเป็น list ว่าง
        # แปลว่า prefix นี้ยังไม่เคยถูกใช้งาน
        if 'Contents' not in response or not response['Contents']:
            logger.info(f"✅ Generated unique userId: {user_id}")
            return user_id

    # ถ้าวน loop 10 ครั้งแล้วยังชนอยู่ ให้โยน error
    logger.error(f"❌ Failed to generate unique userId after {max_tries} tries.")
    raise Exception("Failed to generate unique user ID (collision)")


def handler(event, context):
    try:
        bucket = os.environ.get("RAW_BUCKET")
        if not bucket:
            logger.error("❌ RAW_BUCKET env not set")
            return _resp(500, {"error": "RAW_BUCKET env not set"})

        # --- ส่วนที่เปลี่ยนแปลง ---
        # เราจะไม่รับ userId จาก query string อีกต่อไป
        # แต่จะสร้างขึ้นมาใหม่ทุกครั้งที่เรียก
        try:
            user_id = generate_unique_user_id(bucket, s3)
        except Exception as e:
            logger.exception("❌ Error during user ID generation")
            return _resp(500, {"error": "id_generation_failed", "detail": str(e)})
        # ------------------------

        qs = event.get("queryStringParameters") or {}
        ext = (qs.get("ext") or "jpg").lower() # <- ยังคงรับ ext จาก query string
        ctype = ALLOWED_EXT.get(ext)
        if not ctype:
            logger.warning(f"❌ Unsupported ext requested: {ext}")
            return _resp(400, {"error": f"unsupported ext: {ext}"})

        max_size = int(os.environ.get("MAX_SIZE", "10000000"))  # 10MB
        now = dt.datetime.utcnow()
        # สร้าง key โดยใช้ user_id ที่สุ่มมาได้
        key = f"uploads/user={user_id}/dt={now:%Y/%m/%d}/{uuid.uuid4()}.{ext}"

        # log ข้อมูลสำคัญ
        logger.info(f"🚀 Presign requested | user={user_id}, fileKey={key}")

        presigned = s3.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={
              "Content-Type": ctype,
              "acl": "public-read"  # <-- 1. เพิ่ม Field นี้
          },
          Conditions=[
              ["content-length-range", 0, max_size], 
              {"Content-Type": ctype},
              {"acl": "public-read"}   # <-- 2. เพิ่ม Condition นี้
          ],
          ExpiresIn=300,
        )

        logger.info(f"✅ Presigned URL generated successfully for {key}")
        
        # --- ส่วนที่เปลี่ยนแปลง ---
        # ส่ง 'userId' ที่สุ่มได้ กลับไปให้ frontend ด้วย
        return _resp(200, {"key": key, "userId": user_id, "upload": presigned})
        # ------------------------

    except Exception as e:
        logger.exception("❌ Internal error while generating presign")
        return _resp(500, {"error": "internal_error", "detail": str(e)})