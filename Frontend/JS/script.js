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

  // 🔧 ใส่ URL ของ API Gateway (ที่ชี้ Lambda presigner)
  const API_ENDPOINT = 'https://wzs3lu83ng.execute-api.us-east-1.amazonaws.com/presign';

  let isInteractionBlocked = false;

  // --- Sidebar / Modal เดิม ---
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

  // --- ส่งฟอร์ม ---
  uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (isInteractionBlocked) return;

    const selectedFile = fileInput.files[0];

    // 1) เก็บค่าจาก checkbox
    const selectedCheckboxes = document.querySelectorAll('input[name="skin-type"]:checked');
    const selectedSkinTypes = Array.from(selectedCheckboxes).map(cb => cb.value); // ["ผิวมัน", "ผิวแพ้ง่าย"]
    const skinTypesString = selectedSkinTypes.join(',');

    // Validation
    if (!selectedFile) {
      resultMessage.textContent = 'กรุณาอัปโหลดรูปภาพก่อน';
      resultMessage.style.color = 'red';
      return;
    }
    if (!skinTypesString) {
      resultMessage.textContent = 'กรุณาเลือกสภาพผิวอย่างน้อย 1 ข้อ';
      resultMessage.style.color = 'red';
      return;
    }
    if (API_ENDPOINT === 'YOUR_API_GATEWAY_URL_HERE') {
      resultMessage.textContent = 'Error: ยังไม่ได้ตั้งค่า API Gateway URL';
      resultMessage.style.color = 'red';
      return;
    }

    resultMessage.textContent = 'กำลังเตรียมการอัปโหลด...';
    resultMessage.style.color = 'var(--text-color)';

    try {
      // 2) สร้าง/จำ sessionId
      const sessionId = localStorage.getItem('sessionId') || crypto.randomUUID();
      localStorage.setItem('sessionId', sessionId);

      const ext = (selectedFile.name.split('.').pop() || 'jpg').toLowerCase();

      // 3) ขอ Presigned URL (POST) พร้อมส่ง sessionId + skinTypes
      const presResp = await fetch(API_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fileName: selectedFile.name,
          fileType: selectedFile.type,
          sessionId,
          skinTypes: skinTypesString
        })
      });
      if (!presResp.ok) {
        const err = await presResp.text();
        throw new Error(`Cannot get upload URL: ${err || presResp.statusText}`);
      }

      // presigner ควรคืน { uploadURL, key, bucket, requiredHeaders }
      const { uploadURL, key, bucket, requiredHeaders } = await presResp.json();

      resultMessage.textContent = 'กำลังอัปโหลดไฟล์...';

      // 4) อัปโหลดด้วย presigned PUT + header meta (ต้องตรงกับที่เซ็นมา)
      const putHeaders = new Headers({ 'Content-Type': selectedFile.type });
      if (requiredHeaders) {
        Object.entries(requiredHeaders).forEach(([k, v]) => putHeaders.set(k, v));
      }
      const uploadRes = await fetch(uploadURL, { method: 'PUT', headers: putHeaders, body: selectedFile });
      if (!uploadRes.ok) throw new Error('File upload failed.');

      resultMessage.textContent = '✅ อัปโหลดสำเร็จ! กำลังรอผลวิเคราะห์...';

      // 5) สร้าง URL ผลลัพธ์ แล้วลองดึงหลัง 5 วิ
      const resultsKey = key.replace('uploads/', 'results/') + '.json';
      const s3Host = new URL(uploadURL).host; // <bucket>.s3.<region>.amazonaws.com
      const resultUrl = `https://${s3Host}/${resultsKey}`;

      setTimeout(async () => {
        try {
          const res = await fetch(resultUrl);
          if (!res.ok) { resultMessage.textContent = 'ยังไม่มีผลลัพธ์ โปรดลองอีกสักครู่'; return; }
          const data = await res.json();
          const labels = Array.isArray(data.labels) ? data.labels.join(', ') : '-';
          const userSkin = data.user_skin_types || skinTypesString || '-';
          resultMessage.innerHTML = `
            <b>สภาพผิวที่ผู้ใช้เลือก:</b> ${userSkin}<br/>
            <b>ผลจากโมเดล:</b> ${labels}
          `;
        } catch (err) {
          resultMessage.textContent = `ดึงผลล้มเหลว: ${err.message}`;
        }
      }, 5000);

    } catch (error) {
      resultMessage.textContent = `Error: ${error.message}`;
      resultMessage.style.color = 'red';
    }
  });
});
