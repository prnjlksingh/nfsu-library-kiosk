/**
 * NFSU Central Library Self-Service Kiosk - Exit Security Gate & Buzzer
 * National Forensic Sciences University, Gandhinagar
 * Integrated with Koha 26 ILMS (PS-2)
 *
 * Renders alarms raised by the real exit-gate antenna:
 * - AFI 0x07 (armed)  -> alternating 850/1150 Hz siren + crimson strobe
 * - AFI 0xC2 (disarmed) -> soft major-triad chime
 * - AFI unreadable    -> manual-check warning
 */

class GateBuzzerController {
  constructor() {
    this.audioCtx = null;
    this.alarmInterval = null;
    this.isAlarmActive = false;
    this.autoSilenceTimer = null;
  }

  initAudio() {
    if (!this.audioCtx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      this.audioCtx = new Ctx();
    }
    if (this.audioCtx.state === 'suspended') this.audioCtx.resume();
  }

  playPassChime() {
    this.initAudio();
    const ctx = this.audioCtx;
    const now = ctx.currentTime;
    [523.25, 659.25, 783.99].forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, now + idx * 0.08);
      gain.gain.setValueAtTime(0, now + idx * 0.08);
      gain.gain.linearRampToValueAtTime(0.18, now + idx * 0.08 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + idx * 0.08 + 0.5);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + idx * 0.08);
      osc.stop(now + idx * 0.08 + 0.55);
    });
  }

  startGateBuzzerAlarm() {
    this.initAudio();
    if (this.isAlarmActive) return;
    this.isAlarmActive = true;
    const ctx = this.audioCtx;
    let high = true;
    this.alarmInterval = setInterval(() => {
      if (!this.isAlarmActive) return;
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(high ? 1150 : 850, now);
      gain.gain.setValueAtTime(0.35, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.24);
      high = !high;
    }, 250);
  }

  stopGateBuzzerAlarm() {
    this.isAlarmActive = false;
    if (this.alarmInterval) {
      clearInterval(this.alarmInterval);
      this.alarmInterval = null;
    }
    if (this.autoSilenceTimer) {
      clearTimeout(this.autoSilenceTimer);
      this.autoSilenceTimer = null;
    }
  }

  handleGateWalkthrough(gateData) {
    if (!gateData) return;
    const alarmBanner = document.getElementById('gate-alarm-banner');
    const clearBanner = document.getElementById('gate-clear-banner');
    const live = document.getElementById('gate-live-status');
    const pillars = document.querySelectorAll('.gate-antenna-pillar');
    const laser = document.querySelector('.gate-laser-line');

    const setPillars = (alarm) => {
      pillars.forEach((p) => p.classList.toggle('alarm', alarm));
      if (laser) laser.classList.toggle('alarm', alarm);
    };

    if (live) {
      live.textContent = `${gateData.barcode || gateData.tag_uid || 'tag'} · ${gateData.afi || 'AFI unknown'}`;
    }

    if (gateData.alarm) {
      this.startGateBuzzerAlarm();
      if (alarmBanner) {
        alarmBanner.style.display = 'block';
        alarmBanner.innerHTML = `
          <i class="fas fa-exclamation-triangle"></i>
          <strong>SECURITY GATE ALARM</strong><br>
          Unissued book detected: <em>${gateData.barcode || gateData.tag_uid}</em><br>
          <span class="small-text">Tag state: AFI = 0x07 (armed / EAS active)</span>
          <button onclick="window.gateBuzzer.stopGateBuzzerAlarm(); this.parentElement.style.display='none';">
            Mute &amp; silence
          </button>`;
      }
      if (clearBanner) clearBanner.style.display = 'none';
      setPillars(true);

      this.autoSilenceTimer = setTimeout(() => {
        if (this.isAlarmActive) {
          this.stopGateBuzzerAlarm();
          setPillars(false);
        }
      }, 8000);

    } else if (gateData.unknown_afi) {
      this.stopGateBuzzerAlarm();
      setPillars(false);
      if (alarmBanner) alarmBanner.style.display = 'none';
      if (clearBanner) {
        clearBanner.style.display = 'block';
        clearBanner.className = 'gate-clear-banner warn';
        clearBanner.innerHTML = `
          <i class="fas fa-question-circle"></i>
          <strong>TAG AFI UNREADABLE</strong><br>
          <em>${gateData.barcode || gateData.tag_uid}</em> — please perform a manual check.`;
      }
    } else {
      this.stopGateBuzzerAlarm();
      this.playPassChime();
      if (alarmBanner) alarmBanner.style.display = 'none';
      if (clearBanner) {
        clearBanner.className = 'gate-clear-banner';
        clearBanner.style.display = 'block';
        clearBanner.innerHTML = `
          <i class="fas fa-check-circle"></i>
          <strong>GATE CLEAR — VERIFIED KOHA ISSUE</strong><br>
          <em>${gateData.barcode || gateData.tag_uid}</em><br>
          <span class="small-text">Tag state: AFI = 0xC2 (disarmed / EAS off)</span>`;
        setTimeout(() => { clearBanner.style.display = 'none'; }, 5000);
      }
      setPillars(false);
    }
  }
}

window.gateBuzzer = new GateBuzzerController();
