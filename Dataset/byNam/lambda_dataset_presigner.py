import os, json, boto3, datetime as dt

s3 = boto3.client("s3")

OFFLINE_BUCKET = os.environ.get("OFFLINE_BUCKET", "dermavision-offline")
MAX_DATASET_SIZE = int(os.environ.get("MAX_DATASET_SIZE", str(500 * 1024 * 1024)))  # 500MB

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }

def handler(event, context):
    try:
        qs = event.get("queryStringParameters") or {}
        dataset = qs.get("dataset", "skin-2025-09")
        user_id = qs.get("userId", "ingestor")

        # key → landing/<dataset>-<timestamp>.zip
        now = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        key = f"landing/{dataset}-{now}.zip"
        ctype = "application/zip"

        presigned = s3.generate_presigned_post(
            Bucket=OFFLINE_BUCKET,
            Key=key,
            Fields={
                "Content-Type": ctype,
                "x-amz-tagging": "project=dermavision&ingestion=offline_dataset&stage=landing",
                "x-amz-meta-user-id": user_id,
                "x-amz-meta-dataset": dataset,
                "x-amz-meta-source": "local-ingest"
            },
            Conditions=[
                ["content-length-range", 0, MAX_DATASET_SIZE],
                {"Content-Type": ctype},
                {"x-amz-tagging": "project=dermavision&ingestion=offline_dataset&stage=landing"},
                ["starts-with", "$x-amz-meta-user-id", ""],
                ["starts-with", "$x-amz-meta-dataset", ""],
                ["starts-with", "$x-amz-meta-source", ""]
            ],
            ExpiresIn=600,
        )
        return _resp(200, {"bucket": OFFLINE_BUCKET, "key": key, "upload": presigned})

    except Exception as e:
        return _resp(500, {"error": str(e)})
