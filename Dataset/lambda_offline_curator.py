import os
import io
import json
import zipfile
import tempfile
import boto3
import mimetypes
from pathlib import Path
from datetime import datetime
import time

s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")

# ---------- ENV ----------
BUCKET = os.environ.get("BUCKET", "")  # ถ้าไม่ตั้ง จะใช้จาก event
DATASET_ENV = os.environ.get("DATASET_NAME", "")
PREPROCESS_FN = os.environ.get("PREPROCESS_FN", "preprocess-images")
MANIFEST_FN = os.environ.get("MANIFEST_FN", "coco_to_rek_manifest")
WAIT_PREPROC_READY_SECS = int(os.environ.get("WAIT_PREPROC_READY_SECS", "600"))
IMG_EXTS = [e.strip().lower() for e in os.environ.get("IMG_EXTS", ".jpg,.jpeg,.png").split(",")]

# ---------- helpers ----------
def _guess_ct(fn: str):
    ct, _ = mimetypes.guess_type(fn)
    return ct or "application/octet-stream"

def _put_bytes(bucket, key, body: bytes, ct="application/octet-stream"):
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=ct)

def _put_json(bucket, key, obj):
    _put_bytes(bucket, key, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

def _exists(bucket, key) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def _list_dir(zf: zipfile.ZipFile, prefix: str):
    return [n for n in zf.namelist() if n.startswith(prefix)]

def _merge_cocos(cocos: list):
    """
    รวม COCO หลาย split:
    - รวม categories โดยอาศัย 'name'
    - รีไอดี image/annotation ไม่ให้ชน
    - บังคับ file_name เป็น basename (กัน path ยาว) เพื่อแมตช์กับไฟล์ใน S3
    """
    # รวม categories ตาม name
    name_to_id = {}
    merged_categories = []
    next_cat = 1
    for cset in cocos:
        for c in cset.get("categories", []):
            nm = c["name"]
            if nm not in name_to_id:
                name_to_id[nm] = next_cat
                merged_categories.append({
                    "id": next_cat,
                    "name": nm,
                    "supercategory": c.get("supercategory", nm)
                })
                next_cat += 1

    out_images = []
    out_annotations = []
    next_img = 1
    next_ann = 1

    for cset in cocos:
        # map cat id เก่า -> ใหม่ตามชื่อ
        cat_old_to_new = {c["id"]: name_to_id[c["name"]] for c in cset.get("categories", [])}
        # map image id
        img_old_to_new = {}
        for im in cset.get("images", []):
            new_id = next_img; next_img += 1
            img_old_to_new[im["id"]] = new_id
            out_images.append({
                "id": new_id,
                "file_name": Path(im["file_name"]).name,
                "width": int(im.get("width", 0)),
                "height": int(im.get("height", 0))
            })

        for an in cset.get("annotations", []):
            out_annotations.append({
                "id": next_ann,
                "image_id": img_old_to_new[an["image_id"]],
                "category_id": cat_old_to_new[an["category_id"]],
                "bbox": [float(x) for x in an["bbox"]],
                "iscrowd": int(an.get("iscrowd", 0)),
                "area": float(an.get("area", an["bbox"][2] * an["bbox"][3]))
            })
            next_ann += 1

    return {"images": out_images, "annotations": out_annotations, "categories": merged_categories}

def _derive_dataset_from_key(key: str) -> str:
    # พยายามดึง datasets/<DATASET>/ จาก key เช่น datasets/skin-2025-09/ingest/xxx.zip
    parts = key.split("/")
    if len(parts) >= 3 and parts[0] == "datasets":
        return parts[1]
    return DATASET_ENV or "dataset"

def _wait_for_preprocessed_ready(bucket, dataset, timeout_secs=120):
    key = f"datasets/{dataset}/preprocessed/_READY"
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        if _exists(bucket, key):
            return True
        time.sleep(5)
    return False

# ---------- main handler ----------
def handler(event, context):
    # 1) รับ S3 event
    #    รองรับทั้ง S3 event และการ test ด้วย payload {bucket, key}
    if "Records" in event:
        rec = event["Records"][0]
        bucket = rec["s3"]["bucket"]["name"]
        key = rec["s3"]["object"]["key"]
    else:
        bucket = event.get("bucket") or BUCKET
        key = event.get("key")
    if not bucket or not key:
        return {"ok": False, "error": "missing bucket/key"}

    dataset = _derive_dataset_from_key(key)
    raw_img_prefix = f"datasets/{dataset}/raw/images/"
    raw_ann_key = f"datasets/{dataset}/raw/annotations/coco.json"

    print(f"📦 offline-curator start: bucket={bucket}, key={key}, dataset={dataset}")

    # 2) โหลด ZIP ลง /tmp แล้วแตกไฟล์
    with tempfile.TemporaryDirectory() as td:
        zip_path = os.path.join(td, "ingest.zip")
        s3.download_file(bucket, key, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()

            # หาไฟล์ annotations ของ 3 split
            cand_train = [n for n in names if n.startswith("train/") and n.endswith(".coco.json")]
            cand_valid = [n for n in names if n.startswith("valid/") and n.endswith(".coco.json")]
            cand_test  = [n for n in names if n.startswith("test/")  and n.endswith(".coco.json")]

            cocos = []
            for picks in (cand_train, cand_valid, cand_test):
                if picks:
                    data = json.loads(zf.read(picks[0]).decode("utf-8"))
                    cocos.append(data)

            if not cocos:
                return {"ok": False, "error": "no *_annotations.coco.json found in train/valid/test"}

            # 3) รวม COCO
            merged = _merge_cocos(cocos)
            print(f"🧾 merged COCO: images={len(merged['images'])}, anns={len(merged['annotations'])}, cats={len(merged['categories'])}")

            # 4) อัปโหลดภาพที่ถูกอ้างใน COCO เท่านั้น
            needed = {Path(im["file_name"]).name for im in merged["images"]}
            sent = 0
            for n in names:
                # คัดเฉพาะไฟล์ภาพภายใต้ train/valid/test และเป็นชื่อที่อยู่ใน needed
                if not (n.startswith("train/") or n.startswith("valid/") or n.startswith("test/")):
                    continue
                if n.endswith("/"):
                    continue
                ext = Path(n).suffix.lower()
                if ext not in IMG_EXTS:
                    continue
                base = Path(n).name
                if base not in needed:
                    continue

                body = zf.read(n)
                out_key = raw_img_prefix + base
                _put_bytes(bucket, out_key, body, _guess_ct(base))
                sent += 1
                # log แบบสั้นให้ดูความคืบหน้า
                if sent % 100 == 0:
                    print(f"✅ uploaded {sent} images ...")

            print(f"✅ uploaded images: {sent}")

            # 5) อัปโหลด merged COCO
            _put_json(bucket, raw_ann_key, merged)
            print(f"✅ wrote COCO: s3://{bucket}/{raw_ann_key}")

            # 6) เขียน RAW _READY
            _put_bytes(bucket, f"datasets/{dataset}/raw/_READY", b"", "text/plain")
            print(f"🏁 raw READY flag written")

    # 7) invoke preprocess ต่อ (ถ้าตั้ง ENV ไว้)
    if PREPROCESS_FN:
        payload = {"bucket": bucket, "dataset": dataset}
        try:
            lambda_client.invoke(
                FunctionName=PREPROCESS_FN,
                InvocationType="Event",
                Payload=json.dumps(payload).encode("utf-8")
            )
            print(f"📤 invoked {PREPROCESS_FN}")
        except Exception as e:
            print("WARN: cannot invoke preprocess:", e)

    # 8) (ออปชัน) รอ preprocessed/_READY แล้วค่อย invoke manifest
    if MANIFEST_FN:
        ready = _wait_for_preprocessed_ready(bucket, dataset, WAIT_PREPROC_READY_SECS)
        if not ready:
            print(f"⏱️ preprocessed/_READY not found within {WAIT_PREPROC_READY_SECS}s; skip invoking {MANIFEST_FN}")
        else:
            try:
                payload2 = {"bucket": bucket, "dataset": dataset}
                lambda_client.invoke(
                    FunctionName=MANIFEST_FN,
                    InvocationType="Event",
                    Payload=json.dumps(payload2).encode("utf-8")
                )
                print(f"📤 invoked {MANIFEST_FN}")
            except Exception as e:
                print("WARN: cannot invoke manifest:", e)

    return {"ok": True, "bucket": bucket, "dataset": dataset, "uploaded_images": sent}
