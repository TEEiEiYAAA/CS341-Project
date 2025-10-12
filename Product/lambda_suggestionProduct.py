import json
import pandas as pd
import boto3

# Step 1: จำลองข้อมูลจาก Rekognition
rekognition_results = {
    "Oily-Skin": 1,  # ผิวมัน
    "Dry-Skin": 1,   # ผิวแห้ง
    "Acne": 1,       # สิว
    "Wrinkles": 1,   # ริ้วรอย
    "Blackheads": 1,  # รูขุมขนกว้าง
    "wrinkles-acne-pores": 1,
    "Dark-Spots": 1,
    "Englarged-Pores": 1,
    "Eyebags": 1,
    "Skin-Redness": 1,
    "Whiteheads": 1
}

def lambda_handler(event, context):
    # Step 2: รับข้อมูลจาก event (รับค่าปัญหาผิวจากการส่งข้อมูล API)
    skin_concern = event.get('skin_concern', 'Oily-Skin')  # Default เป็น 'Oily-Skin' หากไม่ได้ส่งข้อมูล

    # Step 3: เชื่อมต่อกับ S3 เพื่อดึงข้อมูล CSV
    s3 = boto3.client('s3')
    bucket_name = 'kaggle-dataset-skincare'  # เปลี่ยนเป็นชื่อ S3 bucket ของคุณ
    file_key = 'data/product_catalog_clean.csv'  # เปลี่ยนเป็น path ของไฟล์ใน S3

    # โหลดไฟล์ CSV จาก S3
    obj = s3.get_object(Bucket=bucket_name, Key=file_key)
    csv_data = pd.read_csv(obj['Body'])

    # Step 4: กรองผลิตภัณฑ์ที่เหมาะสมกับประเภทผิวจาก Rekognition
    if rekognition_results.get(skin_concern, 0) == 1:
        # กรองข้อมูลตามประเภทผิว (คอลัมน์ที่ตรงกับผลการวิเคราะห์จาก Rekognition)
        
        if skin_concern == 'Oily-Skin':
            filtered_data = csv_data[csv_data['Oily'] == 1]
        elif skin_concern == 'Dry-Skin':
            filtered_data = csv_data[csv_data['Dry'] == 1]
        elif skin_concern == 'Normal':
            filtered_data = csv_data[csv_data['Normal'] == 1]
        elif skin_concern == 'Sensitive':
            filtered_data = csv_data[csv_data['Sensitive'] == 1]
        elif skin_concern == 'Acne':
            filtered_data = csv_data[csv_data['Oily'] == 1]  # สิวมักเกี่ยวข้องกับผิวมัน
        elif skin_concern == 'Wrinkles':
            filtered_data = csv_data[csv_data['Dry'] == 1]  # ริ้วรอยมักเกี่ยวข้องกับผิวแห้ง
        elif skin_concern == 'Blackheads':
            filtered_data = csv_data[csv_data['Oily'] == 1]  # สิวเสี้ยนมักเกี่ยวข้องกับผิวมัน
        elif skin_concern == 'Dark-Spots':
            filtered_data = csv_data[csv_data['Dry'] == 1]  # จุดด่างดำมักเกิดกับผิวแห้ง
        elif skin_concern == 'Eyebags':
            filtered_data = csv_data[csv_data['Sensitive'] == 1]  # ถุงใต้ตามักเกี่ยวข้องกับผิวบอบบาง
        elif skin_concern == 'Skin-Redness':
            filtered_data = csv_data[csv_data['Sensitive'] == 1]  # ผิวแดงมักเกี่ยวข้องกับผิวบอบบาง
        elif skin_concern == 'Whiteheads':
            filtered_data = csv_data[csv_data['Oily'] == 1]  # สิวหัวขาวมักเกี่ยวข้องกับผิวมัน

        else:
            filtered_data = pd.DataFrame()  # ไม่มีข้อมูลที่กรองได้

        # Step 5: หากกรองข้อมูลได้, ส่งข้อมูลผลิตภัณฑ์ที่เหมาะสมกลับ
        if not filtered_data.empty:
            result = filtered_data[['Label', 'brand', 'name', 'price', 'ingredients']].to_dict(orient='records')
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }
        else:
            return {
                'statusCode': 404,
                'body': json.dumps({"error": f"No suitable products found for {skin_concern}."})
            }

    # หากไม่มีผลลัพธ์จาก Rekognition หรือไม่พบประเภทผิว
    return {
        'statusCode': 400,
        'body': json.dumps({"error": "Invalid skin concern or no data available."})
    }
