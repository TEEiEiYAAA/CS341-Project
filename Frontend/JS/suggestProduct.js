// file: suggestProduct.js

async function loadAnalysisResult(jsonUrl) {
    // อ้างอิง Element จากหน้า HTML (ต้องมี ID เหล่านี้ใน index.html)
    const analysisText = document.getElementById('analysis-text');
    const analysisContainer = document.getElementById('analysis-container');
    const productList = document.getElementById('product-list');
    const productContainer = document.getElementById('product-container');
    
    // ถ้ามีส่วน Result Message (จาก script ตัวเก่า) ให้ซ่อนหรือเปลี่ยนข้อความ
    const resultMessage = document.getElementById('result-message');

    console.log("🚀 เริ่มทำงาน: loadAnalysisResult ที่ URL:", jsonUrl);

    // 1. แจ้งสถานะกำลังโหลด
    if (analysisContainer) analysisContainer.classList.remove('hidden');
    if (analysisText) {
        analysisText.innerHTML = '<span style="color:#888">⏳ กำลังวิเคราะห์ข้อมูลจาก AI...</span>';
    }
    if (resultMessage) {
        resultMessage.textContent = 'กำลังดึงข้อมูลสินค้าแนะนำ...';
        resultMessage.style.color = '#d35400';
    }

    try {
        // 2. ดึงไฟล์ JSON จาก S3
        const response = await fetch(jsonUrl);
        
        // ถ้ายังไม่เจอไฟล์ (404) ให้จบฟังก์ชันไปเงียบๆ (เพื่อให้ script.js เรียกซ้ำใหม่)
        if (!response.ok) {
            console.log("...รอไฟล์ผลลัพธ์จาก Lambda...");
            return false; // ส่งค่า false กลับไปบอกว่ายังไม่เสร็จ
        }
        
        const data = await response.json();
        console.log("✅ ได้รับข้อมูลสินค้าแล้ว:", data);

        // 3. แสดงผลลัพธ์ปัญหาผิว (Text)
        const problems = data.analysis_labels || [];
        if (analysisText) {
            if (problems.length > 0) {
                analysisText.innerHTML = `<strong style="color:#E57373">${problems.join(", ")}</strong>`;
            } else {
                analysisText.textContent = "ผิวสุขภาพดี ไม่พบปัญหาที่เด่นชัด";
            }
        }

        // 4. สร้างการ์ดสินค้า (Grid)
        const products = data.recommendations || [];
        
        // เคลียร์ข้อมูลเก่าก่อน
        if (productList) productList.innerHTML = ''; 

        if (products.length > 0) {
            products.forEach(product => {
                // สร้าง HTML การ์ดสินค้า
                const card = document.createElement('div');
                card.className = 'product-card-item'; // class นี้ต้องมีใน css

                // จัดการ text ส่วนผสม (แปลง | เป็น ,)
                const ingredientsList = product.ingredients ? product.ingredients.replace(/\|/g, ', ') : '-';

                // ใส่เนื้อหาลงในการ์ด
                card.innerHTML = `
                    <div class="product-badge">แก้ปัญหา: ${product.problem}</div>
                    <img src="${product.image_url}" alt="${product.name}" class="product-card-img" onerror="this.src='https://via.placeholder.com/150?text=No+Image'">
                    
                    <div class="product-card-info">
                        <div class="product-card-brand">${product.brand || 'Brand'}</div>
                        <div class="product-card-name">${product.name}</div>
                        <div class="product-card-price">฿${Number(product.price).toLocaleString()}</div>
                        
                        <details class="ing-details">
                            <summary>ดูส่วนผสม</summary>
                            <div class="ing-content">${ingredientsList}</div>
                        </details>
                    </div>
                `;
                // ยัดการ์ดลงในกล่อง productList
                productList.appendChild(card);
            });

            // เปิดกล่องสินค้าให้แสดงขึ้นมา
            if (productContainer) productContainer.classList.remove('hidden');
            
            // อัปเดตข้อความสถานะว่าเสร็จแล้ว
            if (resultMessage) {
                resultMessage.innerHTML = '<b>✨ เสร็จสิ้น! เลื่อนลงด้านล่างเพื่อดูสินค้าแนะนำ</b>';
                resultMessage.style.color = '#27ae60';
            }

            return true; // ส่งค่า true กลับไปบอกว่าเสร็จแล้ว

        } else {
            // กรณีไม่มีสินค้าแนะนำ
            if (productList) productList.innerHTML = '<p style="text-align:center; width:100%; color:#888;">ไม่พบข้อมูลสินค้าแนะนำในระบบ</p>';
            if (productContainer) productContainer.classList.remove('hidden');
            return true;
        }

    } catch (error) {
        console.error("Error parsing result:", error);
        if (resultMessage) {
            resultMessage.textContent = "เกิดข้อผิดพลาดในการแสดงผล";
            resultMessage.style.color = 'red';
        }
        return true; // ถือว่าจบกระบวนการ (แม้จะ error)
    }
}