"""
NFSU Central Library Self-Service Kiosk - Facial Liveness Engine
National Forensic Sciences University, Gandhinagar
Integrated with Koha 26 ILMS (PS-2)

Server side of the challenge-response liveness flow.  The **browser** performs
the real work: it captures camera frames, measures eye-region closure and
horizontal face drift, and submits the measurements together with the
one-time nonce it was issued.  This module only *validates* those
measurements against per-challenge thresholds - it never trusts a bare
"challenge_passed: true" flag and it never invents a confidence score.

Privacy mandate: nothing biometric is written to disk.  Sessions live only in
volatile RAM and are destroyed the moment they are consumed or expire.
"""

import random
import time
from datetime import datetime
from typing import Any, Dict, Optional

from .config import settings

# Per-challenge acceptance thresholds.  All measurements come from the client
# but they are bounded so a static photo or a blank frame cannot pass.
_MIN_FRAMES = 15
_MIN_DURATION_MS = 800
_MAX_DURATION_MS = settings.LIVENESS_CHALLENGE_TIMEOUT * 1000
_MIN_MOTION_ENERGY = 0.008
_MIN_TURN_SHIFT = 0.06

CHALLENGES = [
    {
        "id": "blink",
        "instruction": "Look at the camera and blink both eyes once",
        "steps": ["BLINK"],
        "requires": {"blink": True},
    },
    {
        "id": "turn_left",
        "instruction": "Slowly turn your head to your left, then back to centre",
        "steps": ["TURN_LEFT"],
        "requires": {"turn": "left"},
    },
    {
        "id": "turn_right",
        "instruction": "Slowly turn your head to your right, then back to centre",
        "steps": ["TURN_RIGHT"],
        "requires": {"turn": "right"},
    },
    {
        "id": "blink_and_turn",
        "instruction": "Blink once and then turn your head to one side",
        "steps": ["BLINK", "TURN"],
        "requires": {"blink": True, "turn": "either"},
    },
]


def _challenge_by_id(challenge_id: str) -> Dict[str, Any]:
    for challenge in CHALLENGES:
        if challenge["id"] == challenge_id:
            return challenge
    return CHALLENGES[0]


class BiometricLivenessEngine:
    """Ephemeral, RAM-only liveness challenge manager."""

    # Expose the catalogue on the instance for telemetry/tests.
    CHALLENGES = CHALLENGES

    def __init__(self):
        self.active_challenges: Dict[str, Dict[str, Any]] = {}
        self._purge()

    # ------------------------------------------------------------------
    def _purge(self) -> None:
        now = time.time()
        for sid in [s for s, r in self.active_challenges.items() if r["expires_at"] < now]:
            self.active_challenges.pop(sid, None)

    def create_liveness_challenge(self) -> Dict[str, Any]:
        self._purge()
        challenge = random.choice(CHALLENGES)
        session_id = f"live_{int(time.time() * 1000)}_{random.randint(0x1000, 0xFFFF):04X}"
        nonce = f"{random.getrandbits(64):016X}"
        now = time.time()

        self.active_challenges[session_id] = {
            "session_id": session_id,
            "challenge_id": challenge["id"],
            "challenge": challenge,
            "nonce": nonce,
            "created_at": now,
            "expires_at": now + settings.LIVENESS_CHALLENGE_TIMEOUT,
            "used": False,
        }

        return {
            "session_id": session_id,
            "nonce": nonce,
            "challenge_id": challenge["id"],
            "instruction": challenge["instruction"],
            "steps": challenge["steps"],
            "timeout_seconds": settings.LIVENESS_CHALLENGE_TIMEOUT,
            "zero_retention_badge": (
                "Zero biometric retention: camera frames are analysed in the "
                "browser and discarded; only anonymous motion metrics are sent."
            ),
        }

    # ------------------------------------------------------------------
    def verify_liveness_and_authenticate(
        self,
        session_id: str,
        challenge_passed: bool = False,
        claimed_patron_id: Optional[str] = None,
        nonce: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Validate a completed liveness challenge.

        All measurements are cross-checked against the challenge that was
        issued.  A successful result is only returned when the numbers are
        physically plausible - there is no fallback that authenticates on a
        bare boolean.
        """
        self._purge()
        record = self.active_challenges.get(session_id)
        if not record:
            return {"authenticated": False, "error": "Liveness session not found or expired"}

        if record["used"]:
            return {"authenticated": False, "error": "Liveness session already consumed"}

        if time.time() > record["expires_at"]:
            self.active_challenges.pop(session_id, None)
            return {"authenticated": False, "error": "Liveness challenge timed out"}

        if nonce is not None and nonce != record["nonce"]:
            return {"authenticated": False, "error": "Invalid liveness nonce"}

        try:
            verdict = self._evaluate_metrics(record["challenge"], metrics or {})
        except Exception as exc:  # malformed payload
            return {"authenticated": False, "error": f"Invalid liveness payload: {exc}"}

        if not verdict["ok"]:
            return {"authenticated": False, "error": verdict["reason"]}

        if not claimed_patron_id:
            return {"authenticated": False, "error": "No patron identity to bind the face check to"}

        # Consume the session immediately (single use).
        record["used"] = True
        self.active_challenges.pop(session_id, None)

        return {
            "authenticated": True,
            "patron_id": claimed_patron_id,
            "challenge_id": record["challenge_id"],
            "liveness": verdict["summary"],
            "zero_retention_badge": (
                "Zero biometric retention: frames processed in volatile RAM and purged"
            ),
            "timestamp": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _evaluate_metrics(challenge: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
        frames = int(metrics.get("face_detected_frames", 0) or 0)
        duration = int(metrics.get("duration_ms", 0) or 0)
        motion = float(metrics.get("motion_energy", 0.0) or 0.0)
        blink = bool(metrics.get("blink_detected", False))
        closure = float(metrics.get("eye_closure_ratio", 0.0) or 0.0)
        shift = float(metrics.get("horizontal_shift", 0.0) or 0.0)

        if frames < _MIN_FRAMES:
            return {"ok": False, "reason": "Face was not detected for long enough"}
        if not (_MIN_DURATION_MS <= duration <= _MAX_DURATION_MS):
            return {"ok": False, "reason": "Liveness challenge duration outside the accepted range"}
        if motion < _MIN_MOTION_ENERGY:
            return {"ok": False, "reason": "No live movement detected (possible static photo)"}

        requires = challenge.get("requires", {})
        if requires.get("blink") and not (blink and 0.03 <= closure <= 0.95):
            return {"ok": False, "reason": "Blink not detected"}
        turn = requires.get("turn")
        if turn == "left" and shift > -_MIN_TURN_SHIFT:
            return {"ok": False, "reason": "Head turn to the left not detected"}
        if turn == "right" and shift < _MIN_TURN_SHIFT:
            return {"ok": False, "reason": "Head turn to the right not detected"}
        if turn == "either" and abs(shift) < _MIN_TURN_SHIFT:
            return {"ok": False, "reason": "No head turn detected"}

        return {
            "ok": True,
            "summary": (
                f"frames={frames}, duration={duration}ms, "
                f"motion={motion:.3f}, blink={blink}, closure={closure:.2f}, shift={shift:+.3f}"
            ),
        }


# Singleton instance
biometrics = BiometricLivenessEngine()
