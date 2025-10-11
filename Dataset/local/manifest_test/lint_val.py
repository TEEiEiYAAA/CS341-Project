import json, re, sys

attr = "bounding-box"
meta = f"{attr}-metadata"

def ok_int(x): return isinstance(x, int) and x >= 0

bad = 0
with open("val.manifest", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if not line: continue
        try:
            j = json.loads(line)
        except Exception as e:
            print(f"[L{i}] ❌ JSON parse error: {e}")
            bad += 1
            continue

        # ตรวจคีย์หลัก
        if "source-ref" not in j or attr not in j or meta not in j:
            print(f"[L{i}] ❌ missing keys (source-ref / {attr} / {meta})")
            bad += 1; continue

        bb = j[attr]
        mm = j[meta]

        # annotations & image_size
        ann = bb.get("annotations") or []
        sz  = bb.get("image_size") or []
        if not ann:
            print(f"[L{i}] ❌ no annotations")
            bad += 1

        if not (isinstance(sz, list) and len(sz)==1 and
                ok_int(sz[0].get("width", -1)) and ok_int(sz[0].get("height", -1)) and ok_int(sz[0].get("depth", -1))):
            print(f"[L{i}] ❌ image_size invalid: {sz}")
            bad += 1
        else:
            W, H = sz[0]["width"], sz[0]["height"]

        # กล่องต้องเป็น int และไม่เกินขอบภาพ
        for k, a in enumerate(ann):
            for key in ("class_id","left","top","width","height"):
                if not ok_int(a.get(key, -1)):
                    print(f"[L{i}] ❌ box[{k}] non-int field '{key}': {a.get(key)}")
                    bad += 1
                    break
            else:
                x,y,w,h = a["left"], a["top"], a["width"], a["height"]
                if W and H and (x+w>W or y+h>H):
                    print(f"[L{i}] ❌ box[{k}] out of bounds W{W} H{H} -> {x,y,w,h}")
                    bad += 1

        # metadata schema
        need_meta = ("objects","class-map","human-annotated","creation-date","type","job-name")
        miss = [k for k in need_meta if k not in mm]
        if miss:
            print(f"[L{i}] ❌ metadata missing: {miss}")
            bad += 1

        # type/jon-name
        if mm.get("type") != "groundtruth/object-detection":
            print(f"[L{i}] ❌ metadata.type invalid: {mm.get('type')}")
            bad += 1
        if mm.get("job-name") != attr:
            print(f"[L{i}] ❌ metadata.job-name != '{attr}': {mm.get('job-name')}")
            bad += 1

        # creation-date รูปแบบ ISO-8601 แบบง่าย
        cd = str(mm.get("creation-date",""))
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", cd):
            print(f"[L{i}] ⚠ creation-date should be ISO8601 '...T..Z': {cd}")

        # class-map เป็นสตริง index ต่อเนื่อง
        cmap = mm.get("class-map", {})
        keys = sorted(cmap.keys(), key=lambda s: int(s) if s.isdigit() else 9999)
        if keys != [str(i) for i in range(len(keys))]:
            print(f"[L{i}] ❌ class-map keys should be '0..N-1': {list(cmap.keys())}")
            bad += 1

if bad==0:
    print("✅ manifest looks valid for Rekognition (schema-wise).")
else:
    print(f"❌ found {bad} schema issues.")
