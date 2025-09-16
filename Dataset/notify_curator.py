# notify_curator.py
import json, os, boto3, traceback

lam = boto3.client("lambda")
OFFLINE_FN = os.environ.get("OFFLINE_CURATOR_FN", "offline-curator")

def handler(event, context):
    try:
        print("EVENT:", json.dumps(event))
        body = event.get("body", event)
        if isinstance(body, str):
            body = json.loads(body or "{}")

        bucket = body.get("bucket")
        key = body.get("key")
        payload = {}
        if bucket and key:
            payload = {"bucket": bucket, "key": key}

        resp = lam.invoke(
            FunctionName=OFFLINE_FN,
            InvocationType="Event",  # async
            Payload=json.dumps(payload).encode("utf-8")
        )
        print("invoke response (meta):", resp.get("StatusCode"))

        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True, "forwarded_to": OFFLINE_FN})
        }
    except Exception as e:
        print("ERR:", e)
        traceback.print_exc()
        return {
            "statusCode": 500,
            "body": json.dumps({"ok": False, "error": str(e)})
        }
