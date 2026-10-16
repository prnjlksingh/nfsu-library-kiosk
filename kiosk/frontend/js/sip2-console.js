/**
 * NFSU Central Library Self-Service Kiosk - SIP2 Diagnostic Suite & Testing Tool
 * National Forensic Sciences University, Gandhinagar
 * Integrated with Koha 26 ILMS (PS-2)
 *
 * Implements:
 * - 1-Click Packet Builder for 99/98, 93/94, 63/64, 17/18, 11/12, 09/10, 29/30
 * - Raw SIP2 ASCII Frame Inspector with AY Sequence & AZ Checksum Validation
 * - Field-by-Field Breakdown Parser
 * - Koha Server / Emulator Reconfiguration
 * - Least-Privilege SIPconfig.xml Generator
 */

class SIP2ConsoleController {
  constructor() {
    this.drawer = null;
    this.terminal = null;
    this.inspector = null;
    this.history = [];
  }

  init() {
    this.drawer = document.getElementById('sip-diagnostics-drawer');
    this.terminal = document.getElementById('sip-terminal-output');
    this.inspector = document.getElementById('sip-packet-breakdown');
  }

  toggleDrawer() {
    if (!this.drawer) this.init();
    if (this.drawer) {
      this.drawer.classList.toggle('open');
    }
  }

  openDrawer() {
    if (!this.drawer) this.init();
    if (this.drawer) {
      this.drawer.classList.add('open');
    }
  }

  closeDrawer() {
    if (!this.drawer) this.init();
    if (this.drawer) {
      this.drawer.classList.remove('open');
    }
  }

  logTerminal(text, type = 'info') {
    if (!this.terminal) this.init();
    if (!this.terminal) return;

    const time = new Date().toLocaleTimeString();
    let color = '#38bdf8';
    if (type === 'out') color = '#fbbf24';  // Yellow for outbound
    if (type === 'in') color = '#34d399';   // Green for inbound
    if (type === 'err') color = '#f87171';  // Red for error

    const line = `<div style="color:${color}; margin-bottom:4px;">[${time}] ${text}</div>`;
    this.terminal.innerHTML += line;
    this.terminal.scrollTop = this.terminal.scrollHeight;
  }

