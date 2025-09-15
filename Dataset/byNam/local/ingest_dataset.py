import os, sys, requests

API_URL = "https://cmh4aw53j1.execute-api.us-east-1.amazonaws.com/dataset-presign"
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

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("วิธีใช้: python ingest_dataset.py <dataset.zip>")
        sys.exit(1)
    main(sys.argv[1])
