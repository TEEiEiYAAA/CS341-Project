import json
import os
import boto3
from urllib.parse import unquote

s3 = boto3.client('s3')
BUCKET = os.environ.get("UPLOAD_BUCKET", "user-pic-dermavision")
KEY_PREFIX = os.environ.get("KEY_PREFIX", "uploads/")
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")

def _headers():
    return {
        "Access-Control-Allow-Origin": CORS_ORIGIN,
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }

def lambda_handler(event, context):
    # รองรับ preflight จากเบราว์เซอร์
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": _headers(), "body": ""}

    qs = event.get("queryStringParameters") or {}
    filename = qs.get("filename")
    content_type = qs.get("contentType", "application/octet-stream")

    if not filename:
        return {"statusCode": 400, "headers": _headers(),
                "body": json.dumps({"error": "missing filename"})}

    # กัน path traversal / space แปลกๆ
    filename = unquote(filename).split("/")[-1]
    key = f"{KEY_PREFIX}{filename}"

    url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=3600  # อายุ URL 1 ชม.
    )

    return {
        "statusCode": 200,
        "headers": _headers(),
        "body": json.dumps({"uploadUrl": url, "objectKey": key})
    }
