import os, json, boto3
from collections import Counter, defaultdict

s3 = boto3.client("s3")

BUCKET = os.environ["BUCKET"]
DATASET = os.environ["DATASET_NAME"]
RAW_IMG_PREFIX = os.environ.get("RAW_IMG_PREFIX", f"datasets/{DATASET}/raw/images/")
RAW_COCO_KEY   = os.environ.get("RAW_COCO_KEY",   f"datasets/{DATASET}/raw/annotations/coco.json")
PROC_IMG_PREFIX= os.environ.get("PROC_IMG_PREFIX",f"datasets/{DATASET}/processed/")
REPORT_KEY     = os.environ.get("REPORT_KEY",     f"datasets/{DATASET}/manifest/validation_report.json")

def list_s3_keys(prefix):
    keys = []
    token = None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": prefix, "MaxKeys": 1000}
        if token: kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        for it in r.get("Contents", []):
            k = it["Key"]
            if k.endswith("/"): 
                continue
            keys.append(k)
        if not r.get("IsTruncated"): break
        token = r.get("NextContinuationToken")
    return keys

def load_json(key):
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return json.loads(obj["Body"].read())

def handler(event, context):
    report = {
        "dataset": DATASET,
        "checks": [],
        "summary": {}
    }

    # ---------- 1) โหลด COCO ----------
    try:
        coco = load_json(RAW_COCO_KEY)
        images = coco.get("images", [])
        anns   = coco.get("annotations", [])
        cats   = coco.get("categories", [])
    except Exception as e:
        report["checks"].append({"name":"load_coco", "ok":False, "error":str(e)})
        write_report(report)
        return {"ok": False, "report": report}

    report["checks"].append({"name":"load_coco", "ok":True, "counts":{
        "images": len(images), "annotations": len(anns), "categories": len(cats)
    }})

    # ---------- 2) Missing keys / Schema drift ----------
    schema_ok = True
    missing = {"images": [], "annotations": [], "categories": []}

    for im in images:
        for key in ("id","file_name"):
            if key not in im:
                schema_ok = False
                missing["images"].append({"image": im.get("id"), "missing": key})
    for an in anns:
        for key in ("id","image_id","category_id"):
            if key not in an:
                schema_ok = False
                missing["annotations"].append({"ann": an.get("id"), "missing": key})
    for ct in cats:
        for key in ("id","name"):
            if key not in ct:
                schema_ok = False
                missing["categories"].append({"cat": ct.get("id"), "missing": key})

    report["checks"].append({"name":"schema_required_keys", "ok": schema_ok, "detail": missing})

    # ---------- 3) Duplicate (image_id, file_name, ann id) ----------
    img_ids = Counter([im.get("id") for im in images])
    img_names = Counter([im.get("file_name") for im in images])
    ann_ids = Counter([an.get("id") for an in anns])

    dup = {
        "image_id": [k for k,c in img_ids.items() if c>1],
        "file_name": [k for k,c in img_names.items() if c>1],
        "ann_id": [k for k,c in ann_ids.items() if c>1]
    }
    dup_ok = all(len(v)==0 for v in dup.values())
    report["checks"].append({"name":"duplicate", "ok": dup_ok, "detail": dup})

    # ---------- 4) Missing files in S3/raw/images ----------
    raw_img_keys = list_s3_keys(RAW_IMG_PREFIX)
    raw_set = set(k.split("/")[-1] for k in raw_img_keys)
    coco_set = set(im["file_name"] for im in images if "file_name" in im)

    missing_in_s3 = sorted(list(coco_set - raw_set))
    orphan_in_s3  = sorted(list(raw_set - coco_set))

    report["checks"].append({
        "name":"raw_files_consistency",
        "ok": len(missing_in_s3)==0,
        "missing_in_s3": missing_in_s3[:50],
        "orphan_in_s3": orphan_in_s3[:50],
        "counts": {"coco_files": len(coco_set), "raw_files": len(raw_set)}
    })

    # ---------- 5) ตรวจ processed เทียบ raw (จำนวน/ตัวอย่างชื่อ) ----------
    proc_keys = list_s3_keys(PROC_IMG_PREFIX)
    proc_names = set(k.split("/")[-1] for k in proc_keys)
    diff_proc = {
        "missing_in_processed": sorted(list(raw_set - proc_names))[:50],
        "orphan_in_processed":  sorted(list(proc_names - raw_set))[:50],
    }
    proc_ok = (len(diff_proc["missing_in_processed"])==0)
    report["checks"].append({"name":"processed_consistency", "ok": proc_ok, "detail": diff_proc,
                             "counts": {"processed_files": len(proc_names)}})

    # ---------- 6) Summary ----------
    report["summary"] = {
        "ok": all(ch["ok"] for ch in report["checks"]),
        "images_coco": len(images),
        "images_raw": len(raw_set),
        "images_processed": len(proc_names),
        "annotations": len(anns),
        "categories": len(cats)
    }

    write_report(report)
    return {"ok": report["summary"]["ok"], "report_key": REPORT_KEY, "summary": report["summary"]}

def write_report(report):
    s3.put_object(
        Bucket=BUCKET, Key=REPORT_KEY,
        Body=(json.dumps(report, ensure_ascii=False, indent=2)).encode("utf-8"),
        ContentType="application/json"
    )
