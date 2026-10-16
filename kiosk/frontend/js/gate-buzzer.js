/**
 * NFSU Central Library Self-Service Kiosk - Library Exit Security Gate & Buzzer
 * National Forensic Sciences University, Gandhinagar
 * Integrated with Koha 26 ILMS (PS-2)
 *
 * Implements:
 * - Web Audio API oscillating siren for unissued books (AFI 0x07)
 * - Soft harmonic chime for verified issued books (AFI 0xC2)
 * - Visual crimson strobe alert banner
 */

class GateBuzzerController {
  constructor() {
    this.audioCtx = null;
    this.alarmOscillator = null;
    this.alarmGain = null;
    this.alarmInterval = null;
    this.isAlarmActive = false;
  }

  initAudio() {
    if (!this.audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      this.audioCtx = new AudioContext();
    }
    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
  }

  // Play pleasant chime for properly issued book (AFI 0xC2)
  playPassChime() {
    this.initAudio();
    const ctx = this.audioCtx;
    const now = ctx.currentTime;

    const freqs = [523.25, 659.25, 783.99]; // C5, E5, G5 major triad
    freqs.forEach((freq, idx) => {
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

  // Play loud alternating security buzzer siren for unissued book (AFI 0x07)
  startGateBuzzerAlarm() {
    this.initAudio();
    if (this.isAlarmActive) return;

    this.isAlarmActive = true;
    const ctx = this.audioCtx;
    let highTone = true;

    this.alarmInterval = setInterval(() => {
      if (!this.isAlarmActive) return;
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(highTone ? 1150 : 850, now);

      gain.gain.setValueAtTime(0.35, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(now);
      osc.stop(now + 0.24);

      highTone = !highTone;
    }, 250);
  }

  stopGateBuzzerAlarm() {
    this.isAlarmActive = false;
    if (this.alarmInterval) {
      clearInterval(this.alarmInterval);
      this.alarmInterval = null;
    }
  }

  handleGateWalkthrough(gateData) {
    const alarmBanner = document.getElementById('gate-alarm-banner');
    const clearBanner = document.getElementById('gate-clear-banner');
    const gatePillars = document.querySelectorAll('.gate-antenna-pillar');
    const laserLine = document.querySelector('.gate-laser-line');

    if (gateData.alarm) {
      // Trigger Siren
      this.startGateBuzzerAlarm();

      if (alarmBanner) {
        alarmBanner.style.display = 'block';
        alarmBanner.innerHTML = `
          <i class="fas fa-exclamation-triangle"></i>
          <strong>SECURITY GATE ALARM TRIGGERED!</strong><br>
          Unissued Book Detected: <em>${gateData.title}</em> (${gateData.barcode})<br>
          <span style="font-size: 11px;">RFID Tag State: AFI = 0x07 [ARMED - EAS ACTIVE]</span>
          <button onclick="gateBuzzer.stopGateBuzzerAlarm(); this.parentElement.style.display='none';"
                  style="margin-top:6px; display:block; width:100%; padding:4px; font-size:11px; font-weight:700; background:#dc2626; color:white; border:none; border-radius:4px; cursor:pointer;">
            Mute & Silence Alarm
          </button>
        `;
      }
      if (clearBanner) clearBanner.style.display = 'none';

      gatePillars.forEach(p => p.classList.add('alarm'));
      if (laserLine) laserLine.classList.add('alarm');

      // Auto-silence after 8 seconds if not silenced manually
      setTimeout(() => {
        if (this.isAlarmActive) {
          this.stopGateBuzzerAlarm();
          gatePillars.forEach(p => p.classList.remove('alarm'));
          if (laserLine) laserLine.classList.remove('alarm');
        }
      }, 8000);

    } else {
      // Clear Pass
      this.stopGateBuzzerAlarm();
      this.playPassChime();

      if (alarmBanner) alarmBanner.style.display = 'none';
      if (clearBanner) {
        clearBanner.style.display = 'block';
        clearBanner.innerHTML = `
          <i class="fas fa-check-circle"></i>
          <strong>GATE CLEAR — VERIFIED KOHA ISSUE</strong><br>
          <em>${gateData.title}</em> (${gateData.barcode})<br>
          <span style="font-size: 11px;">RFID Tag State: AFI = 0xC2 [DISARMED - EAS OFF]</span>
        `;
        setTimeout(() => { clearBanner.style.display = 'none'; }, 5000);
      }

      gatePillars.forEach(p => p.classList.remove('alarm'));
      if (laserLine) laserLine.classList.remove('alarm');
    }
  }
}

window.gateBuzzer = new GateBuzzerController();
