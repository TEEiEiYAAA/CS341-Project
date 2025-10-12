import json
import boto3
import os
import uuid
from botocore.exceptions import ClientError

# --- ตั้งค่าที่จำเป็น ---
# คุณต้องตั้งค่า S3_BUCKET และ AWS_REGION ใน Environment Variables ของ Lambda
S3_BUCKET = os.environ.get('S3_BUCKET')
AWS_REGION = os.environ.get('AWS_REGION')

# ตั้งค่าประเภทไฟล์ที่อนุญาต
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'}

s3_client = boto3.client('s3', region_name=AWS_REGION)

def lambda_handler(event, context):
    """
    Lambda function ที่สร้าง Pre-signed URL สำหรับการอัปโหลดไฟล์ไปยัง S3
    """
    try:
        # ดึงข้อมูลจาก request body ที่ส่งมาจาก client (script.js)
        body = json.loads(event.get('body', '{}'))
        file_name = body.get('fileName')
        file_type = body.get('fileType')

        if not file_name or not file_type:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing fileName or fileType'})
            }

        # ตรวจสอบนามสกุลไฟล์
        extension = file_name.rsplit('.', 1)[-1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'File type not allowed'})
            }

        # สร้างชื่อไฟล์ใหม่ที่ไม่ซ้ำกัน เพื่อป้องกันการเขียนทับกันบน S3
        # เช่น: 123e4567-e89b-12d3-a456-426614174000.jpg
        unique_file_name = f"{uuid.uuid4()}.{extension}"

        # สร้าง Pre-signed URL
        # URL นี้จะอนุญาตให้ client อัปโหลดไฟล์ด้วยเมธอด PUT ได้ภายใน 300 วินาที (5 นาที)
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': unique_file_name,
                'ContentType': file_type
            },
            ExpiresIn=300
        )

        # ส่ง URL กลับไปให้ client
        return {
            'statusCode': 200,
            # --- สำคัญ: ตั้งค่า CORS Headers ---
            # เพื่อให้เบราว์เซอร์สามารถเรียก API นี้จากโดเมนอื่นได้
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'POST, OPTIONS'
            },
            'body': json.dumps({
                'uploadURL': presigned_url,
                'key': unique_file_name # ชื่อไฟล์ที่จะถูกเก็บใน S3
            })
        }

    except ClientError as e:
        print(f"Boto3 Client Error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Could not generate upload URL'})
        }
    except Exception as e:
        print(f"Error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'An internal error occurred'})
        }