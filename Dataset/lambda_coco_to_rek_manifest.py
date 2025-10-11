import os
import io
import json
import random
import boto3
import time
import re
import difflib
from datetime import datetime

s3 = boto3.client("s3")

# --------- CONFIG ---------
BUCKET    = os.environ.get("BUCKET", "dermavision-offline")
DATASET   = os.environ.get("DATASET_NAME", "skin-2025-09")
VAL_SPLIT = float(os.environ.get("VAL_SPLIT", "0.1"))

ANN_KEY    = f"datasets/{DATASET}/raw/annotations/coco.json"
IMG_PREFIX = f"datasets/{DATASET}/preprocessed/images/"
OUT_PREFIX = f"datasets/{DATASET}/manifest/"
READY_KEY  = f"datasets/{DATASET}/preprocessed/_READY"

LABEL_ATTR = "bounding-box"  # Rekognition default

# ---- Bounding box policy (adaptive) ----
MIN_W = int(os.environ.get("MIN_BOX_W", "8"))     # px
MIN_H = int(os.environ.get("MIN_BOX_H", "8"))     # px
MAX_PER_CLASS = int(os.environ.get("MAX_PER_CLASS", "25"))  # กัน bias ต่อคลาส
MAX_TOTAL     = int(os.environ.get("MAX_TOTAL", "50"))      # <= REK limit
# ----------------------------------------

# ---------- Optional Pillow ----------
try:
    from PIL import Image
    from io import BytesIO
    _PIL_OK = True
except Exception:
    _PIL_OK = False
# ------------------------------------

# ---------- helpers ----------
def _put_jsonl(objs, key):
    buf = io.StringIO()
    for o in objs:
        buf.write(json.dumps(o, ensure_ascii=False) + "\n")
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=buf.getvalue().encode("utf-8"),
        ContentType="application/json"
    )

