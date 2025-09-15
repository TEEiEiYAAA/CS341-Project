import os, json, uuid, datetime as dt, boto3
import logging


# ตั้งค่า logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)


ALLOWED_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://staticwebdermavision.s3.us-east-1.amazonaws.com")


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
            return _resp(400, {"error": f"unsupported ext: {ext}"})


        max_size = int(os.environ.get("MAX_SIZE", "10000000"))  # 10MB
        now = dt.datetime.utcnow()
        key = f"uploads/user={user_id}/dt={now:%Y/%m/%d}/{uuid.uuid4()}.{ext}"


        # log ข้อมูลสำคัญ
        logger.info(f"🚀 Presign requested | user={user_id}, fileKey={key}")


        s3 = boto3.client("s3")
        presigned = s3.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"Content-Type": ctype},
            Conditions=[["content-length-range", 0, max_size], {"Content-Type": ctype}],
            ExpiresIn=300,
        )


        logger.info(f"✅ Presigned URL generated successfully for {key}")
        return _resp(200, {"key": key, "upload": presigned})


    except Exception as e:
        logger.exception("❌ Internal error while generating presign")
        return _resp(500, {"error": "internal_error", "detail": str(e)})
