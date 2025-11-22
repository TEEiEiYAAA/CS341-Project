import json
import boto3
import random
from boto3.dynamodb.conditions import Attr
from decimal import Decimal
import urllib.parse

# เชื่อมต่อ S3 และ DynamoDB
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('SkincareProducts') # ชื่อ Table ของคุณ

# Helper แปลง Decimal เป็นเลขปกติ
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    # รับ Event จาก S3
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'])
    
    print(f"Processing file: {key} from bucket: {bucket}")

    try:
        # อ่านไฟล์ JSON Input
        response = s3.get_object(Bucket=bucket, Key=key)
        file_content = response['Body'].read().decode('utf-8')
        input_data = json.loads(file_content)
        
        # ดึง Labels ปัญหาผิว
        detected_labels = input_data.get('labels', [])
        print(f"Labels found: {detected_labels}")
        
        recommendations = []
        
        # วนลูปหาปัญหาสินค้า
        for label in detected_labels:
            # สุ่มหาสินค้าจาก DynamoDB
            db_response = table.scan(
                FilterExpression=Attr('tags').contains(label)
            )
            items = db_response.get('Items', [])
            
            if items:
                selected_product = random.choice(items)
                
                product_data = {
                    "problem": label,
                    "name": selected_product.get('name'),
                    "brand": selected_product.get('brand'),
                    "price": selected_product.get('price'),
                    "image_url": selected_product.get('image_url'),
                    "ingredients": selected_product.get('ingredients', '') 
                }
                recommendations.append(product_data)

        # สร้าง JSON ผลลัพธ์
        final_output = {
            "user_info": input_data.get('source', {}),
            "analysis_labels": detected_labels,
            "recommendations": recommendations
        }
        
        # --- ส่วนสำคัญ: กำหนด Path ใหม่ ---
        # เปลี่ยนโฟลเดอร์จาก results/ เป็น recommendations/
        new_key = key.replace("results/", "recommendations/")
        
        # เปลี่ยนหางไฟล์ให้เป็น _final.json (รองรับทั้ง .jpg.json, .png.json)
        if new_key.endswith(".json"):
            new_key = new_key[:-5] + "_final.json"
        else:
            new_key = new_key + "_final.json"
            
        # บันทึกไฟล์ใหม่ลง S3
        s3.put_object(
            Bucket=bucket,
            Key=new_key,
            Body=json.dumps(final_output, cls=DecimalEncoder, ensure_ascii=False),
            ContentType='application/json'
        )
        
        print(f"✅ Success! Saved to: {new_key}")
        return "Success"

    except Exception as e:
        print(f"Error: {str(e)}")
        raise e