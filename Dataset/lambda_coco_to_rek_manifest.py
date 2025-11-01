import os, io, json, random, boto3, time, re, difflib
from datetime import datetime
from collections import defaultdict

s3 = boto3.client("s3")

# -------- CONFIG --------
BUCKET    = os.environ.get("BUCKET", "dermavision-offline")
DATASET   = os.environ.get("DATASET_NAME", "skin-2025-09")
VAL_SPLIT = float(os.environ.get("VAL_SPLIT", "0.1"))

ANN_KEY   = os.environ.get("ANN_KEY", f"datasets/{DATASET}/raw/annotations/coco.json")
IMG_PREFIX = f"datasets/{DATASET}/preprocessed/images/"
OUT_PREFIX = f"datasets/{DATASET}/manifest/"
READY_KEY  = f"datasets/{DATASET}/preprocessed/_READY"

LABEL_ATTR = "bounding-box"  # Rekognition spec key

# ---- Balance controls (ENV) ----
ENABLE_BALANCE     = os.environ.get("ENABLE_BALANCE", "true").lower() == "true"
PER_CLASS_CAP      = int(os.environ.get("PER_CLASS_CAP", "90"))   # ภาพ/คลาส สูงสุด
MIN_CLASS_IMAGES   = int(os.environ.get("MIN_CLASS_IMAGES", "40")) # ตัดคลาสที่ภาพน้อยเกินไป
MIN_BOX_PX         = int(os.environ.get("MIN_BOX_PX", "6"))        # ตัดกล่องเล็กจิ๋ว
MAX_BOX_PER_IMAGE  = int(os.environ.get("MAX_BOX_PER_IMAGE", "50"))# กัน overflow Rekognition
# -------------------------------

# -------- helpers ----------
def _put_jsonl(objs, key):
    buf = io.StringIO()
    for o in objs:
        buf.write(json.dumps(o, ensure_ascii=False) + "\n")
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue().encode("utf-8"),
                ContentType="application/json")

