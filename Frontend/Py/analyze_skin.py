import os
import json
import base64
import logging
import urllib.request
import urllib.parse
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

rekognition = boto3.client("rekognition")
s3          = boto3.client("s3")

MODEL_ARN      = os.environ["MODEL_ARN"]
RESULT_BUCKET  = os.environ["RESULT_BUCKET"]
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "70"))

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }

def handler(event, context):
    try:
        body = event.get("body")
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body or "").decode("utf-8")
        data = json.loads(body or "{}")

        image_url       = data["image_url"]          # presigned GET url
        session_id      = data.get("sessionId")
        user_skin_types = data.get("skinTypes")      # ส่งมาเป็น "Oily,Sensitive" ได้
        src_bucket      = data.get("source_bucket")  # optional
        src_key         = data.get("source_key")     # optional

        # ดาวน์โหลดรูปจาก presigned URL
        with urllib.request.urlopen(image_url, timeout=15) as r:
            img_bytes = r.read()

        # วิเคราะห์ด้วยโมเดลใน Account B
        resp = rekognition.detect_custom_labels(
            ProjectVersionArn=MODEL_ARN,
            Image={"Bytes": img_bytes},
            MinConfidence=MIN_CONFIDENCE
        )
        labels = sorted({lbl["Name"] for lbl in resp.get("CustomLabels", [])})

        # สร้าง result key
        if src_key:
            out_key = src_key.replace("uploads/", "results/", 1) + ".json"
        else:
            # กรณีไม่มี source_key ให้ fallback ชื่อจาก URL
            filename = os.path.basename(urllib.parse.urlparse(image_url).path) or "image"
            out_key = f"results/{filename}.json"

        result = {
            "source": {"bucket": src_bucket, "key": src_key, "via": "presigned_url"},
            "sessionId": session_id,
            "user_skin_types": user_skin_types,
            "labels": list(labels)
        }

        s3.put_object(
            Bucket=RESULT_BUCKET,
            Key=out_key,
            Body=json.dumps(result, ensure_ascii=False, indent=2),
            ContentType="application/json"
        )
        logger.info(f"Saved result to s3://{RESULT_BUCKET}/{out_key}")
        return _resp(200, {"ok": True, "result_key": out_key})

    except Exception as e:
        logger.exception("Error")
        return _resp(500, {"error": str(e)})