/**
 * Tree Of Life Global Missions - Main Application Controller
 */

let galleryApp;

document.addEventListener('DOMContentLoaded', () => {
  // 1. 갤러리 인스턴스 초기화
  galleryApp = new GalleryManager();
  galleryApp.render();
  galleryApp.renderAdminUI();

  // 2. 필터 버튼 이벤트 리스너
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const category = e.currentTarget.dataset.category;
      galleryApp.setFilter(category);
    });
  });

  // 3. 업로드 폼 및 드래그 앤 드롭 설정
  setupUploadDropzone();

  // 4. 키보드 단축키 이벤트
  window.addEventListener('keydown', (e) => {
    const lightbox = document.getElementById('lightbox-modal');
    const isLightboxOpen = lightbox && !lightbox.classList.contains('hidden');

    if (e.key === 'Escape') {
      if (isLightboxOpen) galleryApp.closeLightbox();
      closeUploadModal();
      closeDonateModal();
    } else if (isLightboxOpen) {
      if (e.key === 'ArrowLeft') galleryApp.navigateLightbox(-1);
      if (e.key === 'ArrowRight') galleryApp.navigateLightbox(1);
    }
  });

  // 5. 모바일 메뉴 토글
  const mobileMenuBtn = document.getElementById('mobile-menu-btn');
  const mobileMenu = document.getElementById('mobile-menu');
  if (mobileMenuBtn && mobileMenu) {
    mobileMenuBtn.addEventListener('click', () => {
      mobileMenu.classList.toggle('hidden');
    });
  }
});

// 관리자 모드 토글 (간단 패스워드 검증)
function handleAdminToggle() {
  if (galleryApp.isAdmin) {
    galleryApp.toggleAdmin(false);
    showToast('관리자 모드가 종료되었습니다.', 'info');
  } else {
    const pass = prompt('관리자 비밀번호를 입력하세요 (기본 데모 비밀번호: 1234):', '1234');
    if (pass === '1234' || pass === 'admin') {
      galleryApp.toggleAdmin(true);
      showToast('관리자 모드로 전환되었습니다. 사진 업로드 및 삭제가 가능합니다.', 'success');
    } else if (pass !== null) {
      alert('비밀번호가 올바르지 않습니다. (데모: 1234)');
    }
  }
}

// 업로드 모달 제어
function openUploadModal() {
  const modal = document.getElementById('upload-modal');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
  }
}

function closeUploadModal() {
  const modal = document.getElementById('upload-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = '';
    // 폼 초기화
    document.getElementById('upload-form')?.reset();
    const previewContainer = document.getElementById('upload-preview-container');
    if (previewContainer) previewContainer.classList.add('hidden');
    window._uploadedImageBase64 = null;
  }
}

// 기부(Contribute) 모달 제어
function openDonateModal() {
  const modal = document.getElementById('donate-modal');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
  }
}

function closeDonateModal() {
  const modal = document.getElementById('donate-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = '';
  }
}

function handleDonationSubmit(event) {
  event.preventDefault();
  closeDonateModal();
  showToast('소중한 사역 후원 신청이 접수되었습니다. 담당자가 안내 메일을 발송합니다.', 'success');
}

// 드래그 앤 드롭 & 파일 인풋 설정
function setupUploadDropzone() {
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  const previewContainer = document.getElementById('upload-preview-container');
  const previewImg = document.getElementById('upload-preview-img');

  if (!dropzone || !fileInput) return;

  dropzone.addEventListener('click', () => fileInput.click());

  ['dragenter', 'dragover'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleImageFile(files[0]);
    }
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleImageFile(e.target.files[0]);
    }
  });

  function handleImageFile(file) {
    if (!file.type.startsWith('image/')) {
      alert('이미지 파일(JPG, PNG, WebP 등)만 업로드할 수 있습니다.');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      window._uploadedImageBase64 = e.target.result;
      if (previewImg && previewContainer) {
        previewImg.src = e.target.result;
        previewContainer.classList.remove('hidden');
      }
    };
    reader.readAsDataURL(file);
  }

  // 폼 제출 처리
  const form = document.getElementById('upload-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();

      const imageUrl = window._uploadedImageBase64 || document.getElementById('image-url-input')?.value.trim();
      if (!imageUrl) {
        alert('사진 파일을 첨부하거나 이미지 웹 URL을 입력해주세요.');
        return;
      }

      const categorySelect = document.getElementById('photo-category');
      const selectedCategory = categorySelect.value;
      const selectedCategoryLabel = categorySelect.options[categorySelect.selectedIndex].text;

      const newPhoto = {
        title: document.getElementById('photo-title').value.trim(),
        category: selectedCategory,
        categoryLabel: selectedCategoryLabel,
        location: document.getElementById('photo-location').value.trim() || '사역지',
        date: document.getElementById('photo-date').value || new Date().toISOString().split('T')[0],
        imageUrl: imageUrl,
        caption: document.getElementById('photo-caption').value.trim(),
        photographer: document.getElementById('photo-author').value.trim() || 'Mission Team'
      };

      galleryApp.addItem(newPhoto);
      closeUploadModal();
      showToast('새로운 선교 사진이 갤러리에 성공적으로 등록되었습니다!', 'success');
      
      // 갤러리 섹션으로 부드럽게 스크롤
      document.getElementById('gallery')?.scrollIntoView({ behavior: 'smooth' });
    });
  }
}
