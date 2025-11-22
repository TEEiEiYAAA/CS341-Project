# forward_to_analyzer.py  (Account A)
import os, json, logging, urllib.request, boto3
from urllib.parse import unquote_plus

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client(s3)

API_ENDPOINT    = os.environ[API_ENDPOINT]
EXPIRES         = int(os.environ.get(PRESIGN_EXPIRES, 300))

def _post_json(url, payload dict)
    data = json.dumps(payload).encode(utf-8)
    req = urllib.request.Request(url, data=data, headers={Content-Type applicationjson}, method=POST)
    with urllib.request.urlopen(req, timeout=10) as resp
        return resp.read().decode(utf-8)

def handler(event, context)
    for rec in event[Records]
        bucket = rec[s3][bucket][name]
        key    = unquote_plus(rec[s3][object][key])

        # สร้าง presigned GET URL ส่งให้ Account B
        presigned = s3.generate_presigned_url(
            get_object,
            Params={Bucket bucket, Key key},
            ExpiresIn=EXPIRES
        )

        # (optional) ดึง metadata เผื่อมี sessionskinTypes แนบมา
        session_id = None
        user_skin_types = None
        try
            head = s3.head_object(Bucket=bucket, Key=key)
            md = head.get(Metadata, {})
            session_id = md.get(sessionid)
            user_skin_types = md.get(skintypes)
        except Exception
            pass

        payload = {
            image_url presigned,
            source_bucket bucket,
            source_key key,
            sessionId session_id,
            skinTypes user_skin_types
        }

        try
            logger.info(fPOST {API_ENDPOINT} for {key})
            _post_json(API_ENDPOINT, payload)
        except Exception as e
            logger.exception(fCall API failed for {key} {e})

    return {status ok}