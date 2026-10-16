/**
 * NFSU Central Library Self-Service Kiosk - Main Application Controller
 * National Forensic Sciences University, Gandhinagar
 * Integrated with Koha 26 ILMS (PS-2)
 *
 * Real-hardware controller:
 * - Live Koha 26 SIP2 circulation (issue / return / renew)
 * - RFID book pad + patron card reader driven by the backend PC/SC bridge
 * - HID / serial barcode scanner capture (keyboard-wedge)
 * - Two-phase-commit AFI security byte updates (0x07 armed / 0xC2 disarmed)
 * - Strict 2-books-at-a-time policy with a live issued-books counter
 */

class NFSUKioskApp {
  constructor() {
    this.ws = null;
    this.currentPatron = null;
    this.padState = { books_zone: { books: [] }, card_zone: {}, gate_zone: null };
    this.telemetry = null;
    this.hardware = null;
    this.activeWorkflow = null; // 'issue' | 'return' | 'renew' | null
    this.maxBooksAllowed = 2;
    this._isAuthenticating = false;
  }

  // =====================================================================
  // Lifecycle
  // =====================================================================
  async init() {
    this.initClock();
    await this.loadConfig();
    this.connectWebSocket();
    this.attachBarcodeScanner();
    await this.refreshState();
    this.returnHome();
  }

  async loadConfig() {
    try {
      const resp = await fetch('/api/health');
      const data = await resp.json();
      if (data && data.max_books_allowed) this.maxBooksAllowed = data.max_books_allowed;
      if (data && data.koha) this.updateTelemetryUI(data.koha);
      if (data && data.hardware) this.updateHardwareUI(data.hardware);
    } catch (e) {
      console.warn('Could not load kiosk configuration', e);
    }
  }

  initClock() {
    const update = () => {
      const el = document.getElementById('workflow-clock');
      if (el) el.textContent = new Date().toLocaleTimeString('en-IN', { hour12: false });
    };
    update();
    setInterval(update, 1000);
  }

