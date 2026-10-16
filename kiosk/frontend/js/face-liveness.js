/**
 * NFSU Central Library Self-Service Kiosk - Facial Liveness Module
 * National Forensic Sciences University, Gandhinagar
 * Integrated with Koha 26 ILMS (PS-2)
 *
 * Performs REAL liveness analysis on the live camera feed:
 * - Consecutive frames are sampled to a small grayscale buffer
 * - Motion energy = mean absolute inter-frame difference (a static photo fails)
 * - Eye-region brightness is tracked to detect a blink and its recovery
 * - Face position (native FaceDetector when available, motion centroid otherwise)
 *   is tracked to verify the requested head turn
 *
 * Only the anonymous metrics are sent to the server, which validates them
 * against the challenge it issued. Nothing is stored, on device or server.
 */

class FaceLivenessController {
  constructor() {
    this.video = null;
    this.stream = null;
    this.session = null;
    this.claimedPatron = null;
    this.isVerifying = false;
    this.faceDetector = null;
  }

  // ------------------------------------------------------------------
  // Camera
  // ------------------------------------------------------------------
  async startWebcam() {
    this.video = document.getElementById('liveness-video');
    if (!this.video) return false;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: 'user' },
        audio: false,
      });
      this.video.srcObject = this.stream;
      await this.video.play();
      return true;
    } catch (err) {
      this.setStatus('Camera unavailable — check the device and browser permission.', true);
      return false;
    }
  }

  stopWebcam() {
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.video) this.video.srcObject = null;
  }

  async openLivenessModal(claimedPatronId) {
    const modal = document.getElementById('face-auth-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    this.claimedPatron = claimedPatronId || null;

    const input = document.getElementById('liveness-patron-input');
    if (input) input.value = claimedPatronId || '';

    const started = await this.startWebcam();
    if (!started) return;

    try {
      const resp = await fetch('/api/biometrics/challenge', { method: 'POST' });
      this.session = await resp.json();
      const inst = document.getElementById('liveness-challenge-text');
      if (inst) inst.innerHTML = `<i class="fas fa-face-smile"></i> ${this.session.instruction}`;
      this.setStatus('Position your face inside the oval, then run the check.');
    } catch (e) {
      this.setStatus('Could not start a liveness session.', true);
    }
  }

  closeLivenessModal() {
    this.isVerifying = false;
    this.stopWebcam();
    const modal = document.getElementById('face-auth-modal');
    if (modal) modal.style.display = 'none';
  }

  // ------------------------------------------------------------------
  // Analysis
  // ------------------------------------------------------------------
  setStatus(text, isError = false) {
    const el = document.getElementById('liveness-status-msg');
    if (!el) return;
    el.textContent = text;
    el.style.color = isError ? '#dc2626' : '#002147';
  }

  setProgress(pct) {
    const el = document.getElementById('liveness-progress-bar');
    if (el) el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }

  setMetrics(text) {
    const el = document.getElementById('liveness-metrics');
    if (el) el.textContent = text;
  }

  _grayscaleFrame(ctx, w, h) {
    const img = ctx.getImageData(0, 0, w, h);
    const data = img.data;
    const gray = new Float32Array(w * h);
    for (let i = 0, p = 0; i < data.length; i += 4, p++) {
      gray[p] = (data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) / 255;
    }
    return gray;
  }

  _regionMean(gray, w, h, x0, y0, x1, y1) {
    let sum = 0;
    let n = 0;
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        sum += gray[y * w + x];
        n++;
      }
    }
    return n ? sum / n : 0;
  }

  async runChallenge() {
    if (this.isVerifying) return;

    const input = document.getElementById('liveness-patron-input');
    const patronId = input ? input.value.trim() : '';
    if (!patronId) {
      this.setStatus('Enter the library card ID to bind this check to.', true);
      return;
    }
    if (!this.stream) {
      const ok = await this.startWebcam();
      if (!ok) return;
    }

    this.isVerifying = true;
    const startBtn = document.getElementById('liveness-start-btn');
    if (startBtn) startBtn.disabled = true;

    const w = 80;
    const h = 60;
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    if (!this.faceDetector && 'FaceDetector' in window) {
      try { this.faceDetector = new window.FaceDetector({ fastMode: true }); } catch (e) { this.faceDetector = null; }
    }

    const DURATION_MS = 4500;
    const start = performance.now();

    let frames = 0;
    let motionSum = 0;
    let motionSamples = 0;
    let prevGray = null;
    let faceFrames = 0;
    let eyeBaselineSum = 0;
    let eyeMin = 1;
    let eyeLast = 1;
    const centroids = [];
    const faceCenters = [];

    this.setProgress(5);
    this.setStatus('Analysing camera frames…');

    while (performance.now() - start < DURATION_MS) {
      if (!this.isVerifying) return this._finish(startBtn);

      if (this.video.readyState >= 2) {
        ctx.drawImage(this.video, 0, 0, w, h);
        const gray = this._grayscaleFrame(ctx, w, h);
        frames++;

        // Motion energy
        if (prevGray) {
          let diff = 0;
          let cx = 0;
          let cxWeight = 0;
          for (let p = 0; p < gray.length; p++) {
            const d = Math.abs(gray[p] - prevGray[p]);
            diff += d;
            const x = p % w;
            cx += x * d;
            cxWeight += d;
          }
          const motion = diff / gray.length;
          motionSum += motion;
          motionSamples++;
          if (cxWeight > 0.001) centroids.push((cx / cxWeight) / w);
        }
        prevGray = gray;

        // Eye-region brightness (upper-middle band)
        const eye = this._regionMean(gray, w, h, w * 0.3 | 0, h * 0.3 | 0, w * 0.7 | 0, h * 0.55 | 0);
        eyeBaselineSum += eye;
        if (eye < eyeMin) eyeMin = eye;
        eyeLast = eye;

        // Native face detection (when available)
        if (this.faceDetector) {
          try {
            const faces = await this.faceDetector.detect(this.video);
            if (faces.length) {
              faceFrames++;
              const box = faces[0].boundingBox;
              const center = (box.x + box.width / 2) / (this.video.videoWidth || w);
              faceCenters.push(1 - center); // mirror to match the selfie preview
            }
          } catch (e) { /* detector hiccup - ignore this frame */ }
        }
      }

      const elapsed = performance.now() - start;
      this.setProgress(5 + (elapsed / DURATION_MS) * 90);
      this.setMetrics(`frames ${frames} · motion ${(motionSamples ? motionSum / motionSamples : 0).toFixed(3)}`);
      await new Promise((r) => setTimeout(r, 55));
    }

    // ---- Compose metrics ----
    const motionEnergy = motionSamples ? motionSum / motionSamples : 0;
    const eyeBaseline = frames ? eyeBaselineSum / frames : 0;
    const closure = eyeBaseline > 0 ? Math.max(0, (eyeBaseline - eyeMin) / eyeBaseline) : 0;
    const recovered = eyeBaseline > 0 ? eyeLast > eyeBaseline * 0.85 : false;
    const blinkDetected = closure > 0.05 && closure < 0.95 && recovered;

    let horizontalShift = 0;
    const track = faceCenters.length > 5 ? faceCenters : centroids;
    if (track.length > 5) {
      const third = Math.max(1, Math.floor(track.length / 3));
      const avg = (a) => a.reduce((s, v) => s + v, 0) / a.length;
      horizontalShift = avg(track.slice(-third)) - avg(track.slice(0, third));
    }

    const metrics = {
      face_detected_frames: this.faceDetector ? faceFrames : frames,
      duration_ms: Math.round(performance.now() - start),
      motion_energy: Number(motionEnergy.toFixed(4)),
      blink_detected: blinkDetected,
      eye_closure_ratio: Number(closure.toFixed(3)),
      horizontal_shift: Number(horizontalShift.toFixed(4)),
      frames_analyzed: frames,
    };

    this.setProgress(98);
    this.setStatus('Verifying with the server…');

    try {
      const resp = await fetch('/api/biometrics/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: this.session ? this.session.session_id : '',
          nonce: this.session ? this.session.nonce : null,
          claimed_patron_id: patronId,
          metrics,
        }),
      });
      const res = await resp.json();

      if (res.authenticated) {
        this.setProgress(100);
        this.setStatus(`Liveness verified (${res.liveness || 'metrics accepted'})`);
        setTimeout(() => {
          this.closeLivenessModal();
          window.kioskApp.authenticatePatron(res.patron_id);
        }, 900);
      } else {
        this.setStatus(res.error || 'Liveness check failed.', true);
        this.setProgress(0);
        // Request a fresh challenge for the next attempt.
        await this._renewChallenge();
      }
    } catch (e) {
      this.setStatus('Verification request failed.', true);
    }

    this._finish(startBtn);
  }

  async _renewChallenge() {
    try {
      const resp = await fetch('/api/biometrics/challenge', { method: 'POST' });
      this.session = await resp.json();
      const inst = document.getElementById('liveness-challenge-text');
      if (inst) inst.innerHTML = `<i class="fas fa-face-smile"></i> ${this.session.instruction}`;
    } catch (e) { /* ignore */ }
  }

  _finish(startBtn) {
    this.isVerifying = false;
    const btn = startBtn || document.getElementById('liveness-start-btn');
    if (btn) btn.disabled = false;
  }
}

window.faceLiveness = new FaceLivenessController();
