import os
import json
from collections import Counter, defaultdict
from datetime import datetime

import boto3
import botocore

s3 = boto3.client("s3")

# ========= DEFAULT ENV (ไม่พังตอน import) =========
DEFAULT_BUCKET  = os.getenv("BUCKET")
DEFAULT_DATASET = os.getenv("DATASET_NAME")

# ค่าเริ่มต้น (จะถูกคำนวณใหม่เมื่อรู้ dataset)
DEFAULT_RAW_IMG_PREFIX = None
DEFAULT_RAW_COCO_KEY   = None
DEFAULT_PROC_IMG_PREFIX = None
DEFAULT_REPORT_KEY      = None


# ========= helpers =========
def _list_keys(bucket: str, prefix: str):
    """List object keys under a prefix (non-folder only)."""
    keys = []
    cont = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
        if cont:
            kw["ContinuationToken"] = cont
        resp = s3.list_objects_v2(**kw)
        for it in resp.get("Contents", []):
            k = it["Key"]
            if not k.endswith("/"):
                keys.append(k)
        if not resp.get("IsTruncated"):
            break
        cont = resp.get("NextContinuationToken")
    return keys


def _get_json(bucket: str, key: str):
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read().decode("utf-8"))


def _put_json(bucket: str, key: str, data):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _derive_paths(dataset: str, overrides: dict | None = None):
    """คำนวณ path ทั้งหมดจาก dataset พร้อมรองรับ overrides จาก ENV/event"""
    ov = overrides or {}
    raw_img_prefix = ov.get("RAW_IMG_PREFIX") or f"datasets/{dataset}/raw/images/"
    raw_coco_key   = ov.get("RAW_COCO_KEY")   or f"datasets/{dataset}/raw/annotations/coco.json"
    proc_img_prefix = ov.get("PROC_IMG_PREFIX") or f"datasets/{dataset}/preprocessed/"
    report_key      = ov.get("REPORT_KEY") or f"datasets/{dataset}/manifest/validation_report.json"
    return raw_img_prefix, raw_coco_key, proc_img_prefix, report_key


