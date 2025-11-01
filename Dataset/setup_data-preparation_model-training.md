# ⚙️ Setup: Data Preparation & Model Training

☁️ S3 Configuration
    Bucket: dermavision-offline
    Region: us-east-1

    ตั้งค่าก่อนใช้งาน
    ✅ Unblock all public access
    ✅ Object Ownership: set to ACLs enabled
    ✅ หลังอัปโหลด manifest เสร็จ
        → เลือกไฟล์ manifest แล้วกด Action > Make public using ACL

    โครงสร้างหลักของ Bucket:

    dermavision-offline/
    │
    ├── landing/                  ← เก็บ ZIP ที่อัปโหลดเข้าระบบ
    ├── datasets/
    │   ├── raw/                  ← รูปต้นฉบับ + coco.json
    │   ├── preprocessed/         ← รูปที่ผ่านการย่อขนาด/normalize แล้ว
    │   └── manifest/             ← train.manifest / val.manifest / labels / validation_report.json

-------------------------------------------------------------------------------------------------
⚙️ Lambda Setup

    1.  Lambda: dataset_presigner
            Runtime: Python 3.13
            Arch: x86_64
            Role: LabRole
            Handler: lambda_dataset_presigner.handler
            Memory: 512 MB
            Timeout: 3 min

        API Gateway
            API name: dataset-presign
            Method: GET
            Resource path: /data-presign
            Integration: Lambda (dataset-presigner)
            Region: us-east-1

            🔗 Copy API endpoint
            https://ihnkz1ifi4.execute-api.us-east-1.amazonaws.com/data-presign
                → ไปวางใน ..\Dataset\local\ingest_dataset.py บรรทัดที่ 3

        -----------------------------------------------------------------------
    2.  Lambda: notify_curator
            Runtime: Python 3.13
            Arch: x86_64
            Role: LabRole
            Handler: notify_curator.handler
            Memory: Default


        API Gateway
            API name: notify-upload
            Method: POST
            Resource path: /notify-upload
            Integration: Lambda (notify_curator)
            Region: us-east-1

            🔗 Copy API endpoint
            https://3vnnragjbi.execute-api.us-east-1.amazonaws.com/notify-upload
            → ไปวางใน ..\Dataset\local\ingest_dataset.py บรรทัดที่ 4

        -----------------------------------------------------------------------
    3.  Lambda: offline_curator
            Runtime: Python 3.13
            Arch: x86_64
            Role: LabRole
            Handler: lambda_offline_curator.handler
            Memory: 512 MB
            Timeout: 3 min
            Trigger: S3 (Prefix: landing/)
            ENV:
                BUCKET=dermavision-offline
                DATASET_NAME=skin-2025-09
                PREPROCESS_FN=preprocess-images
                MANIFEST_FN=coco_to_rek_manifest
                WAIT_PREPROC_READY_SECS=600

        -----------------------------------------------------------------------
    4.  Lambda: preprocess-images
            Runtime: Python 3.9
            Arch: x86_64
            Role: LabRole
            Handler: lambda_preprocess_images.handler
            Memory: 1024 MB
            Timeout: 5 min
            ENV:
                BUCKET=dermavision-offline
                DATASET_NAME=skin-2025-09


        สร้าง Layer (Pillow Layer)

            เปิด CloudShell

                rm -rf python pillow-layer.zip
                mkdir -p python
                python3 -m pip install --upgrade pip
                python3 -m pip install "pillow==10.4.0" -t python
                zip -r pillow-layer.zip python

                Action > Dowload file: pillow-layer.zip

        # อัปโหลด pillow-layer.zip ไปที่ Lambda Layer  
        Lambda > Layer > create layer
            Name: pillow-layer
            Upload a .zip file: pillow-layer.zip
            Runtime: Python 3.13
            Arch: x86_64
        
        # เพิ่มเข้าในฟังก์ชัน preprocess-images
        Lambda > preprocess-images > Add Layer > Choose a layer
            Layer source: Custom layers
            Custom layers: pillow-layer

        -----------------------------------------------------------------------
    5.  Lambda: coco_to_rek_manifest
            Runtime: Python 3.13
            Arch: x86_64
            Role: LabRole
            Handler: lambda_coco_to_rek_manifest.handler
            Memory: 1024 MB
            Timeout: 3 min
            ENV:
                BUCKET=dermavision-offline
                DATASET_NAME=skin-2025-09
                VAL_SPLIT=0.1
                VALIDATE_FN=validate_dataset
                ENABLE_BALANCE=true
                PER_CLASS_CAP=90
                MIN_CLASS_IMAGES=40
                MIN_BOX_PX=6
                MAX_BOX_PER_IMAGE=50

        -----------------------------------------------------------------------
    6.  Lambda: validate_dataset
            Runtime: Python 3.13
            Arch: x86_64
            Role: LabRole
            Handler: lambda_validate_dataset.handler
            Memory: 128 MB
            Timeout: 3 min
            ENV:
                BUCKET=dermavision-offline
                DATASET_NAME=skin-2025-09

----------------------------------------------------------------------------------------------
🧪 Local Setup (VS Code)

    # เปิดโฟลเดอร์ Dataset
    # แก้ไขบรรทัด 3–4 ใน local/ingest_dataset.py ตาม endpoint ที่ได้จาก API Gateway
        cd .\local\
        python --version
        pip install -r requirements.txt
        python ingest_dataset.py "Face Skin Problems.v1i.coco.zip"

----------------------------------------------------------------------------------------------
🧾 Description

    เมื่อรันไฟล์ ingest_dataset.py ระบบจะอัปโหลด ZIP ขึ้น S3 แล้วเริ่มกระบวนการทั้งหมดอัตโนมัติผ่าน Lambda Workflow:

    1. S3 Landing:
        เมื่ออัปโหลด ZIP → สร้างโฟลเดอร์ landing/
        ระบบจะ Trigger Lambda notify_curator → offline_curator

    2. Data Extraction & Preprocess:
        แตกไฟล์และจัดเก็บใน datasets/raw/
        ปรับขนาดรูปและตรวจสอบใน datasets/preprocessed/
        หลังเสร็จจะสร้าง _READY เพื่อยืนยันว่าภาพพร้อมใช้งาน

    3. COCO → Rekognition Manifest Conversion:
        Lambda coco_to_rek_manifest แปลง COCO → Manifest
        แบ่งชุดข้อมูลเป็น train/val (801 / 88 ภาพ)
        สร้าง labels.txt, labels.json, และเรียก validate_dataset

    4. Data Validation:
        ตรวจสอบความครบถ้วนของข้อมูล
        สร้างรายงาน validation_report.json ระบุภาพ, annotations, และ summary

    5. Train Rekognition Model:
        ใช้ไฟล์ manifest จาก S3:
            s3://dermavision-offline/datasets/skin-2025-09/manifest/train.manifest
            s3://dermavision-offline/datasets/skin-2025-09/manifest/val.manifest

        ใช้เวลาฝึก ~2.8 ชั่วโมง
        ผล Evaluate: F1 = 0.343, Precision = 0.347, Recall = 0.36
        ARN:
            arn:aws:rekognition:us-east-1:992382606126:project/DermaVision-Model/version/DermaVision-Model.2025-11-01T16.25.30/1761989132640
