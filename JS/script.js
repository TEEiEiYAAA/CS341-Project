document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements (เหมือนเดิม) ---
    const hamburgerMenu = document.getElementById('hamburger-menu');
    const closeMenu = document.getElementById('close-menu');
    const sidebar = document.querySelector('.sidebar');
    const uploadBtn = document.getElementById('upload-btn');
    const fileInput = document.getElementById('file-input');
    const fileNameText = document.getElementById('file-name-text');
    const removeFileBtn = document.getElementById('remove-file-btn');
    const uploadForm = document.getElementById('upload-form');
    const resultMessage = document.getElementById('result-message');
    const modalOverlay = document.getElementById('modal-overlay');
    const confirmModal = document.getElementById('confirm-modal');
    const errorModal = document.getElementById('error-modal');
    const closeConfirmModalBtn = document.getElementById('close-confirm-modal-btn');
    const confirmClearBtn = document.getElementById('confirm-clear-btn');
    const errorClearBtn = document.getElementById('error-clear-btn');

    // --- << ส่วนที่แก้ไข >> ---
    // ใส่ URL ของ API Gateway ที่คุณสร้างขึ้นเพื่อเรียก Lambda Function
    const API_ENDPOINT = 'YOUR_API_GATEWAY_URL_HERE';
    // -------------------------

    let isInteractionBlocked = false;

    // --- Sidebar and Modal Logic (เหมือนเดิม) ---
    const toggleSidebar = () => { if (!isInteractionBlocked) sidebar.classList.toggle('open'); };
    if (hamburgerMenu) hamburgerMenu.addEventListener('click', toggleSidebar);
    if (closeMenu) closeMenu.addEventListener('click', toggleSidebar);
    const showModal = (modal) => { modalOverlay.classList.remove('hidden'); modal.classList.remove('hidden'); };
    const hideAllModals = () => { if (isInteractionBlocked) return; modalOverlay.classList.add('hidden'); confirmModal.classList.add('hidden'); errorModal.classList.add('hidden'); };
    const resetFileInput = () => { fileInput.value = ''; fileNameText.textContent = '<No File Chosen...>'; fileNameText.style.color = '#888'; removeFileBtn.classList.add('hidden'); };
    uploadBtn.addEventListener('click', () => { if (isInteractionBlocked) return; fileInput.click(); });
    removeFileBtn.addEventListener('click', () => { if (isInteractionBlocked) return; showModal(confirmModal); });
    closeConfirmModalBtn.addEventListener('click', hideAllModals);
    modalOverlay.addEventListener('click', hideAllModals);
    confirmClearBtn.addEventListener('click', () => { resetFileInput(); hideAllModals(); });
    errorClearBtn.addEventListener('click', () => { isInteractionBlocked = false; hideAllModals(); resetFileInput(); });

    // --- File Handling (เหมือนเดิม) ---
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            const file = fileInput.files[0];
            if (file.type.startsWith('image/')) {
                fileNameText.textContent = file.name;
                fileNameText.style.color = 'var(--text-color)';
                removeFileBtn.classList.remove('hidden');
            } else {
                resetFileInput();
                showModal(errorModal);
                isInteractionBlocked = true;
            }
        } else {
            resetFileInput();
        }
    });

    // --- << ส่วนที่แก้ไข: Form Submission Logic ใหม่ทั้งหมด >> ---
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (isInteractionBlocked) return;

        const selectedFile = fileInput.files[0];

        // --- ส่วนที่แก้ไข ---
        // 1. ค้นหา checkbox ทั้งหมดที่ถูกติ๊ก
        const selectedCheckboxes = document.querySelectorAll('input[name="skin-type"]:checked');

        // 2. ดึงค่า value ของแต่ละอันมาเก็บใน array
        const selectedSkinTypes = [];
        selectedCheckboxes.forEach((checkbox) => {
            selectedSkinTypes.push(checkbox.value);
        });
        // ผลลัพธ์จะเป็น array เช่น ["ผิวมัน", "ผิวแพ้ง่าย"]
        // ------------------

        // Validation
        if (!selectedFile) {
            resultMessage.textContent = 'กรุณาอัปโหลดรูปภาพก่อน';
            resultMessage.style.color = 'red';
            return;
        }
        // แก้ไข: ตรวจสอบว่ามี array ค่าที่เลือกหรือไม่
        if (selectedSkinTypes.length === 0) {
            resultMessage.textContent = 'กรุณาเลือกสภาพผิวของท่านอย่างน้อย 1 ข้อ';
            resultMessage.style.color = 'red';
            return;
        }
        if (API_ENDPOINT === 'YOUR_API_GATEWAY_URL_HERE') {
            resultMessage.textContent = 'Error: API Gateway URL is not configured.';
            resultMessage.style.color = 'red';
            return;
        }

        resultMessage.textContent = 'กำลังเตรียมการอัปโหลด...';
        resultMessage.style.color = 'var(--text-color)';

        try {
            // ขั้นตอนที่ 1: ขอ Pre-signed URL (เหมือนเดิม)
            const response = await fetch(API_ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    fileName: selectedFile.name,
                    fileType: selectedFile.type
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(`Cannot get upload URL: ${errorData.error || response.statusText}`);
            }

            const { uploadURL, key } = await response.json();
            resultMessage.textContent = 'กำลังอัปโหลดไฟล์...';

            // ขั้นตอนที่ 2: อัปโหลดไฟล์ไปยัง S3 (เหมือนเดิม)
            const uploadResponse = await fetch(uploadURL, {
                method: 'PUT',
                headers: { 'Content-Type': selectedFile.type },
                body: selectedFile
            });

            if (!uploadResponse.ok) {
                throw new Error('File upload failed.');
            }

            resultMessage.textContent = 'อัปโหลดสำเร็จ!';
            resultMessage.style.color = 'green';

            // --- ส่วนที่แก้ไข ---
            // 3. รวมค่าใน array ให้เป็นข้อความเดียว คั่นด้วยจุลภาค (,)
            const skinTypesString = selectedSkinTypes.join(',');
            // ผลลัพธ์จะเป็น string เช่น "ผิวมัน,ผิวแพ้ง่าย"

            // ณ จุดนี้ คุณสามารถเรียก Lambda function อีกตัวเพื่อเริ่ม "ประมวลผล"
            // โดยส่ง `key` และ `skinTypesString` ที่มีหลายค่าไปให้
            console.log(`File uploaded to S3 with key: ${key}`);
            console.log(`Skin types to process: ${skinTypesString}`);
            // ตัวอย่าง: processImage(key, skinTypesString);
            // ------------------

        } catch (error) {
            resultMessage.textContent = `Error: ${error.message}`;
            resultMessage.style.color = 'red';
        }
    });
});