  // =====================================================================
  // WebSocket
  // =====================================================================
  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    this.ws.onopen = () => this.setBeacon(true);
    this.ws.onclose = () => {
      this.setBeacon(false);
      setTimeout(() => this.connectWebSocket(), 3000);
    };
    this.ws.onerror = () => this.setBeacon(false);
    this.ws.onmessage = (event) => {
      try {
        this.handleWebSocketMessage(JSON.parse(event.data));
      } catch (e) {
        console.error('WS parse error', e);
      }
    };
  }

  setBeacon(connected) {
    const beacon = document.getElementById('koha-beacon');
    if (beacon) beacon.classList.toggle('error', !connected);
  }

  handleWebSocketMessage(msg) {
    switch (msg.type) {
      case 'INIT_STATE':
        if (msg.telemetry) this.updateTelemetryUI(msg.telemetry);
        if (msg.hardware) this.updateHardwareUI(msg.hardware);
        this.applyPadState(msg.pad_state);
        break;
      case 'PAD_BOOKS_UPDATED':
        this.applyPadState(msg.data);
        this.renderWorkflowDynamicContent();
        break;
      case 'PATRON_CARD_TAPPED':
        this.applyPadState(msg.data);
        this.syncPatronFromPad();
        break;
      case 'PATRON_CARD_REMOVED':
        this.applyPadState(msg.data);
        if (this.currentPatron) this.logoutPatron(false);
        break;
      case 'AFI_STATE_CHANGED':
        if (window.sip2Console) {
          window.sip2Console.logTerminal(`[RFID] ${msg.data.barcode || msg.data.tag_uid}: AFI → ${msg.data.new_afi} (${msg.data.state})`, 'info');
        }
        this.renderWorkflowDynamicContent();
        break;
      case 'GATE_WALKTHROUGH':
        if (window.gateBuzzer) window.gateBuzzer.handleGateWalkthrough(msg.data);
        break;
      case 'UNKNOWN_CARD':
        this.showToast(`Unregistered card ${msg.data.card_uid}. Add it to hardware_map.json.`, 'error');
        break;
      case 'PATRON_AUTH_FAILED':
        if (!this.currentPatron) this.showToast(msg.data.reason || 'Patron authentication failed', 'error');
        break;
      case 'SCAN_REJECTED':
        this.showToast(msg.data.reason || 'Item not found in Koha', 'error');
        break;
      case 'HARDWARE_STATUS':
        this.updateHardwareUI(msg.data);
        break;
      case 'SIP2_TELEMETRY':
        this.updateTelemetryUI(msg.data);
        break;
      case 'CIRCULATION_TRANSACTION':
        break;
    }
  }

  applyPadState(padState) {
    if (!padState) return;
    this.padState = padState;
    if (padState.hardware) this.updateHardwareUI(padState.hardware);
    this.renderWorkflowDynamicContent();
  }

  syncPatronFromPad() {
    const patron = this.padState?.card_zone?.patron;
    if (patron && (!this.currentPatron || this.currentPatron.card_number !== patron.card_number)) {
      this.loadPatron(patron.card_number);
    }
  }

  // =====================================================================
  // Telemetry / hardware status
  // =====================================================================
  updateTelemetryUI(telemetry) {
    if (!telemetry) return;
    this.telemetry = telemetry;

    const lat = document.getElementById('koha-latency-val');
    if (lat) lat.textContent = `${telemetry.latency_ms != null ? telemetry.latency_ms : '--'} ms`;

    const text = document.getElementById('koha-conn-text');
    const beacon = document.getElementById('koha-beacon');
    if (text) {
      if (telemetry.is_logged_in) text.textContent = 'KOHA 26 LIVE';
      else if (telemetry.is_connected) text.textContent = 'KOHA 26 (no login)';
      else if (!telemetry.configured) text.textContent = 'KOHA NOT CONFIGURED';
      else text.textContent = 'KOHA OFFLINE';
    }
    if (beacon) {
      const healthy = telemetry.is_logged_in;
      beacon.classList.toggle('error', !healthy);
    }

    const host = document.getElementById('footer-koha-host');
    if (host) host.textContent = `${telemetry.host}:${telemetry.port}`;
    const account = document.getElementById('footer-account');
    if (account) account.textContent = telemetry.account || '--';
    const inst = document.getElementById('footer-inst');
    if (inst) inst.textContent = telemetry.institution_id || '--';

    const cfgHost = document.getElementById('sip-config-host');
    const cfgPort = document.getElementById('sip-config-port');
    const cfgStatus = document.getElementById('sip-config-status');
    if (cfgHost && !cfgHost.value) cfgHost.value = telemetry.host || '';
    if (cfgPort && !cfgPort.value) cfgPort.value = telemetry.port || '';
    if (cfgStatus) {
      cfgStatus.textContent = telemetry.is_logged_in
        ? `Connected to ${telemetry.host}:${telemetry.port} as ${telemetry.account}`
        : (telemetry.last_error || 'Not connected.');
    }
  }

  updateHardwareUI(hw) {
    if (!hw) return;
    this.hardware = hw;

    const readers = hw.readers || {};
    const ok = (r) => r && r.name;
    const missing = [];
    if (!hw.pyscard_available) missing.push('pyscard');
    if (!ok(readers.card)) missing.push('card reader');
    if (!ok(readers.book)) missing.push('book pad');
    if (!ok(readers.gate)) missing.push('gate antenna');

    const text = document.getElementById('hardware-status-text');
    const chip = document.getElementById('hardware-status-chip');
    if (text && chip) {
      if (missing.length === 0) {
        text.textContent = 'Hardware ready';
        chip.classList.remove('warn');
      } else {
        text.textContent = `Hardware: ${missing.join(', ')} unavailable`;
        chip.classList.add('warn');
      }
    }

    const body = document.getElementById('hardware-panel-body');
    if (body) {
      if (!hw.pyscard_available) {
        body.innerHTML = `<div class="hw-row error"><i class="fas fa-exclamation-triangle"></i>
          PC/SC support unavailable. Install <code>pyscard</code> (<code>pip install pyscard</code>) and connect the readers.</div>`;
        return;
      }
      const rows = [
        ['card', 'fas fa-id-card', 'Patron MIFARE card reader'],
        ['book', 'fas fa-book-open', 'ISO 15693 book pad'],
        ['gate', 'fas fa-door-open', 'Exit gate antenna'],
      ];
      body.innerHTML = rows.map(([role, icon, label]) => {
        const name = readers[role] && readers[role].name;
        return `<div class="hw-row ${name ? 'ok' : 'error'}">
          <i class="${icon}"></i>
          <span class="hw-label">${label}</span>
          <span class="hw-name">${name ? this.esc(name) : 'not detected'}</span>
          <i class="fas ${name ? 'fa-check-circle' : 'fa-times-circle'}"></i>
        </div>`;
      }).join('') + `<div class="hw-note">Tag map: ${hw.map_entries?.patron_cards ?? 0} cards, ${hw.map_entries?.book_tags ?? 0} book tags — ${this.esc(hw.map_file || '')}</div>`;
    }
  }

  // =====================================================================
  // View navigation
  // =====================================================================
  selectWorkflow(type) {
    this.activeWorkflow = type;
    const homeView = document.getElementById('kiosk-home-view');
    const workflowView = document.getElementById('kiosk-workflow-view');
    if (homeView) homeView.style.display = 'none';
    if (workflowView) workflowView.style.display = 'flex';

    const titles = {
      issue: '<i class="fas fa-book-open"></i> Book Issue / Checkout',
      return: '<i class="fas fa-inbox"></i> Express Return / Check-In',
      renew: '<i class="fas fa-sync-alt"></i> Book Renewal / Extension',
    };
    const title = document.getElementById('workflow-banner-title');
    if (title) title.innerHTML = titles[type] || '';

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

  // =====================================================================
  // Patron authentication (SIP2 63 → 64)
  // =====================================================================
  async authenticatePatron(patronId) {
    if (!patronId || !patronId.trim()) return;
    if (this._isAuthenticating) return;
    this._isAuthenticating = true;
    try {
      const resp = await fetch('/api/circulation/patron-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patron_id: patronId.trim() }),
      });
      const data = await resp.json();
      if (window.sip2Console) window.sip2Console.renderResponse(data);

      if (data.command === '64' && data.valid_patron !== false) {
        this.setPatron(data, patronId.trim());
        if (!this.activeWorkflow) this.selectWorkflow('issue');
        else this.renderWorkflowViews();
      } else {
        this.showToast(data.screen_message || data.error || 'Patron not found in Koha', 'error');
      }
    } catch (e) {
      this.showToast('Could not reach the kiosk backend', 'error');
    } finally {
      this._isAuthenticating = false;
    }
  }

  async loadPatron(patronId) {
    try {
      const resp = await fetch('/api/circulation/patron-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patron_id: patronId }),
      });
      const data = await resp.json();
      if (data.command === '64' && data.valid_patron !== false) {
        this.setPatron(data, patronId);
        this.renderWorkflowViews();
      }
    } catch (e) { /* ignore */ }
  }

  setPatron(data, fallbackId) {
    const padPatron = this.padState?.card_zone?.patron || {};
    this.currentPatron = {
      card_number: data.patron_id || fallbackId,
      name: (data.patron_name || '').trim() || padPatron.name || fallbackId,
      charged_items_count: data.charged_items_count ?? (data.charged_items || []).length ?? 0,
      charged_items: data.charged_items || [],
      fee_amount: data.fee_amount || '0.00',
      mifare_uid: padPatron.mifare_uid || null,
      screen_message: data.screen_message || '',
    };
  }

  logoutPatron(syncHardware = true) {
    this.currentPatron = null;
    if (syncHardware && this.padState?.card_zone?.card_present) {
      // The card reader is hardware driven; only clear the UI session here.
    }
    this.renderWorkflowViews();
  }

  // =====================================================================
  // Patron banner + authentication hub
  // =====================================================================
  renderPatronBanner() {
    const container = document.getElementById('workflow-patron-banner');
    if (!container) return;

    if (this.currentPatron) {
      const count = this.currentPatron.charged_items_count;
      const isFull = count >= this.maxBooksAllowed;
      const remaining = Math.max(0, this.maxBooksAllowed - count);
      const color = isFull ? '#ef4444' : (count === 1 ? '#f59e0b' : '#10b981');
      const quotaText = isFull ? 'QUOTA FULL' : `${remaining} of ${this.maxBooksAllowed} slots free`;

      let html = `
        <div class="patron-live-card">
          <div class="patron-live-info">
            <div class="patron-live-avatar"><i class="fas fa-user-graduate"></i></div>
            <div>
              <div class="patron-live-name">
                ${this.esc(this.currentPatron.name)}
                <span class="pill-tag">KOHA PATRON</span>
              </div>
              <div class="patron-live-meta">
                Card: <strong>${this.esc(this.currentPatron.card_number)}</strong>
                ${this.currentPatron.mifare_uid ? ` &middot; MIFARE: <strong>${this.esc(this.currentPatron.mifare_uid)}</strong>` : ''}
                &nbsp;|&nbsp; Fines: <strong class="ok-text">₹${this.esc(this.currentPatron.fee_amount)}</strong>
              </div>
            </div>
          </div>
          <div class="patron-live-right">
            <div class="patron-counter-badge" style="border-color:${color};">
              <div class="patron-counter-label">Books issued</div>
              <div class="patron-counter-num" style="color:${color};">
                ${count} <span class="muted">/ ${this.maxBooksAllowed}</span>
              </div>
              <div class="patron-counter-sub" style="color:${color};">${quotaText}</div>
            </div>
            <button class="btn-back-home" onclick="window.kioskApp.logoutPatron()">
              <i class="fas fa-sign-out-alt"></i> Logout
            </button>
          </div>
        </div>`;

      if (isFull) {
        html += `
          <div class="alert-banner danger">
            <i class="fas fa-exclamation-triangle"></i>
            <div><strong>Borrowing limit reached (${count}/${this.maxBooksAllowed}).</strong><br>
            Return a book before issuing another one.</div>
          </div>`;
      }

      if (this.currentPatron.charged_items.length > 0) {
        html += `
          <div class="issued-list-card">
            <div class="issued-list-title">
              <span><i class="fas fa-layer-group"></i> Currently issued (from Koha AU fields)</span>
              <span class="muted">max ${this.maxBooksAllowed}</span>
            </div>`;
        this.currentPatron.charged_items.forEach((barcode, idx) => {
          html += `
            <div class="issued-row">
              <div>
                <span class="issued-index">#${idx + 1}</span>
                <i class="fas fa-book info-text"></i>
                Barcode: <strong>${this.esc(barcode)}</strong>
              </div>
              <div class="issued-actions">
                <button class="btn-back-home small gold" onclick="window.kioskApp.renewBook('${this.escAttr(barcode)}')">
                  <i class="fas fa-sync-alt"></i> Renew
                </button>
                <button class="btn-back-home small green" onclick="window.kioskApp.returnBookDirect('${this.escAttr(barcode)}')">
                  <i class="fas fa-undo"></i> Return
                </button>
              </div>
            </div>`;
        });
        html += `</div>`;
      }

      container.innerHTML = html;
      return;
    }

    // Not authenticated
    if (this.activeWorkflow === 'return') {
      container.innerHTML = `
        <div class="alert-banner info">
          <i class="fas fa-info-circle"></i>
          <div><strong>Express Return — no login required.</strong><br>
          Place the book on the RFID pad or scan its barcode. Tags are re-armed on Koha check-in.</div>
        </div>`;
      return;
    }

    container.innerHTML = `
      <div class="auth-hub">
        <div class="auth-hub-title"><i class="fas fa-user-shield"></i> Identify yourself to continue</div>
        <div class="auth-hub-grid">
          <div class="auth-method">
            <i class="fas fa-id-card gold-text"></i>
            <h4>MIFARE Card</h4>
            <p>Tap your library card on the card reader.</p>
          </div>
          <div class="auth-method">
            <i class="fas fa-barcode info-text"></i>
            <h4>Barcode Scan</h4>
            <p>Scan your library-card barcode, or type it below.</p>
            <div class="auth-input-row">
              <input type="text" id="manual-patron-input" placeholder="Library card ID"
                     onkeydown="if(event.key==='Enter'){window.kioskApp.authenticatePatron(this.value);this.value='';}">
              <button class="btn-nfsu-action" onclick="const el=document.getElementById('manual-patron-input');window.kioskApp.authenticatePatron(el.value);el.value='';">Go</button>
            </div>
          </div>
          <div class="auth-method">
            <i class="fas fa-camera ok-text"></i>
            <h4>Face Liveness</h4>
            <p>Blink / head-turn check with the kiosk camera.</p>
            <button class="btn-nfsu-action full" onclick="window.kioskApp.openFaceLiveness()">
              <i class="fas fa-video"></i> Start Camera
            </button>
          </div>
        </div>
      </div>`;
  }

  // =====================================================================
  // Workflow body rendering
  // =====================================================================
  renderWorkflowDynamicContent() {
    const container = document.getElementById('workflow-dynamic-content');
    if (!container || !this.activeWorkflow) return;

    if (this.activeWorkflow === 'issue') return this.renderIssue(container);
    if (this.activeWorkflow === 'return') return this.renderReturn(container);
    if (this.activeWorkflow === 'renew') return this.renderRenew(container);
  }

  booksOnPad() {
    return (this.padState && this.padState.books_zone && this.padState.books_zone.books) || [];
  }

  renderBookCard(book, idx, afiAware) {
    const afi = book.afi;
    const afiLabel = afi ? `AFI ${afi}${afi === '0x07' ? ' (armed)' : afi === '0xC2' ? ' (disarmed)' : ''}` : 'AFI unknown';
    const afiClass = afi === '0x07' ? 'armed' : (afi === '0xC2' ? 'disarmed' : 'unknown');
    const sourceLabel = book.source === 'scanner' ? 'Barcode scan' : 'RFID pad';
    const barcode = book.barcode ? this.esc(book.barcode) : '<span class="danger-text">unmapped tag</span>';

    return `
      <div class="book-pad-item ${afiAware ? '' : 'plain'}">
        <div class="book-pad-cover">
          <span class="book-cover-chip"><i class="fas fa-microchip"></i> ${book.source === 'scanner' ? 'SCAN' : 'ISO 15693'}</span>
          <div class="book-cover-title">${this.esc(book.title)}</div>
        </div>
        <div class="book-pad-details">
          <div class="book-pad-head">Item #${idx + 1} &middot; ${sourceLabel}</div>
          <div class="book-pad-title">${this.esc(book.title)}</div>
          <div class="book-pad-meta">
            Author: <strong>${this.esc(book.author)}</strong><br>
            Barcode: <strong>${barcode}</strong> &nbsp;|&nbsp;
            Call: <strong>${this.esc(book.call_number)}</strong>
          </div>
          ${afiAware ? `<span class="afi-badge ${afiClass}">${afiLabel}</span>` : ''}
          ${book.known_in_koha === false ? `<span class="afi-badge unknown">not in Koha catalogue</span>` : ''}
        </div>
      </div>`;
  }

  renderIssue(container) {
    if (!this.currentPatron) {
      container.innerHTML = `<div class="workflow-hint"><i class="fas fa-arrow-up"></i> Authenticate above to unlock the checkout pad.</div>`;
      return;
    }

    const books = this.booksOnPad();
    const issued = this.currentPatron.charged_items_count;
    const wouldExceed = issued + books.length > this.maxBooksAllowed;
    const issuable = books.filter((b) => b.barcode);

    let html = `
      <div class="pad-workflow-card">
        <div class="pad-card-head">
          <div>
            <h4><i class="fas fa-microchip"></i> RFID Self-Check Pad</h4>
            <p>Place books on the pad or scan their barcodes (max ${this.maxBooksAllowed} at a time).</p>
          </div>
          <button class="btn-back-home small danger" onclick="window.kioskApp.clearScanned()">
            <i class="fas fa-broom"></i> Clear scanned
          </button>
        </div>
        <div class="books-pad-grid ${books.length > 1 ? 'two' : ''}">`;

    if (books.length === 0) {
      html += `<div class="pad-empty">
          <i class="fas fa-book-open"></i>
          <h5>Waiting for a book…</h5>
          <p>Lay the book flat on the RFID pad, or scan its barcode below.</p>
        </div>`;
    } else {
      html += books.map((b, i) => this.renderBookCard(b, i, true)).join('');
    }

    html += `</div>
        <div class="barcode-strip">
          <i class="fas fa-barcode"></i>
          <input type="text" id="manual-book-input" placeholder="Scan or type a book barcode…"
                 onkeydown="if(event.key==='Enter'){window.kioskApp.scanBook(this.value);this.value='';}">
          <button class="btn-back-home" onclick="const el=document.getElementById('manual-book-input');window.kioskApp.scanBook(el.value);el.value='';">Add</button>
        </div>`;

    if (wouldExceed) {
      html += `<div class="alert-banner danger">
          <i class="fas fa-ban"></i>
          <div><strong>Checkout blocked: 2-book limit would be exceeded.</strong><br>
          You hold ${issued} book(s) and ${books.length} item(s) are on the pad
          (total ${issued + books.length} &gt; ${this.maxBooksAllowed}). Remove items to continue.</div>
        </div>`;
    } else if (books.length > 0) {
      html += `<div class="action-bar ok">
          <div>
            <div class="action-title"><i class="fas fa-check-circle"></i> Ready to issue ${books.length} item(s)</div>
            <div class="action-sub">Koha SIP2 11 → 12, then two-phase-commit tag disarm (AFI 0xC2).</div>
          </div>
          <button class="btn-nfsu-action" ${issuable.length === 0 ? 'disabled' : ''}
                  onclick="window.kioskApp.confirmIssueCheckout()">
            <i class="fas fa-check-double"></i> Confirm Issue
          </button>
        </div>`;
      if (issuable.length !== books.length) {
        html += `<div class="alert-banner warn"><i class="fas fa-exclamation-triangle"></i>
          ${books.length - issuable.length} item(s) have no barcode (unmapped RFID tag) and will be skipped.</div>`;
      }
    }

    html += `</div>`;
    container.innerHTML = html;
  }

  renderReturn(container) {
    const books = this.booksOnPad();

    let html = `
      <div class="pad-workflow-card">
        <div class="pad-card-head">
          <div>
            <h4><i class="fas fa-inbox"></i> Express Return &amp; Tag Re-arm</h4>
            <p>Tags are re-armed with AFI 0x07 after Koha confirms the check-in.</p>
          </div>
          <button class="btn-back-home small danger" onclick="window.kioskApp.clearScanned()">
            <i class="fas fa-broom"></i> Clear scanned
          </button>
        </div>
        <div class="books-pad-grid ${books.length > 1 ? 'two' : ''}">`;

    if (books.length === 0) {
      html += `<div class="pad-empty">
          <i class="fas fa-book"></i>
          <h5>Place the book to return</h5>
          <p>Lay it on the RFID pad, or scan its barcode below.</p>
        </div>`;
    } else {
      html += books.map((b, i) => this.renderBookCard(b, i, false)).join('');
    }

    html += `</div>
        <div class="barcode-strip">
          <i class="fas fa-barcode"></i>
          <input type="text" id="manual-return-input" placeholder="Scan or type a book barcode to return…"
                 onkeydown="if(event.key==='Enter'){window.kioskApp.returnBookDirect(this.value);this.value='';}">
          <button class="btn-back-home" onclick="const el=document.getElementById('manual-return-input');window.kioskApp.returnBookDirect(el.value);el.value='';">Return</button>
        </div>`;

    if (books.length > 0) {
      html += `<div class="action-bar green">
          <div>
            <div class="action-title"><i class="fas fa-check-circle"></i> ${books.length} item(s) ready to check in</div>
            <div class="action-sub">Sends SIP2 09 → 10 and re-arms the security tag (AFI 0x07).</div>
          </div>
          <button class="btn-nfsu-action" onclick="window.kioskApp.confirmReturnCheckin()">
            <i class="fas fa-undo"></i> Confirm Return
          </button>
        </div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
  }

  renderRenew(container) {
    if (!this.currentPatron) {
      container.innerHTML = `<div class="workflow-hint"><i class="fas fa-arrow-up"></i> Authenticate above to view and renew your issued books.</div>`;
      return;
    }

    const issued = this.currentPatron.charged_items || [];
    let html = `
      <div class="pad-workflow-card">
        <div class="pad-card-head">
          <div>
            <h4><i class="fas fa-sync-alt"></i> Renew borrowed titles (SIP2 29 → 30)</h4>
            <p>Extend due dates for books currently charged to your account.</p>
          </div>
          ${issued.length > 0 ? `<button class="btn-nfsu-action" onclick="window.kioskApp.renewAllBooks()">
            <i class="fas fa-sync-alt"></i> Renew all (${issued.length})
          </button>` : ''}
        </div>`;

    if (issued.length === 0) {
      html += `<div class="pad-empty"><i class="fas fa-info-circle"></i>
          <h5>No books currently issued</h5>
          <p>You have no books charged to your account.</p></div>`;
    } else {
      html += `<div class="issued-column">` + issued.map((barcode, idx) => `
        <div class="issued-row">
          <div>
            <span class="issued-index">#${idx + 1}</span>
            <i class="fas fa-book info-text"></i>
            Barcode: <strong>${this.esc(barcode)}</strong>
            <div class="muted small-text">Standard 14-day extension per NFSU circulation policy.</div>
          </div>
          <button class="btn-nfsu-action" onclick="window.kioskApp.renewBook('${this.escAttr(barcode)}')">
            <i class="fas fa-sync-alt"></i> Renew
          </button>
        </div>`).join('') + `</div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
  }

  // =====================================================================
  // Circulation actions (two-phase commit lives on the server)
  // =====================================================================
  async confirmIssueCheckout() {
    if (!this.currentPatron) return;
    const books = this.booksOnPad().filter((b) => b.barcode);
    if (books.length === 0) return;

    for (const book of books) {
      try {
        const resp = await fetch('/api/circulation/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ patron_id: this.currentPatron.card_number, item_barcode: book.barcode }),
        });
        const res = await resp.json();
        if (window.sip2Console) window.sip2Console.renderResponse(res);

        if (res.ok) {
          this.showReceipt({
            type: 'CHECKOUT / ISSUE RECEIPT',
            patron_name: this.currentPatron.name,
            card_number: this.currentPatron.card_number,
            title: res.title || book.title,
            barcode: book.barcode,
            due_date: res.due_date || 'see Koha',
            afi_state: (res.rfid_afi_update && res.rfid_afi_update.success)
              ? '0xC2 (disarmed / EAS off)' : 'tag write failed',
            message: res.screen_message || 'Thank you for using the NFSU Central Library kiosk.',
          });
        } else {
          this.showToast(res.screen_message || res.error || `Checkout denied for ${book.barcode}`, 'error');
        }
      } catch (e) {
        this.showToast('Checkout request failed', 'error');
      }
    }

    await this.clearScanned();
    if (this.currentPatron) await this.loadPatron(this.currentPatron.card_number);
  }

  async confirmReturnCheckin() {
    const books = this.booksOnPad();
    if (books.length === 0) return;
    for (const book of books) {
      if (book.barcode) await this.returnBookDirect(book.barcode, book.title);
    }
    await this.clearScanned();
  }

  async returnBookDirect(barcode, fallbackTitle = '') {
    if (!barcode) return;
    try {
      const resp = await fetch('/api/circulation/checkin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_barcode: barcode }),
      });
      const res = await resp.json();
      if (window.sip2Console) window.sip2Console.renderResponse(res);

      if (res.ok) {
        if (window.gateBuzzer) window.gateBuzzer.playPassChime();
        this.showReceipt({
          type: 'CHECK-IN / RETURN RECEIPT',
          patron_name: this.currentPatron ? this.currentPatron.name : 'Express return',
          card_number: this.currentPatron ? this.currentPatron.card_number : '—',
          title: res.title || fallbackTitle || `Book (${barcode})`,
          barcode,
          due_date: 'returned',
          afi_state: (res.rfid_afi_update && res.rfid_afi_update.success)
            ? '0x07 (re-armed / EAS on)' : 'tag write failed',
          message: res.screen_message || 'Book returned and security tag re-armed.',
        });
      } else {
        this.showToast(res.screen_message || res.error || `Return failed for ${barcode}`, 'error');
      }
      if (this.currentPatron) await this.loadPatron(this.currentPatron.card_number);
    } catch (e) {
      this.showToast('Return request failed', 'error');
    }
  }

  async renewBook(barcode) {
    if (!this.currentPatron) return;
    try {
      const resp = await fetch('/api/circulation/renew', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patron_id: this.currentPatron.card_number, item_barcode: barcode }),
      });
      const res = await resp.json();
      if (window.sip2Console) window.sip2Console.renderResponse(res);
      this.showToast(
        res.screen_message || (res.ok ? 'Renewal approved' : 'Renewal refused by Koha'),
        res.ok ? 'ok' : 'error'
      );
      await this.loadPatron(this.currentPatron.card_number);
    } catch (e) {
      this.showToast('Renewal request failed', 'error');
    }
  }

  async renewAllBooks() {
    if (!this.currentPatron) return;
    for (const barcode of [...(this.currentPatron.charged_items || [])]) {
      await this.renewBook(barcode);
    }
  }

  // =====================================================================
  // Hardware input endpoints
  // =====================================================================
  async scanBook(barcode) {
    if (!barcode || !barcode.trim()) return;
    try {
      const resp = await fetch('/api/hardware/scan-book', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ barcode: barcode.trim() }),
      });
      const res = await resp.json();
      if (!res.success) this.showToast(res.error || 'Could not add item', 'error');
      await this.refreshState();
    } catch (e) {
      this.showToast('Scan failed', 'error');
    }
  }

  async scanPatron(barcode) {
    if (!barcode || !barcode.trim()) return;
    await this.authenticatePatron(barcode.trim());
  }

  async clearScanned() {
    try {
      await fetch('/api/hardware/clear-scanned', { method: 'POST' });
      await this.refreshState();
    } catch (e) { /* ignore */ }
  }

  async refreshState() {
    try {
      const resp = await fetch('/api/hardware/pad-state');
      this.padState = await resp.json();
      if (this.padState.hardware) this.updateHardwareUI(this.padState.hardware);
      this.syncPatronFromPad();
      if (this.currentPatron) await this.loadPatron(this.currentPatron.card_number);
      this.renderWorkflowViews();
    } catch (e) { /* ignore */ }
  }

  // =====================================================================
  // Modals, toasts, receipts
  // =====================================================================
  openGateModal() {
    const modal = document.getElementById('gate-buzzer-modal');
    if (modal) modal.style.display = 'flex';
  }

  closeGateModal() {
    const modal = document.getElementById('gate-buzzer-modal');
    if (modal) modal.style.display = 'none';
  }

  openFaceLiveness() {
    const patronId = this.currentPatron ? this.currentPatron.card_number : null;
    if (window.faceLiveness) window.faceLiveness.openLivenessModal(patronId);
  }

  showReceipt(details) {
    const modal = document.getElementById('receipt-modal');
    const content = document.getElementById('receipt-printable-content');
    if (!modal || !content) return;

    content.innerHTML = `
      <div class="receipt-head">
        <img src="/assets/img/NFSU_logo.png" alt="NFSU">
        <h4>NATIONAL FORENSIC SCIENCES UNIVERSITY</h4>
        <div class="receipt-sub">CENTRAL LIBRARY SELF-SERVICE KIOSK</div>
        <div class="receipt-addr">Sector-9, Gandhinagar - 382007, Gujarat</div>
        <div class="receipt-type">${this.esc(details.type)}</div>
      </div>
      <table class="receipt-table">
        <tr><td>Transaction time</td><td>${new Date().toLocaleString('en-IN')}</td></tr>
        <tr><td>Patron</td><td><strong>${this.esc(details.patron_name)}</strong></td></tr>
        <tr><td>Patron ID</td><td>${this.esc(details.card_number)}</td></tr>
        <tr><td>Title</td><td><strong>${this.esc(details.title)}</strong></td></tr>
        <tr><td>Item barcode</td><td>${this.esc(details.barcode)}</td></tr>
        <tr><td>Due date</td><td class="ok-text"><strong>${this.esc(details.due_date)}</strong></td></tr>
        <tr><td>RFID tag</td><td class="gold-text">${this.esc(details.afi_state)}</td></tr>
      </table>
      <div class="receipt-foot"><em>${this.esc(details.message)}</em></div>`;
    modal.style.display = 'flex';
  }

  closeReceiptModal() {
    const modal = document.getElementById('receipt-modal');
    if (modal) modal.style.display = 'none';
  }

  printReceipt() {
    window.print();
  }

  showToast(message, kind = 'info') {
    let host = document.getElementById('kiosk-toasts');
    if (!host) {
      host = document.createElement('div');
      host.id = 'kiosk-toasts';
      host.className = 'kiosk-toasts';
      document.body.appendChild(host);
    }
    const toast = document.createElement('div');
    toast.className = `kiosk-toast ${kind}`;
    toast.innerHTML = `<i class="fas ${kind === 'error' ? 'fa-exclamation-circle' : kind === 'ok' ? 'fa-check-circle' : 'fa-info-circle'}"></i> ${this.esc(message)}`;
    host.appendChild(toast);
    setTimeout(() => toast.classList.add('visible'), 10);
    setTimeout(() => {
      toast.classList.remove('visible');
      setTimeout(() => toast.remove(), 300);
    }, 4500);
  }

  // =====================================================================
  // Barcode scanner (HID keyboard-wedge / serial)
  // =====================================================================
  attachBarcodeScanner() {
    let buffer = '';
    let last = Date.now();

    window.addEventListener('keydown', (e) => {
      if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;

      const now = Date.now();
      if (now - last > 200) buffer = '';
      last = now;

      if (e.key === 'Enter') {
        const code = buffer.trim();
        buffer = '';
        if (code.length < 2) return;
        if (window.sip2Console) window.sip2Console.logTerminal(`[SCANNER] ${code}`, 'info');

        if (this.activeWorkflow === 'return') {
          this.returnBookDirect(code);
        } else if (!this.currentPatron) {
          this.scanPatron(code);
        } else {
          this.scanBook(code);
        }
      } else if (e.key.length === 1) {
        buffer += e.key;
      }
    });
  }

  // =====================================================================
  // Helpers
  // =====================================================================
  esc(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  escAttr(value) {
    return this.esc(value);
  }
}

window.kioskApp = new NFSUKioskApp();
document.addEventListener('DOMContentLoaded', () => window.kioskApp.init());