# ========= main =========
def handler(event, context):
    # ---------- รับค่า config ----------
    bucket  = (event or {}).get("bucket")  or DEFAULT_BUCKET
    dataset = (event or {}).get("dataset") or DEFAULT_DATASET
    if not bucket or not dataset:
        raise ValueError(
            "Missing required config: bucket/dataset. "
            "Set ENV BUCKET & DATASET_NAME or pass in event."
        )

    # รองรับ override prefix/key จาก event หรือ ENV (ถ้ามี)
    overrides = {}
    # จาก ENV (ถ้าตั้งไว้ใน Console)
    for k in ["RAW_IMG_PREFIX", "RAW_COCO_KEY", "PROC_IMG_PREFIX", "REPORT_KEY"]:
        v = os.getenv(k)
        if v:
            overrides[k] = v
    # จาก event มาก่อน (สำคัญกว่า)
    if isinstance(event, dict):
        overrides.update({k: v for k, v in event.items() if k in {
            "RAW_IMG_PREFIX", "RAW_COCO_KEY", "PROC_IMG_PREFIX", "REPORT_KEY"
        }})

    RAW_IMG_PREFIX, RAW_COCO_KEY, PROC_IMG_PREFIX, REPORT_KEY = _derive_paths(dataset, overrides)

    # ---------- ข้อมูลเสริมจากขั้นสร้าง manifest (เพิ่มลงรายงาน) ----------
    train_count = (event or {}).get("train")
    val_count   = (event or {}).get("val")
    balanced    = (event or {}).get("balanced")

    report = {
        "dataset": dataset,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "paths": {
            "raw_images_prefix": RAW_IMG_PREFIX,
            "raw_coco_key": RAW_COCO_KEY,
            "processed_prefix": PROC_IMG_PREFIX,
            "report_key": REPORT_KEY,
        },
        "checks": []
    }

    # ---------- 1) โหลด COCO ----------
    try:
        coco = _get_json(bucket, RAW_COCO_KEY)
    except botocore.exceptions.ClientError as e:
        report["checks"].append({
            "name": "load_coco",
            "ok": False,
            "detail": str(e),
        })
        _put_json(bucket, REPORT_KEY, report)
        return {"ok": False, "note": "cannot load COCO", "report_key": REPORT_KEY}

    imgs = coco.get("images", [])
    anns = coco.get("annotations", [])
    cats = coco.get("categories", [])

    report["checks"].append({
        "name": "load_coco",
        "ok": True,
        "detail": {
            "images": len(imgs),
            "annotations": len(anns),
            "categories": len(cats),
        }
    })

    # ---------- 2) schema keys ----------
    need = {"images", "annotations", "categories"}
    missing = [k for k in need if k not in coco]
    report["checks"].append({
        "name": "schema_required_keys",
        "ok": len(missing) == 0,
        "detail": {"missing": missing}
    })

    # ---------- 3) duplicates ----------
    # ตรวจซ้ำจาก image id และ file_name
    ids = [i.get("id") for i in imgs]
    fns = [i.get("file_name") for i in imgs]
    dup_ids = [k for k, c in Counter(ids).items() if c > 1]
    dup_fns = [k for k, c in Counter(fns).items() if c > 1]
    report["checks"].append({
        "name": "duplicates",
        "ok": not dup_ids and not dup_fns,
        "detail": {"image_id": dup_ids, "file_name": dup_fns}
    })

    # ---------- 4) raw files consistency ----------
    raw_files = _list_keys(bucket, RAW_IMG_PREFIX)
    raw_names = {k.split("/")[-1].lower() for k in raw_files}
    coco_names = {str(i.get("file_name")).split("/")[-1].lower() for i in imgs}

    missing_in_raw = sorted(list(coco_names - raw_names))
    orphan_in_raw  = sorted(list(raw_names - coco_names))
    report["checks"].append({
        "name": "raw_files_consistency",
        "ok": len(missing_in_raw) == 0,
        "detail": {
            "raw_prefix": RAW_IMG_PREFIX,
            "count": {
                "coco_images": len(coco_names),
                "raw_files": len(raw_files)
            },
            "missing_in_raw": missing_in_raw[:50],  # limit preview
            "orphan_in_raw": orphan_in_raw[:50],
        }
    })

    # ---------- 5) processed (preprocessed) consistency ----------
    proc_files = _list_keys(bucket, PROC_IMG_PREFIX + "images/")
    proc_names = {k.split("/")[-1].lower() for k in proc_files}

    missing_in_proc = sorted(list(coco_names - proc_names))
    orphan_in_proc  = sorted(list(proc_names - coco_names))

    report["checks"].append({
        "name": "processed_consistency",
        "ok": len(missing_in_proc) == 0,
        "detail": {
            "proc_prefix": PROC_IMG_PREFIX + "images/",
            "count": {
                "coco_images": len(coco_names),
                "processed_files": len(proc_files)
            },
            "missing_in_processed": missing_in_proc[:50],
            "orphan_in_processed": orphan_in_proc[:50],
        }
    })

    # ---------- 6) สรุปรวม ----------
    summary = {
        "imgs_coco": len(coco_names),
        "imgs_raw": len(raw_files),
        "imgs_processed": len(proc_files),
        "annotations": len(anns),
        "categories": len(cats),
    }
    # ใส่ผลจากขั้นทำ manifest
    if train_count is not None:
        summary["train_manifest"] = int(train_count)
    if val_count is not None:
        summary["val_manifest"] = int(val_count)
    if balanced is not None:
        # รับได้ทั้ง bool/str
        summary["balanced"] = bool(balanced) if isinstance(balanced, bool) else str(balanced).lower() == "true"
    tpc = event.get("train_per_class"); vpc = event.get("val_per_class")
    if tpc: summary["train_per_class"] = tpc
    if vpc: summary["val_per_class"]   = vpc
    report["summary"] = summary

    # ---------- 7) บันทึกรายงาน ----------
    _put_json(bucket, REPORT_KEY, report)

    return {"ok": True, "report_key": REPORT_KEY, "summary": summary}
