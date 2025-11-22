# analyze_skin_s3.py  (runtime: Python 3.13)
import os, json, logging, boto3
from urllib.parse import unquote_plus

logger = logging.getLogger()
logger.setLevel(logging.INFO)

rekognition = boto3.client("rekognition")
s3 = boto3.client("s3")

MODEL_ARN      = os.environ["MODEL_ARN"]
RESULT_BUCKET  = os.environ["RESULT_BUCKET"]           # = บัคเก็ตเดียวกับที่เก็บรูปก็ได้
RESULT_PREFIX  = os.environ.get("RESULT_PREFIX","results/")
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE","50"))

def handler(event, context):
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key    = unquote_plus(rec["s3"]["object"]["key"])

        # อ่าน metadata (ถ้ามี)
        session_id = None
        user_skin_types = None
        try:
            head = s3.head_object(Bucket=bucket, Key=key)
            md = head.get("Metadata", {})
            session_id = md.get("sessionid")
            user_skin_types = md.get("skintypes")
        except Exception:
            pass

        # อ่านไฟล์ภาพจาก S3 → bytes
        obj = s3.get_object(Bucket=bucket, Key=key)
        img_bytes = obj["Body"].read()

        # วิเคราะห์ด้วยโมเดล
        resp = rekognition.detect_custom_labels(
            ProjectVersionArn=MODEL_ARN,
            Image={"Bytes": img_bytes},
            MinConfidence=MIN_CONFIDENCE
        )
        labels = sorted({lbl["Name"] for lbl in resp.get("CustomLabels", [])})

        # กำหนด key สำหรับผลลัพธ์
        # แทนที่ "uploads/" → "results/" แล้วเติม .json
        if key.startswith("uploads/"):
            out_key = key.replace("uploads/", RESULT_PREFIX, 1) + ".json"
        else:
            out_key = f"{RESULT_PREFIX}{key}.json"

        result = {
            "source": {"bucket": bucket, "key": key, "via": "s3_event"},
            "labels": labels,
            #"meta": {"sessionId": session_id, "skinTypes": user_skin_types}
        }

        s3.put_object(
            Bucket=RESULT_BUCKET,
            Key=out_key,
            Body=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json"
        )
        logger.info(f"Saved: s3://{RESULT_BUCKET}/{out_key}")
    return {"ok": True}
