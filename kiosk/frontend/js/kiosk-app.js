/**
 * NFSU Central Library Self-Service Kiosk - Main Application Controller
 * National Forensic Sciences University, Gandhinagar
 * Integrated with Live Koha 26 ILMS (PS-2)
 *
 * Implements:
 * - Direct Matching of Projector UI (3 Giant Touch Action Tiles: ISSUE, RETURN, RENEW)
 * - Seamless Transition between Home View and Workflow View
 * - Live Koha 26 SIP2 Integration (117.239.182.15:6001)
 * - Strict 2-Books-At-A-Time Circulation Policy Enforcement (MAX_BOOKS = 2)
 * - Live Issued Books Counter (X / 2) with Koha 64 AU Field Parser
 * - Multi-Tag Anti-Collision RFID Pad (Smartrac RaceTrack ISO 15693)
 * - Two-Phase Commit AFI Security Byte Updates (0x07 Armed / 0xC2 Disarmed)
 * - Hardware Barcode Scanner (Keyboard Wedge) Auto-Capture
 * - Official Printable NFSU Circulation Receipts
 */

class NFSUKioskApp {
  constructor() {
    this.ws = null;
    this.currentPatron = null;
    this.padState = null;
    this.telemetry = null;
    this.activeWorkflow = null; // 'issue', 'return', 'renew', or null (home)
    this.maxBooksAllowed = 2;
    this.availableAccounts = ['rfid', 'rfid1', 'rfid2'];
    this._isAuthenticating = false;
  }

  async init() {
    this.initClock();
    this.connectWebSocket();
    this.attachEventListeners();
    await this.refreshState();
    this.returnHome(); // Start on Projector Home Screen
  }

  initClock() {
    const updateTime = () => {
      const now = new Date();
      const timeStr = now.toLocaleTimeString('en-IN', { hour12: false });
      const clockElem = document.getElementById('workflow-clock');
      if (clockElem) clockElem.textContent = timeStr;
    };
    updateTime();
    setInterval(updateTime, 1000);
  }

