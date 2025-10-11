document.addEventListener('DOMContentLoaded', () => {
    // --- Configuration ---
    const API_BASE = "https://74gg5hsgxk.execute-api.us-east-1.amazonaws.com"; // <- ใส่ URL ของ API Gateway ที่นี่

    // --- DOM Elements ---
    const fileInput = document.getElementById('file-input');
    const uploadButton = document.getElementById('upload-button');
    const fileNameDisplay = document.getElementById('file-name');
    const statusMessage = document.getElementById('status-message');
    
    // Menu Elements
    const hamburgerMenu = document.getElementById('hamburger-menu');
    const closeMenuButton = document.getElementById('close-menu');
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.querySelector('.overlay');

    // --- Menu Toggle Logic ---
    function openSidebar() {
        sidebar.classList.add('open');
        overlay.classList.add('active');
    }

    function closeSidebar() {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
    }

    hamburgerMenu.addEventListener('click', openSidebar);
    closeMenuButton.addEventListener('click', closeSidebar);
    overlay.addEventListener('click', closeSidebar);


    // --- File Upload Logic ---
    
    // Trigger file input when the upload button is clicked
    uploadButton.addEventListener('click', () => {
        // If a file is already selected, perform upload. Otherwise, open file dialog.
        if (fileInput.files.length > 0) {
            handleUpload();
        } else {
            fileInput.click();
        }
    });

    // Update file name display when a file is chosen
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            const file = fileInput.files[0];
            fileNameDisplay.textContent = file.name;
            statusMessage.textContent = "พร้อมอัปโหลด";
        } else {
            fileNameDisplay.textContent = "<No File Chosen...>";
        }
    });

    // The main upload function
    async function handleUpload() {
        const file = fileInput.files[0];
        if (!file) {
            statusMessage.textContent = "กรุณาเลือกรูปก่อนอัปโหลด";
            return;
        }

        // Hardcoded userId, since it's removed from the UI
        const userId = "U001"; 

        try {
            statusMessage.textContent = "กำลังเตรียมการอัปโหลด...";
            
            // 1. Get Presigned URL from our backend (Lambda)
            const ext = file.name.split('.').pop().toLowerCase() || "jpg";
            const presignResponse = await fetch(`${API_BASE}/presign?userId=${encodeURIComponent(userId)}&ext=${ext}`);
            
            if (!presignResponse.ok) {
                throw new Error(`ไม่สามารถรับ Presigned URL (HTTP ${presignResponse.status})`);
            }
            const presignData = await presignResponse.json();

            // 2. Prepare form data for direct S3 upload
            const formData = new FormData();
            Object.entries(presignData.upload.fields).forEach(([key, value]) => {
                formData.append(key, value);
            });
            formData.append("file", file);

            // 3. Upload the file directly to S3
            statusMessage.textContent = "กำลังอัปโหลดไฟล์...";
            const uploadResponse = await fetch(presignData.upload.url, {
                method: "POST",
                body: formData,
            });

            if (!uploadResponse.ok) {
                throw new Error(`การอัปโหลดล้มเหลว (HTTP ${uploadResponse.status})`);
            }

            statusMessage.textContent = "✅ อัปโหลดสำเร็จ!";
            
            // Here you can add logic to fetch results after upload is successful
            // For example: fetchResults(presignData.key);

        } catch (error) {
            console.error("Upload Error:", error);
            statusMessage.textContent = `❌ เกิดข้อผิดพลาด: ${error.message}`;
        }
    }
});