  async sendRawPacket(rawPacket) {
    this.logTerminal(`TX >> ${rawPacket}`, 'out');
    try {
      const resp = await fetch('/api/sip2/send-raw', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_packet: rawPacket })
      });
      const data = await resp.json();
      this.renderResponse(data);
      return data;
    } catch (e) {
      this.logTerminal(`ERROR >> ${e.message}`, 'err');
    }
  }

  renderResponse(data) {
    if (data.raw) {
      this.logTerminal(`RX << ${data.raw}`, 'in');
    }
    if (data.latency_ms !== undefined) {
      this.logTerminal(`⏱️ Round-Trip Latency: ${data.latency_ms} ms (Checksum: ${data.checksum_valid ? 'VALID' : 'NONE/INVALID'})`, 'info');
    }

    if (!this.inspector) return;

    let html = `<div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:12px; margin-top:8px;">`;
    html += `<div style="font-weight:700; color:#002147; border-bottom:1px solid #e2e8f0; padding-bottom:6px; margin-bottom:8px; display:flex; justify-content:space-between;">`;
    html += `<span>Parsed Message: ${data.type || data.command}</span>`;
    html += `<span class="badge" style="background:${data.checksum_valid ? '#10b981' : '#f59e0b'}; color:white; font-size:10px; padding:2px 6px; border-radius:4px;">AZ Checksum: ${data.checksum_valid ? 'VALID' : 'CHECK'}</span>`;
    html += `</div>`;

    html += `<table style="width:100%; font-size:12px; border-collapse:collapse;">`;
    html += `<tr><td style="color:#64748b; width:35%;">Command Code:</td><td style="font-family:monospace; font-weight:700;">${data.command}</td></tr>`;
    
    if (data.patron_id) html += `<tr><td style="color:#64748b;">Patron ID (AA):</td><td style="font-weight:700;">${data.patron_id}</td></tr>`;
    if (data.patron_name) html += `<tr><td style="color:#64748b;">Patron Name (AE):</td><td style="font-weight:700;">${data.patron_name}</td></tr>`;
    if (data.charged_items_count !== undefined) {
      html += `<tr><td style="color:#64748b;">Charged Items Count:</td><td style="font-weight:800; color:#002147;">${data.charged_items_count} / 2</td></tr>`;
    }
    if (data.charged_items && data.charged_items.length > 0) {
      html += `<tr><td style="color:#64748b;">Issued Barcodes (AU):</td><td style="font-family:monospace; color:#d97706;">${data.charged_items.join(', ')}</td></tr>`;
    }
    if (data.item_barcode) html += `<tr><td style="color:#64748b;">Item Barcode (AB):</td><td style="font-family:monospace;">${data.item_barcode}</td></tr>`;
    if (data.title) html += `<tr><td style="color:#64748b;">Book Title (AJ):</td><td style="font-weight:600;">${data.title}</td></tr>`;
    if (data.due_date) html += `<tr><td style="color:#64748b;">Due Date (AH):</td><td style="font-weight:700; color:#10b981;">${data.due_date}</td></tr>`;
    if (data.screen_message) html += `<tr><td style="color:#64748b;">Screen Msg (AF):</td><td style="font-style:italic; color:#0f172a;">${data.screen_message}</td></tr>`;
    if (data.ok !== undefined) {
      html += `<tr><td style="color:#64748b;">Transaction Status:</td><td><strong style="color:${data.ok ? '#10b981' : '#dc2626'};">${data.ok ? 'APPROVED (OK=1)' : 'DENIED / BLOCKED (OK=0)'}</strong></td></tr>`;
    }

    html += `</table></div>`;
    this.inspector.innerHTML = html;
  }

  // Quick 1-Click Packet Builders with LIVE Koha 26 Credentials
  async test99Status() {
    await this.sendRawPacket("9900302.00");
  }

  async test93Login(user = "rfid", pwd = "Rfid@123") {
    await this.sendRawPacket(`9300CN${user}|CO${pwd}|CP|`);
  }

  async test63PatronInfo(patronId = "rfid") {
    const now = new Date().toISOString().slice(0, 10).replace(/-/g, '') + '    140000';
    await this.sendRawPacket(`63001${now}  Y       AONFSUGNR|AA${patronId}|AC|AD|`);
  }

  async test17ItemInfo(barcode = "NFSU-BK-104") {
    const now = new Date().toISOString().slice(0, 10).replace(/-/g, '') + '    140000';
    await this.sendRawPacket(`17${now}AONFSUGNR|AB${barcode}|AC|`);
  }

  async test11Checkout(patronId = "rfid", barcode = "NFSU-BK-104") {
    const now = new Date().toISOString().slice(0, 10).replace(/-/g, '') + '    140000';
    await this.sendRawPacket(`11YN${now}                  AONFSUGNR|AA${patronId}|AB${barcode}|AC|`);
  }

  async test09Checkin(barcode = "NFSU-BK-104") {
    const now = new Date().toISOString().slice(0, 10).replace(/-/g, '') + '    140000';
    await this.sendRawPacket(`09N${now}${now}AP|AONFSUGNR|AB${barcode}|AC|`);
  }

  async test29Renew(patronId = "rfid", barcode = "NFSU-BK-101") {
    const now = new Date().toISOString().slice(0, 10).replace(/-/g, '') + '    140000';
    await this.sendRawPacket(`29NN${now}                  AONFSUGNR|AA${patronId}|AB${barcode}|AC|`);
  }

  async switchKohaConnection(host, port) {
    try {
      this.logTerminal(`Connecting to Koha SIP2 at ${host}:${port}...`, 'info');
      const resp = await fetch('/api/sip2/reconnect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host, port: parseInt(port) })
      });
      const data = await resp.json();
      if (data.success) {
        this.logTerminal(`Connected successfully to ${host}:${port}!`, 'in');
        window.kioskApp.updateTelemetryUI(data.telemetry);
      } else {
        this.logTerminal(`Failed to connect to ${host}:${port}`, 'err');
      }
    } catch (e) {
      this.logTerminal(`Error connecting: ${e.message}`, 'err');
    }
  }

  async resetDemoData() {
    try {
      const resp = await fetch('/api/emulator/reset', { method: 'POST' });
      const data = await resp.json();
      this.logTerminal(`DEMO DATA RESET: ${data.message}`, 'info');
      if (window.kioskApp) {
        window.kioskApp.refreshState();
      }
    } catch (e) {
      this.logTerminal(`Reset failed: ${e.message}`, 'err');
    }
  }
}

window.sip2Console = new SIP2ConsoleController();
