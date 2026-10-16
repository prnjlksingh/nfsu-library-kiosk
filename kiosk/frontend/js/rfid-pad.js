/**
 * NFSU Central Library Self-Service Kiosk - Dual-Zone RFID Pad Visualizer
 * National Forensic Sciences University, Gandhinagar
 * Integrated with Koha 26 ILMS (PS-2)
 *
 * Implements:
 * - Top Large Zone: Avery Dennison Smartrac RaceTrack 13.56 MHz HF (ISO 15693)
 *   Multi-tag Anti-Collision (2 Books Simultaneously on Pad)
 * - Bottom-Right Compact Zone: HID OMNIKEY Contactless MIFARE Reader (ISO 14443A)
 * - Real-time AFI Security Tag State Rendering (0x07 Armed / 0xC2 Disarmed)
 */

class RFIDPadVisualizer {
  constructor() {
    this.booksContainer = null;
    this.cardContainer = null;
  }

  init() {
    this.booksContainer = document.getElementById('books-pad-container');
    this.cardContainer = document.getElementById('card-tap-container');
  }

  renderPadState(padState) {
    if (!this.booksContainer || !this.cardContainer) this.init();
    if (!padState) return;

    // 1. Render Books Zone
    const books = padState.books_zone ? padState.books_zone.books : [];
    this.renderBooksZone(books);

    // 2. Render Patron Card Zone
    const cardData = padState.card_zone ? padState.card_zone.patron : null;
    this.renderCardZone(cardData);
  }

  renderBooksZone(books) {
    if (!this.booksContainer) return;

    if (!books || books.length === 0) {
      this.booksContainer.innerHTML = `
        <div class="empty-book-pad">
          <i class="fas fa-book-open"></i>
          <h4 style="font-size:14px; color:#64748b; margin:0;">Place 1 or 2 Books on the Pad</h4>
          <p style="font-size:12px; margin:0;">Lay books flat with RFID tag facing the sensor surface.<br>
          <span style="color:#d97706; font-weight:600;">ISO 15693 Multi-Tag Anti-Collision Active (Max 2 books)</span></p>
        </div>
      `;
      return;
    }

    let html = '';
    books.forEach((book, idx) => {
      const isArmed = (book.afi === '0x07');
      const borderClass = isArmed ? 'armed-border' : 'disarmed-border';
      const afiBadgeClass = isArmed ? 'armed' : 'disarmed';
      const afiLabel = isArmed ? 'AFI: 0x07 [ARMED - EAS ON]' : 'AFI: 0xC2 [DISARMED - EAS OFF]';
      const icon = isArmed ? 'fa-shield-alt' : 'fa-check-circle';

      html += `
        <div class="book-pad-item ${borderClass}" id="book-item-${book.barcode}">
          <div class="book-pad-cover">
            <span class="book-cover-chip-tag"><i class="fas fa-microchip"></i> ISO 15693</span>
            <div class="book-cover-title">${book.title.slice(0, 38)}...</div>
            <div class="book-cover-author">${book.author}</div>
          </div>
          <div class="book-pad-details">
            <div>
              <div style="font-size:10px; font-weight:700; color:#d97706; text-transform:uppercase;">Book #${idx + 1} on RFID Pad</div>
              <div class="book-pad-title">${book.title}</div>
              <div class="book-pad-meta">
                <span><i class="fas fa-user-edit"></i> ${book.author}</span><br>
                <span><i class="fas fa-barcode"></i> Barcode: <strong>${book.barcode}</strong></span> |
                <span><i class="fas fa-map-marker-alt"></i> ${book.call_number}</span>
              </div>
            </div>
            <div class="book-pad-footer">
              <span class="afi-badge ${afiBadgeClass}">
                <i class="fas ${icon}"></i> ${afiLabel}
              </span>
              <button class="btn-sim sim-gate" style="padding:2px 8px; font-size:10px;"
                      onclick="window.kioskApp.testPassGate('${book.barcode}')"
                      title="Test Gate Buzzer for this book">
                <i class="fas fa-door-open"></i> Test Gate
              </button>
            </div>
          </div>
        </div>
      `;
    });

    this.booksContainer.innerHTML = html;
  }

  renderCardZone(patron) {
    if (!this.cardContainer) return;

    if (!patron) {
      this.cardContainer.innerHTML = `
        <div class="card-zone-left">
          <div class="card-tap-icon-wrapper">
            <i class="fas fa-id-card"></i>
            <div class="rfid-wave-ring"></div>
          </div>
          <div class="card-zone-text">
            <h4>TAP PATRON ID CARD HERE</h4>
            <p>Place your NFSU Student / Faculty Smart Card (HID OMNIKEY MIFARE Reader)</p>
          </div>
        </div>
        <div>
          <button class="btn-nfsu btn-nfsu-gold" style="padding:6px 14px; font-size:12px;" onclick="window.kioskApp.openAuthModal()">
            <i class="fas fa-user-check"></i> 3-Way Auth Hub
          </button>
        </div>
      `;
    } else {
      this.cardContainer.innerHTML = `
        <div class="card-zone-left">
          <div class="card-tap-icon-wrapper" style="background:rgba(16,185,129,0.15); border-color:#10b981; color:#10b981;">
            <i class="fas fa-check-circle"></i>
          </div>
          <div class="card-zone-text">
            <h4 style="color:#002147;">${patron.name} (${patron.card_number})</h4>
            <p style="color:#059669; font-weight:600;">
              <i class="fas fa-id-badge"></i> MIFARE UID: ${patron.mifare_uid} | ${patron.role}
            </p>
          </div>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span class="badge" style="background:#002147; color:white; font-size:11px; padding:4px 8px; border-radius:4px;">
            Issued: ${patron.charged_count} / 2
          </span>
          <button class="btn-nfsu btn-nfsu-outline" style="padding:6px 10px; font-size:11px;" onclick="window.kioskApp.logoutPatron()">
            <i class="fas fa-sign-out-alt"></i> Eject
          </button>
        </div>
      `;
    }
  }
}

window.rfidPad = new RFIDPadVisualizer();
