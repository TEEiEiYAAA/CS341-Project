import os, sys, requests, json

API_URL = "https://cmh4aw53j1.execute-api.us-east-1.amazonaws.com/dataset-presign"
NOTIFY_URL = "https://z1jowe5vqj.execute-api.us-east-1.amazonaws.com/notify-upload"
DATASET = "skin-2025-09"
USER_ID = "local-admin"

def main(zip_path):
    # 1) ขอ presign
    r = requests.get(f"{API_URL}?dataset={DATASET}&userId={USER_ID}")
    r.raise_for_status()
    info = r.json()
    upload = info["upload"]

    # 2) อัป zip ไป S3
    with open(zip_path, "rb") as f:
        files = {"file": (os.path.basename(zip_path), f, "application/zip")}
        r2 = requests.post(upload["url"], data=upload["fields"], files=files)
        if r2.status_code not in (200, 204):
            print("❌ Upload failed:", r2.status_code, r2.text)
            sys.exit(1)
    print("✅ Ingested:", f"s3://{info['bucket']}/{info['key']}")

    # 3) แจ้ง notify-curator ให้ offline-curator ทำงาน
    notify_url = os.getenv("NOTIFY_URL", NOTIFY_URL)  # ใช้ ENV ก่อน ถ้าไม่มี fallback ค่า hard-coded
    if notify_url:
        payload = {"bucket": info["bucket"], "key": info["key"]}
        r3 = requests.post(notify_url, json=payload, timeout=30)
        r3.raise_for_status()
        print("🚀 Notified curator:", r3.json())
    else:
        print("⚠️ NOTIFY_URL not set, skipping notify")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("วิธีใช้: python ingest_dataset.py <dataset.zip>")
        sys.exit(1)
    main(sys.argv[1])