def _s3_exists(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def _list_keys(prefix):
    cont=None; keys=[]
    while True:
        kw={"Bucket":BUCKET,"Prefix":prefix,"MaxKeys":1000}
        if cont: kw["ContinuationToken"]=cont
        r=s3.list_objects_v2(**kw)
        keys += [it["Key"] for it in r.get("Contents",[]) if not it["Key"].endswith("/")]
        if not r.get("IsTruncated"): break
        cont=r.get("NextContinuationToken")
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

def _clip_box(x, y, w, h, W, H):
    x = int(round(x)); y = int(round(y))
    w = int(round(w)); h = int(round(h))
    if W <= 0 or H <= 0: return 0,0,0,0
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    return x, y, w, h
# ---------------------------

def handler(event, context):
    # 0) รอรูปให้พร้อม (READY + มีไฟล์จริง)
    for _ in range(12):  # ~60s
        if _s3_exists(BUCKET, READY_KEY) and _list_keys(IMG_PREFIX):
            break
        time.sleep(5)
    if not _s3_exists(BUCKET, READY_KEY):
        return {"ok": False, "note": "images not ready (no READY flag)"}

    img_keys = _list_keys(IMG_PREFIX)
    if not img_keys:
        return {"ok": False, "note": "no preprocessed images found"}

    by_hash, by_name = {}, {}
    for k in img_keys:
        b = os.path.basename(k)
        by_name[b.lower()] = k
        h = _rf_hash(b)
        if h: by_hash[h] = k
    name_set = set(by_name.keys())

    # 1) โหลด COCO
    coco_obj = s3.get_object(Bucket=BUCKET, Key=ANN_KEY)
    coco = json.loads(coco_obj["Body"].read().decode("utf-8"))
    print(f"📘 loaded {ANN_KEY}: {len(coco.get('images',[]))} images, {len(coco.get('annotations',[]))} anns, {len(coco.get('categories',[]))} classes")

    # 2) map image & category
    imgs = {i["id"]: i for i in coco["images"]}
    cats = [c["name"] for c in coco["categories"]]
    class_to_id = {name: i for i, name in enumerate(cats)}
    id_to_name = {i: name for name, i in class_to_id.items()}

    # 3) รวม annotations ต่อภาพ + ตัดกล่องเล็ก + กัน overflow
    anns_by_img = defaultdict(list)
    for a in coco.get("annotations", []):
        # map category id → index ใน class list (กรณี COCO มี id กระโดด)
        cname = next(c["name"] for c in coco["categories"] if c["id"] == a["category_id"])
        cid = class_to_id[cname]
        x,y,w,h = a["bbox"]
        if w < MIN_BOX_PX or h < MIN_BOX_PX:
            continue
        anns_by_img[a["image_id"]].append({"class_id": cid, "left": x, "top": y, "width": w, "height": h})

    # 4) (option) balance: เลือกภาพแบบสมดุลรายคลาส
    selected_img_ids = set(imgs.keys())
    if ENABLE_BALANCE:
        imgs_by_class = defaultdict(set)
        for img_id, boxes in anns_by_img.items():
            for bb in boxes:
                imgs_by_class[bb["class_id"]].add(img_id)

        # ตัดคลาสที่มีภาพน้อยกว่ากำหนด
        valid_class_ids = {cid for cid, s in imgs_by_class.items() if len(s) >= MIN_CLASS_IMAGES}
        if not valid_class_ids:
            print("⚠️ no category passes MIN_CLASS_IMAGES; skip balance")
        else:
            # ทำ pool ต่อคลาส
            pools = {cid: list(imgs_by_class[cid]) for cid in valid_class_ids}
            for p in pools.values(): random.shuffle(p)
            counts = {cid: 0 for cid in pools}
            chosen = set()
            active = True
            while active:
                active = False
                for cid, pool in pools.items():
                    if counts[cid] >= PER_CLASS_CAP: 
                        continue
                    while pool and pool[-1] in chosen:
                        pool.pop()
                    if pool:
                        chosen.add(pool.pop())
                        counts[cid] += 1
                        active = True
            selected_img_ids = chosen if chosen else selected_img_ids
            print(f"🪄 balance: selected {len(selected_img_ids)} images with cap={PER_CLASS_CAP}, min_class_images={MIN_CLASS_IMAGES}")

    # 5) ประกอบ manifest โดยแมตช์ชื่อไฟล์ 3 ชั้น (hash → normalize → fuzzy)
    items = []
    dropped = 0
    today = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    for img_id in selected_img_ids:
        if img_id not in imgs: 
            continue
        meta = imgs[img_id]
        rf_file = meta["file_name"]
        w0 = int(meta.get("width", 0)); h0 = int(meta.get("height", 0))

        # หา key จริงใน S3
        real_key = None
        hsh = _rf_hash(rf_file)
        if hsh and hsh in by_hash:
            real_key = by_hash[hsh]
        else:
            norm = _normalize_filename(rf_file)
            real_key = by_name.get(norm)
            if not real_key:
                cand = _best_match(norm, name_set)
                if cand: real_key = by_name[cand]

        if not real_key:
            dropped += 1
            print(f"⚠️ drop(no-key): {rf_file}")
            continue

        # กล่องของภาพนี้
        boxes = anns_by_img.get(img_id, [])
        if not boxes:
            dropped += 1
            print(f"⚠️ drop(no-boxes): s3://{BUCKET}/{real_key}")
            continue

        # clip ให้อยู่ในขอบภาพ + กัน overflow 50 กล่อง
        W, H = w0, h0
        fixed = []
        for bb in boxes:
            x,y,w,h = _clip_box(bb["left"], bb["top"], bb["width"], bb["height"], W, H)
            if w <= 0 or h <= 0: 
                continue
            fixed.append({"class_id": int(bb["class_id"]), "left": x, "top": y, "width": w, "height": h})
        if not fixed:
            dropped += 1
            print(f"⚠️ drop(no-valid-boxes): s3://{BUCKET}/{real_key}")
            continue

        if len(fixed) > MAX_BOX_PER_IMAGE:
            fixed = fixed[:MAX_BOX_PER_IMAGE]

        entry = {
            "source-ref": f"s3://{BUCKET}/{real_key}",
            LABEL_ATTR: {
                "annotations": fixed,
                "image_size": [{"width": W, "height": H, "depth": 3}],
            },
            f"{LABEL_ATTR}-metadata": {
                "objects": [{"confidence": 1} for _ in fixed],
                "class-map": {str(i): id_to_name[i] for i in range(len(cats))},
                "human-annotated": "yes",
                "creation-date": today,
                "type": "groundtruth/object-detection",
                "job-name": LABEL_ATTR
            }
        }
        items.append(entry)
        print(f"✅ {real_key}  boxes={len(fixed)}  size={W}x{H}")

    if not items:
        return {"ok": False, "note": "no valid items after matching/balancing", "dropped": dropped}

    # 6) split & write
    random.shuffle(items)
    n_val = max(1, int(len(items) * VAL_SPLIT))
    val_items = items[:n_val]
    train_items = items[n_val:]

    _put_jsonl(train_items, f"{OUT_PREFIX}train.manifest")
    _put_jsonl(val_items,   f"{OUT_PREFIX}val.manifest")

    # หลังได้ train_items / val_items
    def count_per_class(items):
        from collections import Counter
        c = Counter()
        for it in items:
            for bb in it[LABEL_ATTR]["annotations"]:
                c[ id_to_name[bb["class_id"]] ] += 1
        return dict(c)

    train_per_class = count_per_class(train_items)
    val_per_class   = count_per_class(val_items)

    # labels helper
    labels_txt = "\n".join(cats) + "\n"
    s3.put_object(Bucket=BUCKET, Key=f"{OUT_PREFIX}labels.txt",
                Body=labels_txt.encode("utf-8"), ContentType="text/plain")
    s3.put_object(Bucket=BUCKET, Key=f"{OUT_PREFIX}labels.json",
                Body=json.dumps(cats, ensure_ascii=False, indent=2).encode("utf-8"),
                ContentType="application/json")
    print(f"🧾 classes ({len(cats)}): {', '.join(cats)}")

    # 7) optional: invoke validate
    try:
        lambda_client = boto3.client("lambda")
        VALIDATE_FN = os.environ.get("VALIDATE_FN", "validate_dataset")
        payload = {"bucket": BUCKET, "dataset": DATASET,
                "train": len(train_items), "val": len(val_items), 
                "balanced": ENABLE_BALANCE, "dropped": dropped,
                "train_per_class": train_per_class, "val_per_class": val_per_class}
        resp = lambda_client.invoke(FunctionName=VALIDATE_FN,
                                    InvocationType="Event",
                                    Payload=json.dumps(payload).encode("utf-8"))
        print(f"📤 invoked {VALIDATE_FN} status={resp.get('StatusCode')}")
    except Exception as e:
        print("WARN: cannot invoke validate_dataset:", e)

    return {"ok": True, "train": len(train_items), "val": len(val_items),
            "dropped": dropped, "classes": cats, "balanced": ENABLE_BALANCE}