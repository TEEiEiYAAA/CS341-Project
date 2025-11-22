    // --------------------------------------------------------
    // PART 1: UI LOGIC (การทำงานของปุ่ม, เมนู, เลือกไฟล์)
    // --------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
      // Element References
      const hamburgerMenu = document.getElementById('hamburger-menu');
      const closeMenu = document.getElementById('close-menu');
      const sidebar = document.querySelector('.sidebar');
      const fileInput = document.getElementById('file');
      const fileNameText = document.getElementById('file-name-text');
      const removeFileBtn = document.getElementById('remove-file-btn');
      const processBtn = document.getElementById('btnUpload');
      
      // Modals
      const wrongTypeModal = document.getElementById('wrong-type-modal');
      const confirmClearModal = document.getElementById('confirm-clear-modal');
      const wrongTypeClearBtn = document.getElementById('wrong-type-clear-btn');
      const confirmClearBtn = document.getElementById('confirm-clear-btn');
      const closeConfirmModalBtn = document.getElementById('close-confirm-modal-btn');
      
      const allowedTypes = ['image/jpeg', 'image/png'];

      // Sidebar Logic
      if (hamburgerMenu && sidebar) {
        hamburgerMenu.addEventListener('click', () => sidebar.classList.add('open'));
      }
      if (closeMenu && sidebar) {
        closeMenu.addEventListener('click', () => sidebar.classList.remove('open'));
      }

      // Function Reset ค่าต่างๆ (ใช้ตอนกดลบไฟล์ หรือตอนอัปโหลดผิด)
      window.resetFileInput = () => { // ประกาศเป็น window เพื่อให้เรียกใช้ได้ทั่ว
        fileInput.value = '';
        fileNameText.textContent = '<No File Chosen...>';
        fileNameText.classList.remove('selected');
        removeFileBtn.classList.add('hidden');
        processBtn.disabled = true;
        document.getElementById('status').textContent = '';
        
        // ซ่อนผลลัพธ์และสินค้าเมื่อเคลียร์ไฟล์ (Reset กลับไปเป็นกล่องเปล่า)
        document.getElementById('analysis-container').classList.add('hidden');
        document.getElementById('product-container').classList.add('hidden');
      };

      // File Input Change Logic
      if (fileInput) {
        fileInput.addEventListener('change', () => {
          const file = fileInput.files[0];
          if (file) {
            if (allowedTypes.includes(file.type)) {
              fileNameText.textContent = file.name;
              fileNameText.classList.add('selected');
              removeFileBtn.classList.remove('hidden');
              processBtn.disabled = false;
            } else {
              window.resetFileInput();
              wrongTypeModal.classList.remove('hidden');
            }
          } else {
            window.resetFileInput();
          }
        });
      }

      // Modal Button Listeners
      if (removeFileBtn) removeFileBtn.addEventListener('click', () => confirmClearModal.classList.remove('hidden'));
      if (wrongTypeClearBtn) wrongTypeClearBtn.addEventListener('click', () => wrongTypeModal.classList.add('hidden'));
      if (confirmClearBtn) confirmClearBtn.addEventListener('click', () => {
        window.resetFileInput();
        confirmClearModal.classList.add('hidden');
      });
      if (closeConfirmModalBtn) closeConfirmModalBtn.addEventListener('click', () => confirmClearModal.classList.add('hidden'));
    });

    // --------------------------------------------------------
    // PART 2: API & PROCESSING LOGIC (การอัปโหลดและแสดงผล)
    // --------------------------------------------------------
    const API_BASE = "https://6w4jivfjnf.execute-api.us-east-1.amazonaws.com"; 

    document.getElementById("btnUpload").addEventListener("click", async () => {
      const status = document.getElementById("status");
      const file = document.getElementById("file").files[0];
      
      if (!file) {
        status.textContent = "กรุณาเลือกรูปก่อนอัปโหลด";
        return;
      }

      try {
        status.textContent = "กำลังประมวลผล...";
        
        // 1. ขอ Presigned URL (API เดิมของคุณ)
        const ext = file.name.split('.').pop().toLowerCase() || "jpg";
        const pres = await fetch(`${API_BASE}/presign?ext=${ext}`);
        if (!pres.ok) throw new Error("Presign request failed");
        const data = await pres.json();

        // 2. อัปโหลดรูปไป S3 (API เดิมของคุณ)
        const form = new FormData();
        Object.entries(data.upload.fields).forEach(([k, v]) => form.append(k, v));
        form.append("file", file);
        const resp = await fetch(data.upload.url, { method: "POST", body: form });
        if (!resp.ok) throw new Error("Upload failed: " + resp.status);

        status.innerHTML = `✅ ประมวลผลสำเร็จ!`;

        // ---------------------------------------------------------
        // 3. จัดการข้อมูล JSON (ส่วนที่เพิ่มใหม่)
        // จำลองข้อมูล JSON ที่ได้รับกลับมา (ตามรูปตัวอย่างของคุณ)
        // *หมายเหตุ: ในอนาคตคุณต้อง Fetch json นี้มาจาก DynamoDB หรือ API
        // ---------------------------------------------------------
        const mockJsonResponse = {
            "user_info": { 
                "bucket": "dermadataaa",
                "key": data.upload.fields.key // ใช้ Key จริงจากการอัปโหลด
            },
            "analysis_labels": [
                "Acne",
                "Enlarged-Pores"
            ],
            "recommendations": [
                {
                    "problem": "Acne",
                    "name": "the perfecting treatment",
                    "brand": "la mer",
                    "price": 8942.5,
                    "image_url": "https://i0.wp.com/mydbale.com/wp-content/uploads/2022/03/Artboard-1-copy-17-1.jpg", 
                    "ingredients": "water | dimethicone | isododecane | algae (seaweed) extract"
                },
                {
                     "problem": "Enlarged-Pores",
                     "name": "Pore Minimizing Serum",
                     "brand": "Clarins",
                     "price": 2500,
                     "image_url": "https://via.placeholder.com/150", 
                     "ingredients": "Aqua | Glycerin | Silica"
                }
            ]
        };

        // เรียกฟังก์ชันวาด UI
        renderUI(mockJsonResponse);

      } catch (err) {
        status.textContent = "❌ เกิดข้อผิดพลาด: " + err.message;
        console.error(err);
      }
    });

    // --- ฟังก์ชันสำหรับวาด UI จาก JSON (Helper Function) ---
    function renderUI(data) {
        // A. ส่วนผลลัพธ์ (Analysis)
        const analysisContainer = document.getElementById('analysis-container');
        const analysisText = document.getElementById('analysis-text');
        
        // แปลง Array labels เป็นข้อความคั่นด้วย comma
        const labels = data.analysis_labels.join(', '); 
        analysisText.innerHTML = `“ตรวจพบปัญหา: <b>${labels}</b> <br>ผิวหน้าของท่านต้องการการดูแลเป็นพิเศษในจุดเหล่านี้...”`;
        
        analysisContainer.classList.remove('hidden'); // ลบ class hidden เพื่อโชว์เนื้อหา

        // B. ส่วนสินค้าแนะนำ (Products)
        const productContainer = document.getElementById('product-container');
        const productList = document.getElementById('product-list');
        productList.innerHTML = ''; // เคลียร์ของเก่า (ถ้ามี)

        data.recommendations.forEach(item => {
            // แปลง ingredients ที่คั่นด้วย | ให้เป็น <option> ใน Dropdown
            const ingredientOptions = item.ingredients.split('|').map(ing => `<option>${ing.trim()}</option>`).join('');

            // สร้าง HTML การ์ดสินค้า
            const cardHTML = `
            <div class="product-item">
                <img src="${item.image_url}" alt="${item.name}" class="product-img">
                <div class="product-info">
                    <div class="product-header">
                        <span class="product-name">${item.brand} - ${item.name}</span>
                        <span class="product-price">ราคา: ${item.price.toLocaleString()} บาท</span>
                    </div>
                    <div class="product-problem-tag">สำหรับ: ${item.problem}</div>
                    
                    <select class="product-select">
                        <option selected disabled>ดูส่วนผสม (Ingredients)</option>
                        ${ingredientOptions}
                    </select>
                </div>
            </div>
            `;
            productList.innerHTML += cardHTML;
        });

        productContainer.classList.remove('hidden'); // ลบ class hidden เพื่อโชว์เนื้อหา
    }