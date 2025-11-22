document.addEventListener('DOMContentLoaded', () => {
    // ============================================================
    // 1. ส่วนจัดการ UI (ปุ่ม, เมนู, เลือกไฟล์) - ไม่ต้องแก้
    // ============================================================
    const hamburgerMenu = document.getElementById('hamburger-menu');
    const closeMenu = document.getElementById('close-menu');
    const sidebar = document.querySelector('.sidebar');
    const fileInput = document.getElementById('file');
    const fileNameText = document.getElementById('file-name-text');
    const removeFileBtn = document.getElementById('remove-file-btn');
    const processBtn = document.getElementById('btnUpload'); // ปุ่มประมวลผล
    const statusDisplay = document.getElementById('status');   // ที่แสดงข้อความสถานะ

    // Modals
    const wrongTypeModal = document.getElementById('wrong-type-modal');
    const confirmClearModal = document.getElementById('confirm-clear-modal');
    const wrongTypeClearBtn = document.getElementById('wrong-type-clear-btn');
    const confirmClearBtn = document.getElementById('confirm-clear-btn');
    const closeConfirmModalBtn = document.getElementById('close-confirm-modal-btn');

    const allowedTypes = ['image/jpeg', 'image/png', 'image/jpg'];

    // Sidebar Logic
    if (hamburgerMenu && sidebar) {
        hamburgerMenu.addEventListener('click', () => sidebar.classList.add('open'));
    }
    if (closeMenu && sidebar) {
        closeMenu.addEventListener('click', () => sidebar.classList.remove('open'));
    }

    // Reset Function
    const resetUI = () => {
        fileInput.value = '';
        fileNameText.textContent = '<No File Chosen...>';
        fileNameText.classList.remove('selected');
        removeFileBtn.classList.add('hidden');
        processBtn.disabled = true;
        statusDisplay.textContent = '';
        
        // ซ่อนผลลัพธ์
        const ac = document.getElementById('analysis-container');
        const pc = document.getElementById('product-container');
        if (ac) ac.classList.add('hidden');
        if (pc) pc.classList.add('hidden');
    };

    // File Input Logic
    if (fileInput) {
        fileInput.addEventListener('change', () => {
            const file = fileInput.files[0];
            if (file) {
                if (allowedTypes.includes(file.type)) {
                    fileNameText.textContent = file.name;
                    fileNameText.classList.add('selected');
                    removeFileBtn.classList.remove('hidden');
                    processBtn.disabled = false; // ปลดล็อคปุ่ม
                } else {
                    resetUI();
                    wrongTypeModal.classList.remove('hidden');
                }
            } else {
                resetUI();
            }
        });
    }

    // Modal Listeners
    if (removeFileBtn) removeFileBtn.addEventListener('click', () => confirmClearModal.classList.remove('hidden'));
    if (wrongTypeClearBtn) wrongTypeClearBtn.addEventListener('click', () => wrongTypeModal.classList.add('hidden'));
    if (confirmClearBtn) confirmClearBtn.addEventListener('click', () => {
        resetUI();
        confirmClearModal.classList.add('hidden');
    });
    if (closeConfirmModalBtn) closeConfirmModalBtn.addEventListener('click', () => confirmClearModal.classList.add('hidden'));


    // ============================================================
    // 2. ส่วนประมวลผล (API & Logic) - แก้ไขชื่อ Bucket ตรงนี้ ✅
    // ============================================================
    const API_BASE = "https://6w4jivfjnf.execute-api.us-east-1.amazonaws.com"; 

    if (processBtn) {
        processBtn.addEventListener("click", async () => {
            const file = fileInput.files[0];
            if (!file) return;

            // ล็อคปุ่ม
            const originalBtnText = processBtn.textContent;
            processBtn.textContent = "กำลังดำเนินการ...";
            processBtn.disabled = true;
            
            try {
                statusDisplay.textContent = "กำลังเตรียมการอัปโหลด...";
                statusDisplay.style.color = "#4A4A4A";

                // 1. ขอ Presigned URL
                const ext = file.name.split('.').pop().toLowerCase() || "jpg";
                const pres = await fetch(`${API_BASE}/presign?ext=${ext}`);
                if (!pres.ok) throw new Error("เชื่อมต่อ Server ไม่ได้");
                const data = await pres.json();

                // 2. อัปโหลดรูปไป S3
                statusDisplay.textContent = "กำลังอัปโหลดรูปภาพ...";
                const form = new FormData();
                Object.entries(data.upload.fields).forEach(([k, v]) => form.append(k, v));
                form.append("file", file);
                
                const resp = await fetch(data.upload.url, { method: "POST", body: form });
                if (!resp.ok) throw new Error("อัปโหลดรูปไม่ผ่าน");

                // ---------------------------------------------------------
                // 3. คำนวณ URL ไฟล์ผลลัพธ์ (แก้ไขให้ตรงกับรูปที่คุณส่งมา)
                // ---------------------------------------------------------
                statusDisplay.innerHTML = '✅ อัปโหลดเสร็จแล้ว! <b>กำลังวิเคราะห์ผิวและหาสินค้า...</b>';
                statusDisplay.style.color = '#27ae60';

                // Key ที่ได้จากการอัปโหลด (เช่น uploads/user=.../image.jpg)
                const uploadKey = data.upload.fields.key; 

                // แปลง Path:
                // จาก: uploads/.../image.jpg  (หรือ results/...)
                // เป็น: recommendations/.../image.jpg_final.json
                
                let resultKey = uploadKey;
                
                // 3.1 เปลี่ยนโฟลเดอร์เป็น recommendations/
                if (resultKey.startsWith("uploads/")) {
                    resultKey = resultKey.replace("uploads/", "recommendations/");
                } else if (resultKey.startsWith("results/")) {
                    resultKey = resultKey.replace("results/", "recommendations/");
                }

                // 3.2 เติม _final.json ต่อท้าย (ตามที่คุณส่งรูปมาดู)
                // ผลลัพธ์จะเป็น: .../image.jpg_final.json
                resultKey = resultKey + "_final.json";

                // 3.3 สร้าง URL เต็ม (ใช้ชื่อ Bucket ที่ถูกต้อง!)
                const bucketName = "skin-analysis-output"; // ✅ แก้แล้ว
                const finalResultUrl = `https://${bucketName}.s3.amazonaws.com/${resultKey}`;

                console.log("🎯 รอรับผลลัพธ์ที่:", finalResultUrl);

                // 4. สั่งให้ดึงข้อมูล (Polling)
                const checkResult = async () => {
                    // ตรวจสอบว่ามีฟังก์ชัน loadAnalysisResult หรือไม่ (จาก suggestProduct.js)
                    if (typeof loadAnalysisResult === 'function') {
                        const isDone = await loadAnalysisResult(finalResultUrl);
                        
                        if (isDone) {
                            // เสร็จแล้ว
                            processBtn.textContent = originalBtnText;
                            processBtn.disabled = false;
                        } else {
                            // ยังไม่มา รอ 3 วิ แล้วเรียกใหม่
                            setTimeout(checkResult, 3000);
                        }
                    } else {
                        console.error("Error: หาฟังก์ชัน loadAnalysisResult ไม่เจอ");
                        statusDisplay.textContent = "เกิดข้อผิดพลาด: ไม่พบ Script แสดงผล";
                    }
                };

                // เริ่มเช็คครั้งแรก (หน่วง 2 วิ)
                setTimeout(checkResult, 2000);

            } catch (err) {
                console.error(err);
                statusDisplay.textContent = "❌ Error: " + err.message;
                statusDisplay.style.color = "red";
                processBtn.textContent = originalBtnText;
                processBtn.disabled = false;
            }
        });
    }
});