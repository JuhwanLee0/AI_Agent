/**
 * Tree Of Life Global Missions - Gallery & Admin Management Engine
 */

const STORAGE_KEY = 'tree_of_life_gallery_items_v1';
const ADMIN_AUTH_KEY = 'tree_of_life_admin_auth';

class GalleryManager {
  constructor() {
    this.items = this.loadItems();
    this.activeFilter = 'all';
    this.currentLightboxIndex = -1;
    this.isAdmin = localStorage.getItem(ADMIN_AUTH_KEY) === 'true';
  }

  loadItems() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        return JSON.parse(saved);
      }
    } catch (e) {
      console.error('Failed to load gallery items from localStorage:', e);
    }
    return [...INITIAL_GALLERY_DATA];
  }

  saveItems() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.items));
    } catch (e) {
      console.error('Failed to save gallery items:', e);
      if (e.name === 'QuotaExceededError') {
        alert('브라우저 저장 공간이 가득 찼습니다. 고용량 이미지 대신 웹 최적화 이미지를 사용해주세요.');
      }
    }
  }

  getFilteredItems() {
    if (this.activeFilter === 'all') {
      return this.items;
    }
    return this.items.filter(item => item.category === this.activeFilter);
  }

  addItem(newItem) {
    const item = {
      id: 'mission-' + Date.now(),
      ...newItem
    };
    this.items.unshift(item);
    this.saveItems();
    this.render();
    return item;
  }

  deleteItem(id) {
    this.items = this.items.filter(item => item.id !== id);
    this.saveItems();
    this.render();
  }

  resetToDefault() {
    if (confirm('갤러리 데이터를 초기 상태로 복원하시겠습니까? (직접 추가한 사진이 삭제됩니다)')) {
      this.items = [...INITIAL_GALLERY_DATA];
      this.saveItems();
      this.render();
      showToast('초기 갤러리 데이터로 복원되었습니다.', 'info');
    }
  }

  setFilter(category) {
    this.activeFilter = category;
    this.render();
  }

  toggleAdmin(forceState) {
    this.isAdmin = forceState !== undefined ? forceState : !this.isAdmin;
    localStorage.setItem(ADMIN_AUTH_KEY, this.isAdmin ? 'true' : 'false');
    this.renderAdminUI();
    this.render();
  }

  render() {
    const container = document.getElementById('gallery-grid');
    if (!container) return;

    const filtered = this.getFilteredItems();
    
    if (filtered.length === 0) {
      container.innerHTML = `
        <div class="col-span-full py-16 text-center text-[#575E59]">
          <svg class="w-12 h-12 mx-auto mb-3 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
          </svg>
          <p class="text-lg font-serif text-[#1B3D2F]">등록된 사진이 없습니다.</p>
          <p class="text-sm mt-1">관리자 모드에서 새로운 사진을 업로드해보세요.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = filtered.map((item, index) => {
      return `
        <div class="gallery-item group rounded-lg" data-id="${item.id}" data-index="${index}">
          <div class="relative overflow-hidden cursor-pointer" onclick="galleryApp.openLightbox('${item.id}')">
            <img src="${item.imageUrl}" alt="${item.title}" loading="lazy" class="w-full object-cover rounded-t-lg max-h-96" />
            <div class="gallery-overlay">
              <span class="text-xs uppercase font-semibold tracking-wider text-[#C26D43] mb-1">${item.categoryLabel || item.category}</span>
              <h3 class="text-lg font-serif font-bold text-white leading-snug">${item.title}</h3>
              <p class="text-xs text-stone-200 mt-1 line-clamp-2">${item.caption}</p>
              <div class="flex items-center justify-between text-[11px] text-stone-300 mt-3 pt-2 border-t border-white/20">
                <span>📍 ${item.location || '사역 현장'}</span>
                <span>📅 ${item.date}</span>
              </div>
            </div>
          </div>
          
          <div class="p-4 bg-[#F4F0E8] border-t border-[#E5E0D6] flex items-center justify-between">
            <div>
              <span class="text-xs font-semibold text-[#1B3D2F]">${item.title}</span>
              <p class="text-[11px] text-[#575E59]">${item.location ? item.location + ' · ' : ''}${item.date}</p>
            </div>
            ${this.isAdmin ? `
              <button onclick="event.stopPropagation(); galleryApp.deletePhoto('${item.id}')" 
                      class="text-xs px-2.5 py-1 text-red-700 hover:bg-red-100 rounded border border-red-200 transition-colors flex items-center gap-1"
                      title="사진 삭제">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                </svg>
                삭제
              </button>
            ` : `
              <button onclick="galleryApp.openLightbox('${item.id}')" class="text-xs text-[#1B3D2F] hover:text-[#C26D43] font-medium flex items-center gap-0.5">
                확대보기
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                </svg>
              </button>
            `}
          </div>
        </div>
      `;
    }).join('');

    // 필터 버튼 활성화 상태 갱신
    document.querySelectorAll('.filter-btn').forEach(btn => {
      if (btn.dataset.category === this.activeFilter) {
        btn.classList.add('active', 'bg-[#1B3D2F]', 'text-white');
        btn.classList.remove('bg-white', 'text-[#191C1A]');
      } else {
        btn.classList.remove('active', 'bg-[#1B3D2F]', 'text-white');
        btn.classList.add('bg-white', 'text-[#191C1A]');
      }
    });
  }

  renderAdminUI() {
    const adminPanel = document.getElementById('admin-action-bar');
    const adminToggleBtn = document.getElementById('admin-toggle-btn');
    const adminStatusBadge = document.getElementById('admin-status-badge');

    if (adminPanel) {
      adminPanel.style.display = this.isAdmin ? 'flex' : 'none';
    }
    if (adminToggleBtn) {
      adminToggleBtn.innerText = this.isAdmin ? '관리자 모드 종료' : '관리자 모드 접속';
    }
    if (adminStatusBadge) {
      adminStatusBadge.style.display = this.isAdmin ? 'inline-flex' : 'none';
    }
  }

  openLightbox(id) {
    const filtered = this.getFilteredItems();
    const index = filtered.findIndex(item => item.id === id);
    if (index === -1) return;

    this.currentLightboxIndex = index;
    this.updateLightboxContent();

    const modal = document.getElementById('lightbox-modal');
    if (modal) {
      modal.classList.remove('hidden');
      modal.classList.add('flex');
      document.body.style.overflow = 'hidden';
    }
  }

  closeLightbox() {
    const modal = document.getElementById('lightbox-modal');
    if (modal) {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      document.body.style.overflow = '';
    }
  }

  navigateLightbox(direction) {
    const filtered = this.getFilteredItems();
    if (filtered.length === 0) return;

    this.currentLightboxIndex = (this.currentLightboxIndex + direction + filtered.length) % filtered.length;
    this.updateLightboxContent();
  }

  updateLightboxContent() {
    const filtered = this.getFilteredItems();
    const item = filtered[this.currentLightboxIndex];
    if (!item) return;

    const img = document.getElementById('lightbox-img');
    const title = document.getElementById('lightbox-title');
    const category = document.getElementById('lightbox-category');
    const caption = document.getElementById('lightbox-caption');
    const meta = document.getElementById('lightbox-meta');
    const count = document.getElementById('lightbox-counter');

    if (img) img.src = item.imageUrl;
    if (title) title.innerText = item.title;
    if (category) category.innerText = item.categoryLabel || item.category;
    if (caption) caption.innerText = item.caption;
    if (meta) meta.innerText = `📍 ${item.location || '사역지'} · 📅 ${item.date}${item.photographer ? ` · 📷 ${item.photographer}` : ''}`;
    if (count) count.innerText = `${this.currentLightboxIndex + 1} / ${filtered.length}`;
  }

  deletePhoto(id) {
    if (confirm('이 사진을 정말 갤러리에서 삭제하시겠습니까?')) {
      this.deleteItem(id);
      showToast('사진이 삭제되었습니다.', 'info');
    }
  }
}

// Toast Utility
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  const bgClass = type === 'success' ? 'bg-[#1B3D2F] text-white' : type === 'error' ? 'bg-red-800 text-white' : 'bg-stone-800 text-white';
  
  toast.className = `${bgClass} px-5 py-3 rounded-lg shadow-lg text-sm font-medium flex items-center gap-2 transform transition-all duration-300 translate-y-4 opacity-0`;
  toast.innerHTML = `
    <span>${type === 'success' ? '✓' : 'ℹ'}</span>
    <span>${message}</span>
  `;

  container.appendChild(toast);

  // Trigger animation
  setTimeout(() => {
    toast.classList.remove('translate-y-4', 'opacity-0');
  }, 10);

  // Auto remove
  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}
