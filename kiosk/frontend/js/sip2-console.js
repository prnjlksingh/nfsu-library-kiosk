/**
 * NFSU Central Library Self-Service Kiosk - SIP2 Testing Tool
 * National Forensic Sciences University, Gandhinagar
 * Integrated with Koha 26 ILMS (PS-2)
 *
 * Diagnostics console:
 * - One-click packet builders for 99/98, 93/94, 63/64, 17/18, 11/12, 09/10, 29/30
 * - Raw ASCII frame inspector with AY sequence and AZ checksum validation
 * - Field-by-field breakdown parser
 * - Koha SIP2 endpoint switcher
 */

class SIP2ConsoleController {
  constructor() {
    this.drawer = null;
    this.terminal = null;
    this.inspector = null;
  }

  init() {
    this.drawer = document.getElementById('sip-diagnostics-drawer');
    this.terminal = document.getElementById('sip-terminal-output');
    this.inspector = document.getElementById('sip-packet-breakdown');
  }

  toggleDrawer() {
    if (!this.drawer) this.init();
    if (this.drawer) this.drawer.classList.toggle('open');
  }

  openDrawer() {
    if (!this.drawer) this.init();
    if (this.drawer) this.drawer.classList.add('open');
  }

  closeDrawer() {
    if (!this.drawer) this.init();
    if (this.drawer) this.drawer.classList.remove('open');
  }

  val(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
  }

  logTerminal(text, type = 'info') {
    if (!this.terminal) this.init();
    if (!this.terminal) return;
    const color = type === 'out' ? '#fbbf24' : type === 'in' ? '#34d399' : type === 'err' ? '#f87171' : '#38bdf8';
    const time = new Date().toLocaleTimeString();
    this.terminal.innerHTML += `<div style="color:${color}; margin-bottom:4px;">[${time}] ${text}</div>`;
    this.terminal.scrollTop = this.terminal.scrollHeight;
  }

  async sendRawPacket(rawPacket) {
    this.logTerminal(`TX >> ${rawPacket}`, 'out');
    try {
      const resp = await fetch('/api/sip2/send-raw', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_packet: rawPacket }),
      });
      const data = await resp.json();
      this.renderResponse(data);
      return data;
    } catch (e) {
      this.logTerminal(`ERROR >> ${e.message}`, 'err');
    }
  }

  renderResponse(data) {
    if (!data) return;
    if (data.raw) this.logTerminal(`RX << ${data.raw}`, 'in');
    if (data.error) this.logTerminal(`ERROR >> ${data.error}`, 'err');
    if (data.latency_ms !== undefined) {
      this.logTerminal(`Round-trip ${data.latency_ms} ms (checksum ${data.checksum_valid ? 'valid' : 'invalid/none'})`);
    }

    if (!this.inspector) return;
    const row = (label, value) => `<tr><td>${label}</td><td>${value}</td></tr>`;

    let html = `<div class="breakdown-card">`;
    html += `<div class="breakdown-head">
        <span>${data.type || data.command || 'Response'}</span>
        <span class="badge ${data.checksum_valid ? 'ok' : 'warn'}">AZ ${data.checksum_valid ? 'VALID' : 'CHECK'}</span>
      </div><table>`;
    html += row('Command code', `<strong>${data.command || '—'}</strong>`);
    if (data.patron_id) html += row('Patron ID (AA)', data.patron_id);
    if (data.patron_name) html += row('Patron name (AE)', data.patron_name);
    if (data.charged_items_count !== undefined) html += row('Charged count', `${data.charged_items_count}`);
    if (data.charged_items && data.charged_items.length) html += row('Issued (AU)', data.charged_items.join(', '));
    if (data.item_barcode) html += row('Item barcode (AB)', data.item_barcode);
    if (data.title) html += row('Title (AJ)', data.title);
    if (data.due_date) html += row('Due date (AH)', data.due_date);
    if (data.screen_message) html += row('Screen message (AF)', data.screen_message);
    if (data.ok !== undefined) html += row('Status', data.ok ? 'APPROVED (OK=1)' : 'DENIED (OK=0)');
    html += `</table></div>`;
    this.inspector.innerHTML = html;
  }

  // ----------------------------------------------------------------
  // One-click packet builders
  // ----------------------------------------------------------------
  async test99Status() {
    await this.sendRawPacket('9900302.00');
  }

  async test93Login() {
    const user = this.val('sip-test-user');
    const pass = this.val('sip-test-pass');
    if (!user) return this.logTerminal('Enter the SIP2 username above first.', 'err');
    await this.sendRawPacket(`9300CN${user}|CO${pass}|CP|`);
  }

  async test63PatronInfo() {
    const patron = this.val('sip-test-patron');
    if (!patron) return this.logTerminal('Enter a patron ID above first.', 'err');
    const now = this._ts();
    await this.sendRawPacket(`63001${now}  Y       AONFSUGNR|AA${patron}|AC|AD|`);
  }

  async test17ItemInfo() {
    const barcode = this.val('sip-test-barcode');
    if (!barcode) return this.logTerminal('Enter an item barcode above first.', 'err');
    await this.sendRawPacket(`17${this._ts()}AONFSUGNR|AB${barcode}|AC|`);
  }

  async testCustom(kind) {
    const patron = this.val('sip-test-patron');
    const barcode = this.val('sip-test-barcode');
    const now = this._ts();
    if (kind === 'checkout') {
      if (!patron || !barcode) return this.logTerminal('Enter patron ID and item barcode first.', 'err');
      await this.sendRawPacket(`11YN${now}                  AONFSUGNR|AA${patron}|AB${barcode}|AC|`);
    } else if (kind === 'checkin') {
      if (!barcode) return this.logTerminal('Enter an item barcode first.', 'err');
      await this.sendRawPacket(`09N${now}${now}AP|AONFSUGNR|AB${barcode}|AC|`);
    } else if (kind === 'renew') {
      if (!patron || !barcode) return this.logTerminal('Enter patron ID and item barcode first.', 'err');
      await this.sendRawPacket(`29NN${now}                  AONFSUGNR|AA${patron}|AB${barcode}|AC|`);
    }
  }

  async sendRawFromInput() {
    const el = document.getElementById('sip-raw-input');
    if (!el || !el.value.trim()) return;
    await this.sendRawPacket(el.value.trim());
  }

  _ts() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const date = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
    const time = `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
    return `${date}    ${time}`;
  }

  // ----------------------------------------------------------------
  // Connection switcher
  // ----------------------------------------------------------------
  async switchKohaConnection(host, port) {
    if (!host || !port) {
      this.logTerminal('Enter a host and port first.', 'err');
      return;
    }
    try {
      this.logTerminal(`Connecting to Koha SIP2 at ${host}:${port} …`);
      const resp = await fetch('/api/sip2/reconnect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host, port: parseInt(port, 10) }),
      });
      const data = await resp.json();
      if (data.success) {
        this.logTerminal(`Connected to ${host}:${port}.`, 'in');
        if (window.kioskApp) window.kioskApp.updateTelemetryUI(data.telemetry);
      } else {
        const err = (data.telemetry && data.telemetry.last_error) || 'connection failed';
        this.logTerminal(`Failed: ${err}`, 'err');
        if (window.kioskApp) window.kioskApp.updateTelemetryUI(data.telemetry);
      }
    } catch (e) {
      this.logTerminal(`Error: ${e.message}`, 'err');
    }
  }
}

window.sip2Console = new SIP2ConsoleController();
