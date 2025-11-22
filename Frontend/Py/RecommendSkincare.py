import json
import boto3
from boto3.dynamodb.conditions import Attr
from decimal import Decimal

# เชื่อมต่อ DynamoDB
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('SkincareProducts') # ⚠️ ชื่อ Table ต้องตรงกับที่คุณสร้างเป๊ะๆ

# ตัวช่วยแปลงตัวเลข Decimal ของ DynamoDB ให้เป็น JSON ที่หน้าเว็บเข้าใจ
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    print("Received event:", json.dumps(event))
    
    # 1. รับค่า Labels จาก Event (ที่หน้าเว็บ หรือ Rekognition ส่งมา)
    # รูปแบบที่รับ: {"labels": ["Acne", "Oily-Skin"]}
    detected_labels = event.get('labels', [])
    
    # ถ้าไม่มี Label ส่งมา ให้ตอบกลับไปดีๆ ว่าไม่เจอ
    if not detected_labels:
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'OPTIONS,POST,GET'
            },
            'body': json.dumps({'message': 'No skin problems detected', 'recommended_products': []})
        }
        
    print(f"Searching products for: {detected_labels}")

    try:
        # 2. ค้นหา (Logic: เลือกปัญหาแรกที่สำคัญที่สุดมาหาก่อน)
        # หมายเหตุ: การใช้ Scan เหมาะกับข้อมูลหลักพัน แต่ถ้าข้อมูลหลักล้านควรใช้ Query
        primary_concern = detected_labels[0] 
        
        # คำสั่ง Scan หาแถวที่มี Tag ตรงกับปัญหาแรก
        response = table.scan(
            FilterExpression=Attr('tags').contains(primary_concern)
        )
        items = response.get('Items', [])
        
        # (Optional) ถ้าผลลัพธ์น้อยกว่า 3 ชิ้น และมีปัญหาที่ 2 ให้หาเพิ่ม
        if len(items) < 3 and len(detected_labels) > 1:
            secondary_concern = detected_labels[1]
            print(f"Results low, searching secondary concern: {secondary_concern}")
            response_2 = table.scan(
                FilterExpression=Attr('tags').contains(secondary_concern)
            )
            items.extend(response_2.get('Items', []))

        # ตัดสินค้าซ้ำออก (เผื่อสินค้าเดียวแก้ได้ 2 ปัญหา)
        unique_products = list({v['product_id']: v for v in items}.values())
        
        # เลือกมาแสดงแค่ 10 ชิ้นพอ (สุ่มหรือเลือกตาม Rank ก็ได้ แต่เอาแบบง่ายก่อน)
        final_products = unique_products[:10]

        # 3. ส่งผลลัพธ์กลับไป
        return {
            'statusCode': 200,
            'headers': {
                # Headers พวกนี้สำคัญมากสำหรับการเรียกผ่านหน้าเว็บ (CORS)
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'OPTIONS,POST,GET'
            },
            'body': json.dumps({
                'message': 'Success',
                'search_criteria': detected_labels,
                'count': len(final_products),
                'recommended_products': final_products
            }, cls=DecimalEncoder) # ใช้ Encoder เพื่อแก้บั๊กทศนิยม
        }

    except Exception as e:
        print("Error:", str(e))
        return {
            'statusCode': 500,
            'body': json.dumps(f"Server Error: {str(e)}")
        }