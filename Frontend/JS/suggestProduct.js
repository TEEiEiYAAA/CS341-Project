// ==========================================================
// ไฟล์: JS/suggestProduct.js
// หน้าที่: ดึงข้อมูล JSON จาก S3 และแสดงผลการวิเคราะห์ + สินค้า
// ==========================================================

async function loadAnalysisResult(jsonUrl) {
    // 1. อ้างอิง Element ตาม HTML ที่คุณส่งมา
    const analysisText = document.getElementById('analysis-text');
    const analysisContainer = document.getElementById('analysis-container');
    const productList = document.getElementById('product-list');
    const productContainer = document.getElementById('product-container');

    // ส่วนแสดงสถานะ (HTML ของคุณใช้ id="status")
    const statusDisplay = document.getElementById('status');

    console.log("🚀 เริ่มทำงาน: loadAnalysisResult ที่ URL:", jsonUrl);

    // 2. อัปเดตสถานะว่ากำลังทำงาน (User จะได้รู้ว่าระบบไม่ค้าง)
    if (analysisContainer) analysisContainer.classList.remove('hidden');
    if (analysisText) {
        analysisText.innerHTML = '<span style="color:#888">⏳ กำลังวิเคราะห์ข้อมูลจาก AI...</span>';
    }
    if (statusDisplay) {
        statusDisplay.textContent = 'กำลังดึงข้อมูลสินค้าแนะนำ...';
        statusDisplay.style.color = '#707070'; 
    }

    try {
        // 3. พยายามดึงไฟล์ JSON จาก S3
        const response = await fetch(jsonUrl);

        // กรณี 1: ยังไม่เจอไฟล์ (404/403) -> แปลว่า Lambda ยังสร้างไฟล์ไม่เสร็จ
        if (!response.ok) {
            console.log("...รอไฟล์ผลลัพธ์จาก Lambda...");
            return false; // ⚠️ ส่งค่า false กลับไป เพื่อให้ script.js รู้ว่าต้องวนรอบใหม่
        }

        // กรณี 2: เจอไฟล์แล้ว -> แปลงเป็น JSON
        const data = await response.json();
        console.log("✅ ได้รับข้อมูลสินค้าแล้ว:", data);

        // -------------------------------------------------------
        // ส่วน A: แสดงผลปัญหาผิว (Analysis Labels) ------ อันเก่า
        // -------------------------------------------------------
        /*const problems = data.analysis_labels || [];
        if (analysisText) {
            if (problems.length > 0) {
                // แสดงรายการปัญหาผิวเป็นตัวหนาสีแดง
                analysisText.innerHTML = `<strong style="color:#E57373">${problems.join(", ")}</strong>`;
            } else {
                analysisText.textContent = "ผิวสุขภาพดี ไม่พบปัญหาที่เด่นชัด";
            }
        }*/


        const problems = data.analysis_labels || [];

        // 1. สร้างดิกชันนารีแปลภาษา
        const problemMapping = {
            "Acne": "สิว",
            "Blackheads": "สิวหัวดำ",
            "Whiteheads": "สิวหัวขาว",
            "Oily-Skin": "ผิวมัน",
            "Enlarged-Pores": "รูขุมขนกว้าง",
            "Englarged-Pores": "รูขุมขนกว้าง",
            "Wrinkles": "ริ้วรอย",
            "Dark-Spots": "จุดด่างดำ",
            "Skin-Redness": "รอยแดง",
            "Redness": "รอยแดง",
            "Dry-Skin": "ผิวแห้ง",
            "Eyebags": "ถุงใต้ตา",
            "wrinkles-acne-pores": "ปัญหาริ้วรอย สิว และรูขุมขน"
        };

        if (analysisText) {
            if (problems.length > 0) {
                // 2. วนลูปสร้าง <li> ภาษาไทย สี #707070
                const listItems = problems.map(label => {
                    const thaiLabel = problemMapping[label] || label;
                    return `<li style="color: #707070; margin-bottom: 5px;">${thaiLabel}</li>`;
                }).join('');

                // 3. ยัดใส่ <ul>
                analysisText.innerHTML = `<ul style="padding-left: 20px; margin: 0;">${listItems}</ul>`;
            } else {
                analysisText.innerHTML = `<span style="color: #707070;">ผิวสุขภาพดี ไม่พบปัญหาที่เด่นชัด</span>`;
            }
        }

        // -------------------------------------------------------
        // ส่วน B: แสดงการ์ดสินค้า (Product Recommendations)
        // -------------------------------------------------------
        /*const products = data.recommendations || [];
        
        // เคลียร์ข้อมูลเก่าก่อนวาดใหม่
        if (productList) productList.innerHTML = ''; 

        if (products.length > 0) {
            products.forEach(product => {
                // สร้าง HTML การ์ดสินค้า
                const card = document.createElement('div');
                card.className = 'product-card-item'; // Class นี้ต้องมีใน CSS

                // จัดการ text ส่วนผสม (เปลี่ยน | เป็น , เว้นวรรค)
                const ingredientsList = product.ingredients ? product.ingredients.replace(/\|/g, ', ') : '-';

                // ใส่เนื้อหา HTML
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
            
            // อัปเดตข้อความสถานะว่าเสร็จสมบูรณ์
            if (statusDisplay) {
                statusDisplay.innerHTML = '<b>✨ เสร็จสิ้น! เลื่อนลงด้านล่างเพื่อดูสินค้าแนะนำ</b>';
                statusDisplay.style.color = '#27ae60'; // สีเขียว
            }

            return true; // ✅ ส่งค่า true กลับไป เพื่อบอก script.js ว่า "จบงานแล้ว หยุดวนลูปได้"
        */

        const products = data.recommendations || [];

        // เคลียร์ข้อมูลเก่าก่อนวาดใหม่
        if (productList) productList.innerHTML = '';

        if (products.length > 0) {
            products.forEach(product => {
                // 1. แปลงชื่อปัญหาเป็นไทย
                const problemText = problemMapping[product.problem] || product.problem;

                // 2. เตรียมลิสต์ส่วนผสม (เปลี่ยนจาก option เป็น div ทีละบรรทัด)
                const ingredientsList = product.ingredients
                    ? product.ingredients.split(/[|,]/).map(ing =>
                        `<div class="ing-row">${ing.trim()}</div>`
                    ).join('')
                    : '<div class="ing-row">-</div>';

                // 3. สร้าง HTML การ์ดสินค้า (เปลี่ยนจาก select เป็น details/summary)
                const cardHTML = `
                <div class="product-item">
                    <div class="product-img-wrapper">
                        <img src="${product.image_url || './Image/placeholder.png'}" class="product-img" onerror="this.src='https://via.placeholder.com/150?text=No+Image'">
                    </div>
                    
                    <div class="product-info">
                        <div class="product-header">
                            <span class="product-name">${product.brand || ''} - ${product.name}</span>
                            <span class="product-price">ราคา: ${Number(product.price).toLocaleString()} บาท</span>
                        </div>
                        
                        <div class="product-problem-text">แก้ปัญหา: ${problemText}</div>
                        
                        <div class="product-actions">
                            <details class="ing-accordion">
                                <summary>
                                    ส่วนผสม
                                    <svg class="arrow-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                                </summary>
                                <div class="ing-content">
                                    ${ingredientsList}
                                </div>
                            </details>
                        </div>
                    </div>
                </div>`;

                productList.innerHTML += cardHTML;
            });

            // ... (ส่วนอัปเดต statusDisplay ด้านล่างเหมือนเดิม) ...
            if (productContainer) productContainer.classList.remove('hidden');
            if (statusDisplay) {
                statusDisplay.innerHTML = '<b>✨ เสร็จสิ้น! เลื่อนลงด้านล่างเพื่อดูสินค้าแนะนำ</b>';
                statusDisplay.style.color = '#27ae60';
            }

            return true;


        } else {
            // กรณีไม่มีสินค้าแนะนำ (แต่ไฟล์มาแล้ว)
            if (productList) productList.innerHTML = '<p style="text-align:center; width:100%; color:#888;">ไม่พบข้อมูลสินค้าแนะนำในระบบ</p>';
            if (productContainer) productContainer.classList.remove('hidden');

            if (statusDisplay) {
                statusDisplay.textContent = 'วิเคราะห์เสร็จสิ้น (ไม่พบสินค้าที่ตรงกัน)';
                statusDisplay.style.color = '#27ae60';
            }
            return true; // จบงาน
        }

    } catch (error) {
        console.error("Error parsing result:", error);
        if (statusDisplay) {
            statusDisplay.textContent = "เกิดข้อผิดพลาดในการแสดงผล";
            statusDisplay.style.color = 'red';
        }
        return true; // จบงาน (เพราะ Error แล้ว วนไปก็ไม่ได้อะไร)
    }
}