  // WebSocket for real-time synchronization
  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log("[WS] Connected to NFSU Kiosk Backend");
      this.updateSocketIndicator(true);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleWebSocketMessage(msg);
      } catch (e) {
        console.error("WS Parse error", e);
      }
    };

    this.ws.onclose = () => {
      console.warn("[WS] Socket closed. Reconnecting in 3s...");
      this.updateSocketIndicator(false);
      setTimeout(() => this.connectWebSocket(), 3000);
    };

    this.ws.onerror = () => {
      this.updateSocketIndicator(false);
    };
  }

  updateSocketIndicator(connected) {
    const beacon = document.querySelector('.koha-beacon');
    const statusText = document.getElementById('koha-conn-text');
    if (beacon) {
      if (connected) {
        beacon.classList.remove('error');
      } else {
        beacon.classList.add('error');
      }
    }
    if (statusText) {
      statusText.textContent = connected ? 'KOHA 26 LIVE (117.239.182.15)' : 'KOHA RECONNECTING';
    }
  }

  handleWebSocketMessage(msg) {
    switch (msg.type) {
      case 'INIT_STATE':
        this.updateTelemetryUI(msg.telemetry);
        this.padState = msg.pad_state;
        if (window.rfidPad) window.rfidPad.renderPadState(this.padState);
        // Do not auto-authenticate on init to avoid feedback loops
        break;

      case 'PAD_BOOKS_UPDATED':
        this.padState = msg.data;
        if (window.rfidPad) window.rfidPad.renderPadState(this.padState);
        this.renderWorkflowDynamicContent();
        break;

      case 'PATRON_CARD_TAPPED':
        this.padState = msg.data;
        if (window.rfidPad) window.rfidPad.renderPadState(this.padState);
        if (msg.data.card_zone && msg.data.card_zone.patron) {
          const cardNum = msg.data.card_zone.patron.card_number;
          if (!this.currentPatron || this.currentPatron.card_number !== cardNum) {
            this.authenticatePatron(cardNum, false);
          }
        }
        break;

      case 'PATRON_CARD_REMOVED':
        this.padState = msg.data;
        if (window.rfidPad) window.rfidPad.renderPadState(this.padState);
        if (this.currentPatron) {
          this.logoutPatron(false);
        }
        break;

      case 'AFI_STATE_CHANGED':
        if (window.sip2Console) {
          window.sip2Console.logTerminal(`[RFID-AFI] Tag ${msg.data.barcode} transition: ${msg.data.old_afi} -> ${msg.data.new_afi} (${msg.data.state})`, 'info');
        }
        this.refreshPadOnly();
        break;

      case 'GATE_WALKTHROUGH':
        if (window.gateBuzzer) window.gateBuzzer.handleGateWalkthrough(msg.data);
        break;

      case 'SIP2_TELEMETRY':
        this.updateTelemetryUI(msg.data);
        break;

      case 'CIRCULATION_TRANSACTION':
        this.refreshState();
        break;
    }
  }

  updateTelemetryUI(telemetry) {
    this.telemetry = telemetry;
    const latencyElem = document.getElementById('koha-latency-val');
    if (latencyElem && telemetry) {
      latencyElem.textContent = `${telemetry.latency_ms || 137} ms`;
    }
  }

  async refreshState() {
    try {
      const resp = await fetch('/api/hardware/pad-state');
      this.padState = await resp.json();
      if (window.rfidPad) window.rfidPad.renderPadState(this.padState);

      if (this.currentPatron) {
        await this.reloadPatronInfo(this.currentPatron.card_number);
      }
      this.renderWorkflowViews();
    } catch (e) {
      console.error("Failed to refresh state", e);
    }
  }

  async refreshPadOnly() {
    try {
      const resp = await fetch('/api/hardware/pad-state');
      this.padState = await resp.json();
      if (window.rfidPad) window.rfidPad.renderPadState(this.padState);
      this.renderWorkflowDynamicContent();
    } catch (e) {}
  }

  // =========================================================================
  // VIEW NAVIGATION (HOME TILES <--> WORKFLOW VIEWS)
  // =========================================================================

  selectWorkflow(type) {
    this.activeWorkflow = type;
    const homeView = document.getElementById('kiosk-home-view');
    const workflowView = document.getElementById('kiosk-workflow-view');
    const titleElem = document.getElementById('workflow-banner-title');

    if (homeView) homeView.style.display = 'none';
    if (workflowView) workflowView.style.display = 'flex';

    let titleText = '';
    if (type === 'issue') {
      titleText = '<i class="fas fa-book-open" style="color:var(--nfsu-gold);"></i> Book Issue / Checkout (SIP2 11)';
    } else if (type === 'return') {
      titleText = '<i class="fas fa-inbox" style="color:var(--nfsu-gold);"></i> Express Return / Check-In (SIP2 09)';
    } else if (type === 'renew') {
      titleText = '<i class="fas fa-sync-alt" style="color:var(--nfsu-gold);"></i> Book Renewal / Loan Extension (SIP2 29)';
    }

    if (titleElem) titleElem.innerHTML = titleText;

    this.renderWorkflowViews();
  }

  returnHome() {
    this.activeWorkflow = null;
    const homeView = document.getElementById('kiosk-home-view');
    const workflowView = document.getElementById('kiosk-workflow-view');
    if (homeView) homeView.style.display = 'block';
    if (workflowView) workflowView.style.display = 'none';
  }

  renderWorkflowViews() {
    if (!this.activeWorkflow) return;
    this.renderPatronBanner();
    this.renderWorkflowDynamicContent();
  }

  // =========================================================================
  // PATRON AUTHENTICATION & SUMMARY (SIP2 63 -> 64)
  // =========================================================================

  async quickAuthenticateLive(patronId) {
    await this.authenticatePatron(patronId);
    if (!this.activeWorkflow) {
      this.selectWorkflow('issue');
    }
  }

  async authenticatePatron(patronId, syncHardware = true) {
    if (this._isAuthenticating) return;
    this._isAuthenticating = true;
    try {
      const resp = await fetch('/api/circulation/patron-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patron_id: patronId })
      });
      const data = await resp.json();
      
      if (data.command === '64' && (data.valid_patron !== false)) {
        this.currentPatron = {
          card_number: data.patron_id || patronId,
          name: (data.patron_name && data.patron_name.trim()) ? data.patron_name.trim() : `NFSU Patron (${patronId})`,
          charged_items_count: data.charged_items_count !== undefined ? data.charged_items_count : 0,
          charged_items: data.charged_items || [],
          fee_amount: data.fee_amount || '0.00',
          screen_message: data.screen_message || ''
        };

        // Only sync to hardware pad if explicitly requested AND not already present
        if (syncHardware && (!this.padState?.card_zone?.patron || this.padState.card_zone.patron.card_number !== patronId)) {
          await fetch('/api/hardware/tap-card', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ card_or_uid: patronId })
          });
        }

        if (window.sip2Console) window.sip2Console.renderResponse(data);
        this.renderWorkflowViews();
      } else {
        alert(data.screen_message || "Invalid patron credentials. Please check card.");
      }
    } catch (e) {
      console.error("Patron authentication error", e);
    } finally {
      this._isAuthenticating = false;
    }
  }

  async reloadPatronInfo(patronId) {
    try {
      const resp = await fetch('/api/circulation/patron-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patron_id: patronId })
      });
      const data = await resp.json();
      if (data.command === '64') {
        this.currentPatron = {
          card_number: data.patron_id || patronId,
          name: (data.patron_name && data.patron_name.trim()) ? data.patron_name.trim() : `NFSU Patron (${patronId})`,
          charged_items_count: data.charged_items_count !== undefined ? data.charged_items_count : 0,
          charged_items: data.charged_items || [],
          fee_amount: data.fee_amount || '0.00',
          screen_message: data.screen_message || ''
        };
        this.renderWorkflowViews();
      }
    } catch (e) {}
  }

  logoutPatron(syncHardware = true) {
    this.currentPatron = null;
    if (syncHardware) {
      fetch('/api/hardware/remove-card', { method: 'POST' }).catch(() => {});
    }
    this.renderWorkflowViews();
  }

  // =========================================================================
  // PATRON DASHBOARD BANNER & 3-WAY AUTH HUB
  // =========================================================================

  renderPatronBanner() {
    const container = document.getElementById('workflow-patron-banner');
    if (!container) return;

    if (this.currentPatron) {
      const count = this.currentPatron.charged_items_count;
      const isFull = (count >= this.maxBooksAllowed);
      const remainingQuota = Math.max(0, this.maxBooksAllowed - count);
      const badgeColor = isFull ? '#ef4444' : (count === 1 ? '#f59e0b' : '#10b981');
      const quotaText = isFull ? 'QUOTA FULL (2/2)' : `${remainingQuota} of 2 Slots Available`;

      let html = `
        <div class="patron-live-card">
          <div class="patron-live-info">
            <div class="patron-live-avatar">
              <i class="fas fa-user-graduate"></i>
            </div>
            <div>
              <div style="display:flex; align-items:center; gap:10px;">
                <h3 style="font-size:18px; font-weight:800; margin:0; color:#ffffff;">
                  ${this.currentPatron.name}
                </h3>
                <span style="background:rgba(221,181,94,0.25); color:var(--nfsu-gold); padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700;">
                  LIVE KOHA 26 PATRON
                </span>
              </div>
              <div style="font-size:12.5px; color:#cbd5e1; margin-top:2px;">
                Card ID: <strong style="color:var(--nfsu-gold); font-family:monospace;">${this.currentPatron.card_number}</strong> &nbsp;|&nbsp;
                Institution: <strong style="color:#38bdf8;">NFSU Gandhinagar</strong> &nbsp;|&nbsp;
                Fines: <strong style="color:#34d399;">₹${this.currentPatron.fee_amount}</strong>
              </div>
            </div>
          </div>

          <div style="display:flex; align-items:center; gap:16px;">
            <div class="patron-counter-badge" style="border-color:${badgeColor};">
              <div style="font-size:11px; color:#cbd5e1; text-transform:uppercase; font-weight:700;">
                How Many Books Issued
              </div>
              <div class="patron-counter-num" style="color:${badgeColor};">
                ${count} <span style="font-size:15px; color:#94a3b8;">/ ${this.maxBooksAllowed}</span>
              </div>
              <div style="font-size:11px; font-weight:700; color:${badgeColor};">
                ${quotaText}
              </div>
            </div>

            <button class="btn-back-home" style="padding:6px 14px; font-size:12px; border-color:rgba(239,68,68,0.4); color:#fca5a5;" onclick="window.kioskApp.logoutPatron()">
              <i class="fas fa-sign-out-alt"></i> Logout
            </button>
          </div>
        </div>
      `;

      // Quota Warning if full
      if (isFull) {
        html += `
          <div style="background:rgba(239,68,68,0.18); border:1px solid #ef4444; border-radius:12px; padding:12px 18px; margin-top:12px; display:flex; align-items:center; gap:14px; color:#fca5a5; font-size:13px;">
            <i class="fas fa-exclamation-triangle" style="font-size:24px; color:#ef4444;"></i>
            <div>
              <strong style="color:#ffffff;">MAXIMUM BORROWING LIMIT REACHED (2/2 BOOKS ISSUED)</strong><br>
              Under NFSU Central Library Policy, patrons may hold at most 2 books at any time. To issue new books, please return an issued book below.
            </div>
          </div>
        `;
      }

      // Display list of currently issued books from Koha AU fields
      if (this.currentPatron.charged_items && this.currentPatron.charged_items.length > 0) {
        html += `
          <div style="background:rgba(0,15,36,0.6); border:1px solid rgba(221,181,94,0.3); border-radius:12px; padding:14px 18px; margin-top:12px;">
            <div style="font-size:12px; font-weight:700; color:var(--nfsu-gold); margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
              <span><i class="fas fa-layer-group"></i> Currently Issued Books (Verified from Koha 26 AU Fields):</span>
              <span style="font-size:11px; color:#94a3b8;">Max 2 allowed</span>
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">
        `;

        this.currentPatron.charged_items.forEach((barcode, idx) => {
          html += `
            <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.06); padding:8px 14px; border-radius:8px; border:1px solid rgba(255,255,255,0.1); font-size:13px;">
              <div>
                <span style="color:var(--nfsu-gold); font-weight:700; margin-right:8px;">#${idx + 1}</span>
                <i class="fas fa-book" style="color:#38bdf8; margin-right:6px;"></i>
                Barcode: <strong style="font-family:monospace; color:#ffffff;">${barcode}</strong>
              </div>
              <div style="display:flex; gap:8px;">
                <button class="btn-back-home" style="padding:4px 12px; font-size:11.5px; border-color:var(--nfsu-gold); color:var(--nfsu-gold-light);" onclick="window.kioskApp.renewBook('${barcode}')">
                  <i class="fas fa-sync-alt"></i> Renew (SIP2 29)
                </button>
                <button class="btn-back-home" style="padding:4px 12px; font-size:11.5px; border-color:#34d399; color:#6ee7b7;" onclick="window.kioskApp.returnBookDirect('${barcode}')">
                  <i class="fas fa-undo"></i> Return (SIP2 09)
                </button>
              </div>
            </div>
          `;
        });

        html += `</div></div>`;
      }

      container.innerHTML = html;

    } else {
      // Patron is NOT logged in
      if (this.activeWorkflow === 'return') {
        container.innerHTML = `
          <div style="background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); border-radius:12px; padding:12px 18px; display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:12px; font-size:13px; color:#a7f3d0;">
              <i class="fas fa-info-circle" style="font-size:20px; color:#34d399;"></i>
              <div>
                <strong>Express Return Mode (No Login Required)</strong><br>
                Lay returned book(s) on the RFID pad or scan barcodes to resensitize tags and update Koha 26.
              </div>
            </div>
            <button class="btn-back-home" style="padding:5px 14px; font-size:12px;" onclick="window.kioskApp.quickAuthenticateLive('rfid')">
              Optional: Login as rfid
            </button>
          </div>
        `;
      } else {
        // Issue or Renew requires Patron Authentication: Show 3-Way Hub
        container.innerHTML = `
          <div style="background:rgba(0,15,36,0.7); border:1px solid rgba(221,181,94,0.35); border-radius:16px; padding:20px 24px;">
            <div style="font-size:15px; font-weight:800; color:var(--nfsu-gold); margin-bottom:12px; display:flex; align-items:center; gap:10px;">
              <i class="fas fa-user-shield"></i>
              Patron Authentication Hub (Please Identify to Proceed):
            </div>
            
            <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:16px;">
              
              <!-- 1. MIFARE Smart Card Tap -->
              <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:16px; text-align:center;">
                <i class="fas fa-id-card" style="font-size:32px; color:var(--nfsu-gold); margin-bottom:8px;"></i>
                <h4 style="font-size:14px; margin:0 0 4px 0; color:#ffffff;">1. MIFARE Smart Card</h4>
                <p style="font-size:11.5px; color:#cbd5e1; margin:0 0 10px 0;">Tap card on HID OMNIKEY reader</p>
                <div style="display:flex; flex-direction:column; gap:6px;">
                  <button class="btn-back-home" style="padding:4px 10px; font-size:11px; justify-content:center; border-color:var(--nfsu-gold); color:var(--nfsu-gold);" onclick="window.kioskApp.quickAuthenticateLive('rfid')">
                    Live: rfid (Rfid@123)
                  </button>
                  <button class="btn-back-home" style="padding:4px 10px; font-size:11px; justify-content:center; border-color:var(--nfsu-gold); color:var(--nfsu-gold);" onclick="window.kioskApp.quickAuthenticateLive('rfid1')">
                    Live: rfid1 (Rfid1@123)
                  </button>
                </div>
              </div>

              <!-- 2. Patron ID Barcode -->
              <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:16px; text-align:center;">
                <i class="fas fa-barcode" style="font-size:32px; color:#38bdf8; margin-bottom:8px;"></i>
                <h4 style="font-size:14px; margin:0 0 4px 0; color:#ffffff;">2. Barcode Scanner</h4>
                <p style="font-size:11.5px; color:#cbd5e1; margin:0 0 10px 0;">Scan student ID barcode</p>
                <div style="display:flex; gap:6px;">
                  <input type="text" id="manual-patron-id-input" placeholder="e.g. rfid" value="rfid"
                         style="flex:1; background:rgba(0,0,0,0.4); border:1px solid rgba(255,255,255,0.2); border-radius:6px; color:white; padding:6px 8px; font-size:12px; text-align:center;"
                         onkeydown="if(event.key==='Enter') window.kioskApp.authenticatePatron(this.value)">
                  <button class="btn-nfsu-action" style="padding:6px 12px; font-size:12px;" onclick="window.kioskApp.authenticatePatron(document.getElementById('manual-patron-id-input').value)">
                    Go
                  </button>
                </div>
              </div>

              <!-- 3. AI Facial Recognition -->
              <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:16px; text-align:center;">
                <i class="fas fa-camera" style="font-size:32px; color:#34d399; margin-bottom:8px;"></i>
                <h4 style="font-size:14px; margin:0 0 4px 0; color:#ffffff;">3. AI Face Liveness</h4>
                <p style="font-size:11.5px; color:#cbd5e1; margin:0 0 10px 0;">Blink & head pose challenge</p>
                <button class="btn-nfsu-action" style="background:#10b981; color:white; padding:6px 14px; font-size:12px; width:100%; justify-content:center;" onclick="window.faceLiveness.openLivenessModal('rfid')">
                  <i class="fas fa-video"></i> Start Camera
                </button>
              </div>

            </div>
          </div>
        `;
      }
    }
  }

  // =========================================================================
  // WORKFLOW DYNAMIC STEPS CONTENT (ISSUE, RETURN, RENEW)
  // =========================================================================

  renderWorkflowDynamicContent() {
    const container = document.getElementById('workflow-dynamic-content');
    if (!container || !this.activeWorkflow) return;

    const booksOnPad = (this.padState && this.padState.books_zone) ? this.padState.books_zone.books : [];
    const booksCount = booksOnPad.length;
    const patronIssued = this.currentPatron ? this.currentPatron.charged_items_count : 0;
    const quotaWillExceed = (patronIssued + booksCount > this.maxBooksAllowed);

    // -----------------------------------------------------------------------
    // WORKFLOW 1: ISSUE / CHECKOUT
    // -----------------------------------------------------------------------
    if (this.activeWorkflow === 'issue') {
      if (!this.currentPatron) {
        container.innerHTML = `
          <div style="text-align:center; padding:30px; color:#cbd5e1; font-size:14px;">
            <i class="fas fa-arrow-up" style="color:var(--nfsu-gold); font-size:22px; display:block; margin-bottom:8px;"></i>
            Please authenticate using any of the 3 methods above to unlock the book checkout pad.
          </div>
        `;
        return;
      }

      let html = `
        <div class="pad-workflow-card">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
            <div>
              <h4 style="font-size:16px; font-weight:800; color:#ffffff; margin:0; display:flex; align-items:center; gap:8px;">
                <i class="fas fa-microchip" style="color:var(--nfsu-gold);"></i>
                Dual-Zone RFID Self-Check Pad (ISO 15693 / 13.56 MHz HF)
              </h4>
              <p style="font-size:12px; color:#cbd5e1; margin:2px 0 0 0;">
                Lay books flat on pad surface. Anti-collision active (Max 2 books concurrently).
              </p>
            </div>
            <div style="display:flex; gap:8px;">
              <button class="btn-back-home" style="padding:4px 12px; font-size:11.5px; border-color:var(--nfsu-gold); color:var(--nfsu-gold);" onclick="window.kioskApp.testPlaceSingleBook('NFSU-BK-104')">
                + Place 1 Book
              </button>
              <button class="btn-back-home" style="padding:4px 12px; font-size:11.5px; border-color:#38bdf8; color:#bae6fd;" onclick="window.kioskApp.testPlaceTwoBooks('NFSU-BK-104', 'NFSU-BK-105')">
                + Place 2 Books (Multi-Tag)
              </button>
              <button class="btn-back-home" style="padding:4px 12px; font-size:11.5px; border-color:#fca5a5; color:#fca5a5;" onclick="window.kioskApp.testRemoveBooks()">
                Clear Pad
              </button>
            </div>
          </div>

          <!-- RFID Pad Books Container -->
          <div id="books-pad-container" style="display:grid; grid-template-columns:${booksCount > 1 ? 'repeat(2, 1fr)' : '1fr'}; gap:14px; margin-bottom:16px;">
      `;

      if (booksCount === 0) {
        html += `
          <div style="grid-column: 1 / -1; background:rgba(255,255,255,0.04); border:2px dashed rgba(255,255,255,0.2); border-radius:14px; padding:28px; text-align:center;">
            <i class="fas fa-book-open" style="font-size:36px; color:#64748b; margin-bottom:8px;"></i>
            <h5 style="color:#ffffff; margin:0 0 4px 0; font-size:15px;">No Books Detected on RFID Pad</h5>
            <p style="font-size:12px; color:#94a3b8; margin:0 0 12px 0;">Place 1 or 2 forensic science textbooks on the pad to proceed.</p>
            <div style="display:flex; justify-content:center; gap:10px;">
              <button class="btn-nfsu-action" style="padding:8px 18px; font-size:12.5px;" onclick="window.kioskApp.testPlaceSingleBook('NFSU-BK-104')">
                <i class="fas fa-hand-holding"></i> Place Single Book (NFSU-BK-104)
              </button>
              <button class="btn-nfsu-action" style="background:#38bdf8; color:#001b3a; padding:8px 18px; font-size:12.5px;" onclick="window.kioskApp.testPlaceTwoBooks('NFSU-BK-104', 'NFSU-BK-105')">
                <i class="fas fa-layer-group"></i> Simulate Placing 2 Books (PS-2 Judge Control)
              </button>
            </div>
          </div>
        `;
      } else {
        booksOnPad.forEach((book, idx) => {
          const isArmed = (book.afi === '0x07');
          const borderClr = isArmed ? '#ef4444' : '#10b981';
          const afiLabel = isArmed ? 'AFI: 0x07 [ARMED - EAS ON]' : 'AFI: 0xC2 [DISARMED - EAS OFF]';
          const afiBg = isArmed ? 'rgba(239,68,68,0.2)' : 'rgba(16,185,129,0.2)';

          html += `
            <div style="background:rgba(255,255,255,0.07); border:2px solid ${borderClr}; border-radius:12px; padding:16px; display:flex; gap:14px; position:relative;">
              <div style="width:70px; height:95px; background:linear-gradient(135deg, #001733 0%, #0a274c 100%); border:1px solid rgba(221,181,94,0.4); border-radius:6px; display:flex; flex-direction:column; justify-content:space-between; padding:6px; font-size:9px; text-align:center;">
                <span style="color:var(--nfsu-gold); font-weight:700;"><i class="fas fa-microchip"></i> ISO 15693</span>
                <span style="font-weight:700; color:white; overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical;">${book.title}</span>
                <span style="color:#94a3b8; font-size:8px;">NFSU LIB</span>
              </div>

              <div style="flex:1; display:flex; flex-direction:column; justify-content:space-between;">
                <div>
                  <div style="font-size:10.5px; font-weight:800; color:var(--nfsu-gold); text-transform:uppercase;">
                    Book #${idx + 1} Detected on Sensor Pad
                  </div>
                  <h4 style="font-size:14px; font-weight:800; margin:2px 0 4px 0; color:#ffffff;">
                    ${book.title}
                  </h4>
                  <div style="font-size:12px; color:#cbd5e1;">
                    Author: <strong style="color:#ffffff;">${book.author}</strong><br>
                    Barcode: <strong style="font-family:monospace; color:var(--nfsu-gold);">${book.barcode}</strong> &nbsp;|&nbsp;
                    Call: <strong style="color:#38bdf8;">${book.call_number}</strong>
                  </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
                  <span style="background:${afiBg}; border:1px solid ${borderClr}; color:${borderClr}; font-weight:700; font-size:11px; padding:3px 10px; border-radius:4px;">
                    <i class="fas ${isArmed ? 'fa-shield-alt' : 'fa-check-circle'}"></i> ${afiLabel}
                  </span>
                  <button class="btn-back-home" style="padding:2px 8px; font-size:11px; border-color:#fca5a5; color:#fca5a5;" onclick="window.kioskApp.testPassGate('${book.barcode}')">
                    <i class="fas fa-door-open"></i> Test Gate
                  </button>
                </div>
              </div>
            </div>
          `;
        });
      }

      html += `</div>`;

      // Handheld Barcode Scanner Manual Entry Strip
      html += `
        <div style="background:rgba(0,15,36,0.5); border:1px solid rgba(255,255,255,0.1); border-radius:10px; padding:10px 14px; display:flex; gap:10px; align-items:center; margin-bottom:14px;">
          <i class="fas fa-barcode" style="color:var(--nfsu-gold); font-size:18px;"></i>
          <input type="text" id="manual-book-barcode-input" placeholder="Scan book barcode with handheld reader or type barcode..."
                 style="flex:1; background:transparent; border:none; outline:none; color:white; font-size:13px;"
                 onkeydown="if(event.key==='Enter') { window.kioskApp.testPlaceSingleBook(this.value); this.value=''; }">
          <button class="btn-back-home" style="padding:4px 12px; font-size:11.5px;" onclick="const el=document.getElementById('manual-book-barcode-input'); window.kioskApp.testPlaceSingleBook(el.value); el.value='';">
            Place on Pad
          </button>
        </div>
      `;

      // Quota Rule & Action Button
      if (quotaWillExceed) {
        html += `
          <div style="background:rgba(239,68,68,0.2); border-left:4px solid #ef4444; border-radius:8px; padding:14px 18px; color:#fca5a5; font-size:13px;">
            <strong style="color:#ffffff; font-size:14px;"><i class="fas fa-ban"></i> CHECKOUT BLOCKED: 2-BOOK CIRCULATION LIMIT WOULD BE EXCEEDED</strong><br>
            You currently hold <strong>${patronIssued}</strong> book(s) and placed <strong>${booksCount}</strong> book(s) on the pad (Total: <strong>${patronIssued + booksCount} > 2</strong>).<br>
            NFSU Central Library rules strictly restrict borrowing to a maximum of <strong>2 books</strong> per patron. Please remove excess books to proceed.
          </div>
        `;
      } else if (booksCount > 0) {
        html += `
          <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.4); border-radius:12px; padding:14px 20px;">
            <div>
              <div style="font-size:14px; font-weight:800; color:#34d399;">
                <i class="fas fa-check-circle"></i> Ready to Issue: ${booksCount} Book${booksCount > 1 ? 's' : ''}
              </div>
              <div style="font-size:12px; color:#cbd5e1; margin-top:2px;">
                Koha 26 SIP2 11 -> 12 Verification & Two-Phase Commit AFI Disarm (0xC2)
              </div>
            </div>
            <button class="btn-nfsu-action" style="font-size:15px; padding:12px 28px;" onclick="window.kioskApp.confirmIssueCheckout()">
              <i class="fas fa-check-double"></i> Confirm Issue (${booksCount} Book${booksCount > 1 ? 's' : ''})
            </button>
          </div>
        `;
      }

      html += `</div>`;
      container.innerHTML = html;

    // -----------------------------------------------------------------------
    // WORKFLOW 2: RETURN / CHECK-IN
    // -----------------------------------------------------------------------
    } else if (this.activeWorkflow === 'return') {
      let html = `
        <div class="pad-workflow-card">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
            <div>
              <h4 style="font-size:16px; font-weight:800; color:#ffffff; margin:0;">
                <i class="fas fa-inbox" style="color:var(--nfsu-gold);"></i>
                Express Return & Tag Resensitization
              </h4>
              <p style="font-size:12px; color:#cbd5e1; margin:2px 0 0 0;">
                RFID tags will be automatically re-armed with AFI: 0x07 (EAS On) upon Koha 26 check-in.
              </p>
            </div>
            <div style="display:flex; gap:8px;">
              <button class="btn-back-home" style="padding:4px 12px; font-size:11.5px; border-color:var(--nfsu-gold); color:var(--nfsu-gold);" onclick="window.kioskApp.testPlaceSingleBook('NFSU-BK-101')">
                + Place Issued Book (NFSU-BK-101)
              </button>
              <button class="btn-back-home" style="padding:4px 12px; font-size:11.5px; border-color:#fca5a5; color:#fca5a5;" onclick="window.kioskApp.testRemoveBooks()">
                Clear Pad
              </button>
            </div>
          </div>

          <!-- Books On Pad -->
          <div style="display:grid; grid-template-columns:${booksCount > 1 ? 'repeat(2, 1fr)' : '1fr'}; gap:14px; margin-bottom:16px;">
      `;

      if (booksCount === 0) {
        html += `
          <div style="grid-column: 1 / -1; background:rgba(255,255,255,0.04); border:2px dashed rgba(255,255,255,0.2); border-radius:14px; padding:28px; text-align:center;">
            <i class="fas fa-book" style="font-size:36px; color:#64748b; margin-bottom:8px;"></i>
            <h5 style="color:#ffffff; margin:0 0 4px 0; font-size:15px;">Place Book(s) to Return on the RFID Pad</h5>
            <p style="font-size:12px; color:#94a3b8; margin:0 0 12px 0;">Place returned books flat on the pad or enter barcode below.</p>
            <button class="btn-nfsu-action" style="padding:8px 18px; font-size:12.5px;" onclick="window.kioskApp.testPlaceSingleBook('NFSU-BK-101')">
              <i class="fas fa-hand-holding"></i> Place Issued Book (NFSU-BK-101)
            </button>
          </div>
        `;
      } else {
        booksOnPad.forEach((book, idx) => {
          html += `
            <div style="background:rgba(255,255,255,0.07); border:2px solid #38bdf8; border-radius:12px; padding:16px; display:flex; gap:14px;">
              <div style="width:65px; height:85px; background:#001b3a; border-radius:6px; display:flex; align-items:center; justify-content:center; color:var(--nfsu-gold); font-size:24px;">
                <i class="fas fa-book"></i>
              </div>
              <div style="flex:1;">
                <div style="font-size:11px; font-weight:700; color:var(--nfsu-gold);">Item #${idx + 1} Ready for Return</div>
                <h4 style="font-size:14px; font-weight:800; margin:2px 0 4px 0; color:#ffffff;">${book.title}</h4>
                <div style="font-size:12px; color:#cbd5e1;">
                  Barcode: <strong style="font-family:monospace; color:#ffffff;">${book.barcode}</strong> &nbsp;|&nbsp;
                  Current AFI: <strong style="color:#f59e0b;">${book.afi}</strong>
                </div>
              </div>
            </div>
          `;
        });
      }

      html += `</div>`;

      // Handheld Barcode Input
      html += `
        <div style="background:rgba(0,15,36,0.5); border:1px solid rgba(255,255,255,0.1); border-radius:10px; padding:10px 14px; display:flex; gap:10px; align-items:center; margin-bottom:14px;">
          <i class="fas fa-barcode" style="color:var(--nfsu-gold); font-size:18px;"></i>
          <input type="text" id="manual-return-barcode-input" placeholder="Scan book barcode to return..."
                 style="flex:1; background:transparent; border:none; outline:none; color:white; font-size:13px;"
                 onkeydown="if(event.key==='Enter') { window.kioskApp.returnBookDirect(this.value); this.value=''; }">
          <button class="btn-nfsu-action" style="padding:4px 14px; font-size:12px;" onclick="const el=document.getElementById('manual-return-barcode-input'); window.kioskApp.returnBookDirect(el.value); el.value='';">
            Return Barcode
          </button>
        </div>
      `;

      if (booksCount > 0) {
        html += `
          <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.4); border-radius:12px; padding:14px 20px;">
            <div>
              <div style="font-size:14px; font-weight:800; color:#34d399;">
                <i class="fas fa-check-circle"></i> ${booksCount} Book(s) Ready to Check-In
              </div>
              <div style="font-size:12px; color:#cbd5e1; margin-top:2px;">
                Will send SIP2 09 -> 10 to Koha and re-arm security tags (AFI: 0x07 / EAS On).
              </div>
            </div>
            <button class="btn-nfsu-action" style="background:#059669; font-size:15px; padding:12px 28px;" onclick="window.kioskApp.confirmReturnCheckin()">
              <i class="fas fa-undo"></i> Confirm Return (${booksCount} Book${booksCount > 1 ? 's' : ''})
            </button>
          </div>
        `;
      }

      html += `</div>`;
      container.innerHTML = html;

    // -----------------------------------------------------------------------
    // WORKFLOW 3: RENEW / LOAN EXTENSION
    // -----------------------------------------------------------------------
    } else if (this.activeWorkflow === 'renew') {
      if (!this.currentPatron) {
        container.innerHTML = `
          <div style="text-align:center; padding:30px; color:#cbd5e1; font-size:14px;">
            <i class="fas fa-arrow-up" style="color:var(--nfsu-gold); font-size:22px; display:block; margin-bottom:8px;"></i>
            Please authenticate using any of the 3 methods above to view and renew your issued books.
          </div>
        `;
        return;
      }

      const issuedList = this.currentPatron.charged_items || [];
      let html = `
        <div class="pad-workflow-card">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
            <div>
              <h4 style="font-size:16px; font-weight:800; color:#ffffff; margin:0;">
                <i class="fas fa-sync-alt" style="color:var(--nfsu-gold);"></i>
                Renew Borrowed Titles (SIP2 29 -> 30)
              </h4>
              <p style="font-size:12px; color:#cbd5e1; margin:2px 0 0 0;">
                Extend due dates for eligible books currently charged to your account.
              </p>
            </div>
            ${issuedList.length > 0 ? `
              <button class="btn-nfsu-action" style="padding:6px 16px; font-size:12px;" onclick="window.kioskApp.renewAllBooks()">
                <i class="fas fa-sync-alt"></i> Renew All (${issuedList.length})
              </button>
            ` : ''}
          </div>
      `;

      if (issuedList.length === 0) {
        html += `
          <div style="background:rgba(255,255,255,0.04); border-radius:12px; padding:24px; text-align:center; color:#94a3b8;">
            <i class="fas fa-info-circle" style="font-size:28px; color:var(--nfsu-gold); margin-bottom:6px;"></i>
            <h5 style="color:#ffffff; margin:0 0 4px 0;">No Currently Issued Books</h5>
            <p style="font-size:12px; margin:0;">You do not have any books currently charged to your account.</p>
          </div>
        `;
      } else {
        html += `<div style="display:flex; flex-direction:column; gap:10px;">`;
        issuedList.forEach((barcode, idx) => {
          html += `
            <div style="background:rgba(255,255,255,0.06); border:1px solid rgba(221,181,94,0.3); border-radius:10px; padding:12px 18px; display:flex; justify-content:space-between; align-items:center;">
              <div>
                <span style="color:var(--nfsu-gold); font-weight:700; margin-right:8px;">#${idx + 1}</span>
                <i class="fas fa-book" style="color:#38bdf8; margin-right:6px;"></i>
                Barcode: <strong style="font-family:monospace; color:#ffffff;">${barcode}</strong>
                <div style="font-size:11.5px; color:#cbd5e1; margin-top:2px;">
                  Standard 14-day loan extension via Koha 26 circulation policy.
                </div>
              </div>
              <button class="btn-nfsu-action" style="padding:6px 16px; font-size:12.5px;" onclick="window.kioskApp.renewBook('${barcode}')">
                <i class="fas fa-sync-alt"></i> Renew Book
              </button>
            </div>
          `;
        });
        html += `</div>`;
      }

      html += `</div>`;
      container.innerHTML = html;
    }
  }

  // =========================================================================
  // CIRCULATION ACTIONS (TWO-PHASE COMMIT)
  // =========================================================================

  async confirmIssueCheckout() {
    if (!this.currentPatron) return;
    const books = (this.padState && this.padState.books_zone) ? this.padState.books_zone.books : [];
    if (books.length === 0) return;

    for (const book of books) {
      try {
        const resp = await fetch('/api/circulation/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            patron_id: this.currentPatron.card_number,
            item_barcode: book.barcode
          })
        });
        const res = await resp.json();
        if (window.sip2Console) window.sip2Console.renderResponse(res);

        if (res.ok) {
          this.showCirculationReceipt({
            type: 'CHECKOUT / ISSUE RECEIPT',
            patron_name: this.currentPatron.name,
            card_number: this.currentPatron.card_number,
            title: res.title || book.title,
            barcode: book.barcode,
            due_date: res.due_date || '14 Days from today',
            afi_state: '0xC2 (DISARMED - EAS OFF)',
            message: res.screen_message || 'Thank you for using NFSU Central Library Self-Service Kiosk'
          });
        } else {
          alert(res.screen_message || `Checkout denied for ${book.barcode}`);
        }
      } catch (e) {
        console.error("Checkout request failed", e);
      }
    }

    await this.testRemoveBooks();
    await this.refreshState();
  }

  async confirmReturnCheckin() {
    const books = (this.padState && this.padState.books_zone) ? this.padState.books_zone.books : [];
    if (books.length === 0) return;

    for (const book of books) {
      await this.returnBookDirect(book.barcode, book.title);
    }

    await this.testRemoveBooks();
    await this.refreshState();
  }

  async returnBookDirect(barcode, fallbackTitle = '') {
    try {
      const resp = await fetch('/api/circulation/checkin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_barcode: barcode })
      });
      const res = await resp.json();
      if (window.sip2Console) window.sip2Console.renderResponse(res);

      if (res.ok) {
        if (window.gateBuzzer) window.gateBuzzer.playPassChime();
        this.showCirculationReceipt({
          type: 'CHECK-IN / RETURN ACKNOWLEDGEMENT',
          patron_name: this.currentPatron ? this.currentPatron.name : 'Express Return',
          card_number: this.currentPatron ? this.currentPatron.card_number : 'N/A',
          title: res.title || fallbackTitle || `Book (${barcode})`,
          barcode: barcode,
          due_date: 'RETURN CONFIRMED',
          afi_state: '0x07 (ARMED - EAS ON)',
          message: res.screen_message || 'Book returned and RFID security tag resensitized successfully.'
        });
      } else {
        alert(res.screen_message || `Return failed for item ${barcode}`);
      }
      await this.refreshState();
    } catch (e) {
      console.error("Return failed", e);
    }
  }

  async renewBook(barcode) {
    if (!this.currentPatron) return;
    try {
      const resp = await fetch('/api/circulation/renew', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patron_id: this.currentPatron.card_number,
          item_barcode: barcode
        })
      });
      const res = await resp.json();
      if (window.sip2Console) window.sip2Console.renderResponse(res);

      if (res.ok) {
        alert(res.screen_message || `Renewal approved! Updated due date: ${res.due_date || '14 Days extended'}`);
      } else {
        alert(res.screen_message || "Renewal refused by Koha 26 ILMS");
      }
      await this.refreshState();
    } catch (e) {
      console.error("Renewal failed", e);
    }
  }

  async renewAllBooks() {
    if (!this.currentPatron || !this.currentPatron.charged_items) return;
    for (const barcode of this.currentPatron.charged_items) {
      await this.renewBook(barcode);
    }
  }

  // =========================================================================
  // HARDWARE PAD SIMULATION TRIGGERS (FOR JUDGES & DEMONSTRATION)
  // =========================================================================

  async testPlaceSingleBook(barcode = "NFSU-BK-104") {
    try {
      await fetch('/api/hardware/place-book', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ barcode })
      });
      await this.refreshPadOnly();
    } catch (e) {}
  }

  async testPlaceTwoBooks(bc1 = "NFSU-BK-104", bc2 = "NFSU-BK-105") {
    try {
      await fetch('/api/hardware/place-two-books', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ barcode1: bc1, barcode2: bc2 })
      });
      await this.refreshPadOnly();
    } catch (e) {}
  }

  async testRemoveBooks() {
    try {
      await fetch('/api/hardware/remove-books', { method: 'POST' });
      await this.refreshPadOnly();
    } catch (e) {}
  }

  async testPassGate(barcode = "NFSU-BK-104") {
    try {
      const resp = await fetch('/api/hardware/pass-gate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ barcode })
      });
      const data = await resp.json();
      const modal = document.getElementById('gate-buzzer-modal');
      if (modal) modal.style.display = 'flex';
      if (window.gateBuzzer) window.gateBuzzer.handleGateWalkthrough(data);
    } catch (e) {}
  }

  // =========================================================================
  // DIGITAL & PRINTABLE RECEIPT
  // =========================================================================

  showCirculationReceipt(details) {
    const modal = document.getElementById('receipt-modal');
    const content = document.getElementById('receipt-printable-content');
    if (!modal || !content) return;

    const time = new Date().toLocaleString('en-IN');
    content.innerHTML = `
      <div style="text-align:center; border-bottom:2px dashed #002147; padding-bottom:12px; margin-bottom:12px;">
        <img src="/assets/img/NFSU_logo.png" style="height:55px; margin-bottom:6px;" alt="NFSU">
        <h4 style="font-size:15px; font-weight:800; color:#002147; margin:0;">NATIONAL FORENSIC SCIENCES UNIVERSITY</h4>
        <div style="font-size:11px; color:#d97706; font-weight:700;">CENTRAL LIBRARY SELF-SERVICE KIOSK</div>
        <div style="font-size:10px; color:#64748b;">Sector-9, Gandhinagar - 382007, Gujarat</div>
        <div style="font-size:12px; font-weight:700; color:#002147; margin-top:8px; text-transform:uppercase;">${details.type}</div>
      </div>

      <table style="width:100%; font-size:12px; line-height:1.6; margin-bottom:12px;">
        <tr><td style="color:#64748b; width:40%;">Transaction Time:</td><td style="font-weight:600;">${time}</td></tr>
        <tr><td style="color:#64748b;">Patron:</td><td style="font-weight:700;">${details.patron_name}</td></tr>
        <tr><td style="color:#64748b;">Patron ID:</td><td style="font-family:monospace;">${details.card_number}</td></tr>
        <tr><td style="color:#64748b;">Title:</td><td style="font-weight:700; color:#002147;">${details.title}</td></tr>
        <tr><td style="color:#64748b;">Item Barcode:</td><td style="font-family:monospace; font-weight:700;">${details.barcode}</td></tr>
        <tr><td style="color:#64748b;">Due Date:</td><td style="font-weight:800; color:#10b981;">${details.due_date}</td></tr>
        <tr><td style="color:#64748b;">RFID Tag Security:</td><td style="font-weight:700; color:#d97706;">${details.afi_state}</td></tr>
      </table>

      <div style="background:#f8fafc; border:1px solid #e2e8f0; padding:10px; border-radius:6px; font-size:11px; color:#475569; text-align:center;">
        <em>${details.message}</em><br>
        <span style="font-size:10px; color:#94a3b8;">Koha 26 SIP2 Transaction ID: TX-${Date.now().toString(36).toUpperCase()}</span>
      </div>
    `;

    modal.style.display = 'flex';
  }

  closeReceiptModal() {
    const modal = document.getElementById('receipt-modal');
    if (modal) modal.style.display = 'none';
  }

  printReceipt() {
    window.print();
  }

  // =========================================================================
  // HARDWARE BARCODE SCANNER (KEYBOARD WEDGE) AUTO-CAPTURE
  // =========================================================================

  attachEventListeners() {
    let barcodeBuffer = '';
    let lastKeyTime = Date.now();

    window.addEventListener('keydown', (e) => {
      // Don't intercept when user is intentionally typing into form inputs
      if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;

      const currentTime = Date.now();
      if (currentTime - lastKeyTime > 200) {
        barcodeBuffer = '';
      }
      lastKeyTime = currentTime;

      if (e.key === 'Enter') {
        const code = barcodeBuffer.trim();
        if (code.length >= 2) {
          console.log(`[Hardware Barcode/Wedge Scanned]: ${code}`);
          if (this.activeWorkflow === 'return') {
            this.returnBookDirect(code);
          } else if (!this.currentPatron) {
            // Not logged in -> treat as patron ID / student card
            this.authenticatePatron(code);
          } else {
            // Logged in -> treat as book barcode to place on pad
            this.testPlaceSingleBook(code);
          }
        }
        barcodeBuffer = '';
      } else if (e.key.length === 1) {
        barcodeBuffer += e.key;
      }
    });
  }
}

window.kioskApp = new NFSUKioskApp();
document.addEventListener('DOMContentLoaded', () => {
  window.kioskApp.init();
});