def _s3_exists(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def _list_keys(prefix):
    cont = None
    keys = []
    while True:
        kw = {"Bucket": BUCKET, "Prefix": prefix, "MaxKeys": 1000}
        if cont:
            kw["ContinuationToken"] = cont
        r = s3.list_objects_v2(**kw)
        keys += [it["Key"] for it in r.get("Contents", []) if not it["Key"].endswith("/")]
        if not r.get("IsTruncated"):
            break
        cont = r.get("NextContinuationToken")
    return keys

RF_RE = re.compile(r"\brf\.([a-f0-9]{6,})", re.IGNORECASE)
def _rf_hash(name: str):
    m = RF_RE.search(name)
    return m.group(1).lower() if m else None

def _normalize_filename(name: str) -> str:
    n = name.lower()
    n = n.replace("_jpg.", "-jpg.").replace("_jpeg.", "-jpeg.").replace("_png.", "-png.")
    n = n.replace("__", "_")
    return os.path.basename(n)

def _best_match(target: str, candidates):
    got = difflib.get_close_matches(target, candidates, n=1, cutoff=0.6)
    return got[0] if got else None

def _get_image_size_true(bucket: str, key: str, fallback_wh):
    """พยายามอ่านขนาดรูปจริงจาก S3; ถ้าอ่านไม่ได้ ให้คืนค่าจาก COCO"""
    if not _PIL_OK:
        return fallback_wh
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        with Image.open(BytesIO(obj["Body"].read())) as im:
            w, h = im.size
        return int(w), int(h)
    except Exception:
        return fallback_wh

def _clip_box(x, y, w, h, W, H):
    """บังคับ bbox ให้อยู่ในขอบภาพและเป็น int ทั้งหมด"""
    x = int(round(x)); y = int(round(y))
    w = int(round(w)); h = int(round(h))
    if W <= 0 or H <= 0:
        return 0, 0, 0, 0
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    return x, y, w, h

def _area(b):  # สำหรับเรียงเลือกรายการใหญ่ก่อน
    return b["width"] * b["height"]
# ----------------------------

def handler(event, context):
    # 0) รอ READY (กัน manifest รันก่อนรูปพร้อม)
    for _ in range(12):  # ~60s
        if _s3_exists(BUCKET, READY_KEY):
            break
        time.sleep(5)

    # 1) โหลด COCO
    coco_obj = s3.get_object(Bucket=BUCKET, Key=ANN_KEY)
    coco = json.loads(coco_obj["Body"].read().decode("utf-8"))

    # 2) index คีย์รูปที่มีอยู่จริงใน S3
    img_keys = _list_keys(IMG_PREFIX)
    if not img_keys:
        return {"ok": False, "note": "no preprocessed images found"}

    by_hash = {}
    by_name = {}
    for k in img_keys:
        b = os.path.basename(k)
        by_name[b.lower()] = k
        h = _rf_hash(b)
        if h:
            by_hash[h] = k
    name_set = set(by_name.keys())

    # 3) เตรียม categories/annotations จาก COCO
    img_map = {i["id"]: i for i in coco["images"]}
    cats = [c["name"] for c in coco["categories"]]
    class_to_id = {name: i for i, name in enumerate(cats)}
    id_to_name = {i: name for name, i in class_to_id.items()}

    per_img = {i: [] for i in img_map.keys()}
    for a in coco.get("annotations", []):
        cname = next(c["name"] for c in coco["categories"] if c["id"] == a["category_id"])
        cid = class_to_id[cname]
        x, y, w, h = a["bbox"]
        per_img[a["image_id"]].append({
            "class_id": cid,
            "left": x, "top": y, "width": w, "height": h
        })

    # 4) ประกอบรายการ manifest
    items = []
    dropped = 0
    today = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    for img_id, anns in per_img.items():
        meta = img_map[img_id]
        rf_file = meta["file_name"]
        w0 = int(meta.get("width", 0))
        h0 = int(meta.get("height", 0))

        # หา key จริงใน S3: rf-hash → normalize → fuzzy
        real_key = None
        hsh = _rf_hash(rf_file)
        if hsh and hsh in by_hash:
            real_key = by_hash[hsh]
        else:
            norm = _normalize_filename(rf_file)
            real_key = by_name.get(norm)
            if not real_key:
                cand = _best_match(norm, name_set)
                if cand:
                    real_key = by_name[cand]

        if not real_key:
            dropped += 1
            print(f"⚠️ drop(no-key): {rf_file}")
            continue

        # ขนาดรูปจริง (fallback ไป COCO ถ้าอ่านไม่ได้)
        W, H = _get_image_size_true(BUCKET, real_key, (w0, h0))
        if W <= 0 or H <= 0:
            dropped += 1
            print(f"⚠️ drop(bad-size): s3://{BUCKET}/{real_key} (COCO {w0}x{h0})")
            continue

        # แปลง/คลิป bbox
        anns_int = []
        for bb in anns:
            x, y, w, h = _clip_box(bb["left"], bb["top"], bb["width"], bb["height"], W, H)
            if w <= 0 or h <= 0:
                continue
            anns_int.append({
                "class_id": int(bb["class_id"]),
                "left": x, "top": y, "width": w, "height": h
            })

        if not anns_int:  # กัน NO_VALID_LABEL_ATTRIBUTES
            dropped += 1
            print(f"⚠️ drop(no-boxes): s3://{BUCKET}/{real_key}")
            continue

        # ---------- ADAPTIVE TRIM ----------
        orig_cnt = len(anns_int)
        dropped_local = 0

        # กรองบ็อกซ์จิ๋วเฉพาะเมื่อจำนวนรวมเกินลิมิต
        if len(anns_int) > MAX_TOTAL:
            before = len(anns_int)
            anns_int = [b for b in anns_int if b["width"] >= MIN_W and b["height"] >= MIN_H]
            dropped_local += before - len(anns_int)

        # จำกัดต่อคลาส (เลือกอันใหญ่ก่อน)
        if len(anns_int) > MAX_TOTAL:
            by_cls = {}
            for b in anns_int:
                by_cls.setdefault(b["class_id"], []).append(b)
            kept = []
            for cid, boxes in by_cls.items():
                boxes.sort(key=_area, reverse=True)
                keep_c = boxes[:MAX_PER_CLASS]
                dropped_local += max(0, len(boxes) - len(keep_c))
                kept.extend(keep_c)
            anns_int = kept

        # จำกัดจำนวนรวม
        if len(anns_int) > MAX_TOTAL:
            anns_int.sort(key=_area, reverse=True)
            dropped_local += len(anns_int) - MAX_TOTAL
            anns_int = anns_int[:MAX_TOTAL]

        if dropped_local > 0:
            print(f"🧹 trim({rf_file}): {orig_cnt} → {len(anns_int)} "
                  f"(dropped={dropped_local}, min={MIN_W}x{MIN_H}, "
                  f"per_class≤{MAX_PER_CLASS}, total≤{MAX_TOTAL})")

        if not anns_int:
            dropped += 1
            print(f"⚠️ drop(after-trim-empty): s3://{BUCKET}/{real_key}")
            continue
        # ---------- /ADAPTIVE TRIM ----------

        entry = {
            "source-ref": f"s3://{BUCKET}/{real_key}",
            LABEL_ATTR: {
                "annotations": anns_int,
                "image_size": [{"width": W, "height": H, "depth": 3}],
            },
            f"{LABEL_ATTR}-metadata": {
                "objects": [{"confidence": 1} for _ in anns_int],
                "class-map": {str(i): id_to_name[i] for i in range(len(cats))},
                "human-annotated": "yes",
                "creation-date": today,
                "type": "groundtruth/object-detection",
                "job-name": LABEL_ATTR
            }
        }
        items.append(entry)
        print(f"✅ {real_key}  boxes={len(anns_int)}  size={W}x{H}")

    if not items:
        return {"ok": False, "note": "no valid items after matching", "dropped": dropped}

    # split & write
    random.shuffle(items)
    n_val = max(1, int(len(items) * VAL_SPLIT))
    val_items = items[:n_val]
    train_items = items[n_val:]

    _put_jsonl(train_items, f"{OUT_PREFIX}train.manifest")
    _put_jsonl(val_items,   f"{OUT_PREFIX}val.manifest")

    # labels helper
    labels_txt = "\n".join(cats) + "\n"
    s3.put_object(Bucket=BUCKET, Key=f"{OUT_PREFIX}labels.txt",
                  Body=labels_txt.encode("utf-8"), ContentType="text/plain")
    s3.put_object(Bucket=BUCKET, Key=f"{OUT_PREFIX}labels.json",
                  Body=json.dumps(cats, ensure_ascii=False, indent=2).encode("utf-8"),
                  ContentType="application/json")
    print(f"🧾 classes ({len(cats)}): {', '.join(cats)}")

    # optional: invoke validate
    try:
        lambda_client = boto3.client("lambda")
        VALIDATE_FN = os.environ.get("VALIDATE_FN", "validate-dataset")
        payload = {"bucket": BUCKET, "dataset": DATASET,
                   "train": len(train_items), "val": len(val_items), "dropped": dropped}
        resp = lambda_client.invoke(FunctionName=VALIDATE_FN,
                                    InvocationType="Event",
                                    Payload=json.dumps(payload).encode("utf-8"))
        print(f"📤 invoked {VALIDATE_FN} status={resp.get('StatusCode')}")
    except Exception as e:
        print("WARN: cannot invoke validate-dataset:", e)

    return {"ok": True, "train": len(train_items), "val": len(val_items),
            "dropped": dropped, "classes": cats}
