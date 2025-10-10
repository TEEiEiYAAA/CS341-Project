import os, io, json, random, boto3
from datetime import datetime

s3 = boto3.client("s3")

BUCKET = os.environ.get("BUCKET", "dermavision-offline")
DATASET = os.environ.get("DATASET_NAME", "skin-2025-09")
ANN_KEY = f"datasets/{DATASET}/raw/annotations/coco.json"
IMG_PREFIX = f"datasets/{DATASET}/preprocessed/images/"
OUT_PREFIX = f"datasets/{DATASET}/manifest/"
JOB = os.environ.get("JOB_NAME", "skin-job")
VAL_SPLIT = float(os.environ.get("VAL_SPLIT", "0.1"))

def _put_jsonl(objs, key):
    buf = io.StringIO()
    for o in objs:
        buf.write(json.dumps(o, ensure_ascii=False) + "\n")
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue().encode("utf-8"),
                  ContentType="application/json")

def handler(event, context):
    # 1) โหลด COCO
    coco_obj = s3.get_object(Bucket=BUCKET, Key=ANN_KEY)
    coco = json.loads(coco_obj["Body"].read().decode("utf-8"))

    # map พื้นฐาน
    img_map = {i["id"]: {"file": i["file_name"], "w": i["width"], "h": i["height"]} for i in coco["images"]}
    cats = [c["name"] for c in coco["categories"]]
    class_to_id = {name: i for i, name in enumerate(cats)}
    id_to_name = {i: name for name, i in class_to_id.items()}

    # รวม annotation ต่อรูป
    per_img = {i: [] for i in img_map.keys()}
    for a in coco.get("annotations", []):
        cname = next(c["name"] for c in coco["categories"] if c["id"] == a["category_id"])
        cid = class_to_id[cname]
        x, y, w, h = a["bbox"]  # COCO เป็นพิกเซล
        per_img[a["image_id"]].append({"class_id": cid, "left": x, "top": y, "width": w, "height": h})

    # 2) สร้าง JSON Lines ตามฟอร์แมต Rekognition Object Detection
    items = []
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for img_id, anns in per_img.items():
        f = img_map[img_id]["file"]
        w = img_map[img_id]["w"]; h = img_map[img_id]["h"]
        entry = {
            "source-ref": f"s3://{BUCKET}/{IMG_PREFIX}{f}",
            JOB: {
                "annotations": anns,
                "image_size": [{"width": w, "height": h, "depth": 3}]
            },
            f"{JOB}-metadata": {
                "objects": [{"confidence": 1} for _ in anns],
                "class-map": {str(i): id_to_name[i] for i in range(len(cats))},
                "human-annotated": "yes",
                "creation-date": today,
                "type": "groundtruth/object-detection",
                "job-name": JOB
            }
        }
        items.append(entry)

    random.shuffle(items)
    n_val = max(1, int(len(items) * VAL_SPLIT))
    val_items = items[:n_val]
    train_items = items[n_val:]

    _put_jsonl(train_items, f"{OUT_PREFIX}train.manifest")
    _put_jsonl(val_items,   f"{OUT_PREFIX}val.manifest")

    return {"ok": True, "train": len(train_items), "val": len(val_items), "classes": cats}
