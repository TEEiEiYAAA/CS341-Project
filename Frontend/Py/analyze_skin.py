import os
import json
import logging
import boto3
from urllib.parse import unquote_plus

logger = logging.getLogger()
logger.setLevel(logging.INFO)

rekognition = boto3.client("rekognition")
s3 = boto3.client("s3")

PROJECT_VERSION_ARN = os.environ["PROJECT_VERSION_ARN"]
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "").strip()
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "50"))

def _build_result_key(src_key: str) -> str:
    clean_key = src_key.lstrip("/")
    if not clean_key.startswith("uploads/"):
        clean_key = f"uploads/{clean_key}"
    return f"{clean_key.replace('uploads/', 'results/', 1)}.json"

def _parse_user_id_from_key(src_key: str) -> str | None:
    parts = src_key.split("/")
    for p in parts:
        if p.startswith("user="):
            return p.split("=", 1)[1]
    return None

def handler(event, context):
    logger.info("📥 Event: %s", json.dumps(event, ensure_ascii=False))

    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key = unquote_plus(rec["s3"]["object"]["key"])
        out_bucket = OUTPUT_BUCKET or bucket
        out_key = _build_result_key(key)
        user_id = _parse_user_id_from_key(key)

        logger.info(f"🖼️ Analyze s3://{bucket}/{key}")

        try:
            response = rekognition.detect_custom_labels(
                ProjectVersionArn=PROJECT_VERSION_ARN,
                Image={"S3Object": {"Bucket": bucket, "Name": key}},
                MinConfidence=MIN_CONFIDENCE
            )
        except Exception as e:
            logger.exception("❌ Rekognition error")
            _put_json(out_bucket, out_key, {"error": str(e)})
            continue

        # ดึงเฉพาะชื่อ label และกรองซ้ำ
        labels = sorted(list({lbl["Name"] for lbl in response.get("CustomLabels", [])}))

        result = {
            "source": {"bucket": bucket, "key": key},
            "userId": user_id,
            "labels": labels
        }

        _put_json(out_bucket, out_key, result)
        logger.info(f"✅ Saved to s3://{out_bucket}/{out_key}")

    return {"statusCode": 200, "body": "ok"}

def _put_json(bucket: str, key: str, data: dict):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json"
    )
