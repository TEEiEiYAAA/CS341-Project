import os, json, uuid, datetime as dt, boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- CHANGE 1: เพิ่มชนิดไฟล์รูปภาพที่รองรับ (ถ้าต้องการ) ---
# เราสามารถเพิ่ม image format อื่นๆ ที่นี่ได้ เช่น webp, gif
# S3 จะใช้ค่า Content-Type นี้เพื่อ validate ไฟล์ที่อัปโหลดเข้ามาจริง
ALLOWED_EXT = {
    "jpg": "image/jpeg", 
    "jpeg": "image/jpeg", 
    "png": "image/png",
    "webp": "image/webp", # เพิ่ม webp เป็นตัวเลือก
    "gif": "image/gif"   # เพิ่ม gif เป็นตัวเลือก
    "heic": "image/heic"
    "heif": "image/heif"  # <-- เพิ่มบรรทัดนี้เผื่อความเข้ากันได้
}

# ใช้ "*" เพื่อทดสอบ หรือใส่ Domain ของเว็บจริงเมื่อใช้งาน
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*") 

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

def handler(event, context):
    try:
        bucket = os.environ.get("RAW_BUCKET")
        if not bucket:
            logger.error("❌ RAW_BUCKET env not set")
            return _resp(500, {"error": "RAW_BUCKET env not set"})

        qs = event.get("queryStringParameters") or {}
        user_id = (qs.get("userId") or "anonymous").strip()
        ext = (qs.get("ext") or "jpg").lower()

        ctype = ALLOWED_EXT.get(ext)
        if not ctype:
            logger.warning(f"❌ Unsupported ext requested: {ext}")
            # คืนค่า error ทันทีถ้า frontend ส่งนามสกุลไฟล์ที่ไม่รองรับมา
            return _resp(400, {"error": f"Unsupported file type: {ext}. Allowed types are: {list(ALLOWED_EXT.keys())}"})

        # --- CHANGE 2: ปรับขนาดไฟล์สูงสุดเป็น 32 MB ---
        # 1 MB = 1024 * 1024 bytes
        # 32 MB = 32 * 1024 * 1024 = 33,554,432 bytes
        # S3 จะปฏิเสธไฟล์ที่ขนาดเกินกว่านี้โดยอัตโนมัติ
        max_size = int(os.environ.get("MAX_SIZE", "33554432")) # Default to 32 MB

        now = dt.datetime.utcnow()
        key = f"uploads/user={user_id}/dt={now:%Y/%m/%d}/{uuid.uuid4()}.{ext}"

        logger.info(f"🚀 Presign requested | user={user_id}, fileKey={key}, maxSize={max_size} bytes")

        s3 = boto3.client("s3")
        
        # S3's 'Conditions' คือหัวใจของการ validate ฝั่ง server
        presigned = s3.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"Content-Type": ctype},
            Conditions=[
                # 1. ตรวจสอบว่าขนาดไฟล์ต้องไม่เกิน max_size ที่เรากำหนด
                ["content-length-range", 0, max_size],
                # 2. ตรวจสอบว่า Content-Type ของไฟล์ที่อัปโหลดจริง ต้องตรงกับที่เราอนุญาต (ctype)
                {"Content-Type": ctype}
            ],
            ExpiresIn=300, # URL ใช้งานได้ 5 นาที
        )

        logger.info(f"✅ Presigned URL generated successfully for {key}")
        return _resp(200, {"key": key, "upload": presigned})

    except Exception as e:
        logger.exception("❌ Internal error while generating presign")
        return _resp(500, {"error": "internal_error", "detail": str(e)})