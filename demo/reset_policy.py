"""Bounded, per-recording audio recovery for the Web Demo."""

from collections import deque

import numpy as np


class ResetPolicy:
    """After a quiet gap, give the current stream time to resume before replaying."""

    QUIET_S = 1.76
    NO_TEXT_S = 6.0
    WAIT_S = 1.28
    ACTIVE_POWER = 1e-5
    LEAD_POWER = 1e-7

    def __init__(self, rate, window, *, roll_s):
        self.rate = rate
        self.window = window
        self.roll_samples = round(roll_s * rate)
        self.resume_at = self.roll_samples
        self.block = rate // 50  # 20 ms energy measurements
        self.quiet_samples = round(self.QUIET_S * rate)
        self.no_text_samples = round(self.NO_TEXT_S * rate)
        self.wait_samples = round(self.WAIT_S * rate)
        self.last_text_end = 0
        self.quiet = 0
        self.lead = None
        self.pending = []
        self.onset = 0
        self.varying = 0
        self.reset_count = 0
        self.resets = deque(maxlen=200)

    def observe(self, pcm, delta, end):
        """Process a window only after the original stream has seen it."""
        if delta.strip():
            self.last_text_end = end
            self.pending.clear()
            self.quiet = 0
            self.lead = None
            return None
        if not self.roll_samples or end <= self.resume_at or pcm.size != self.window:
            return None

        power = np.mean(pcm.reshape(-1, self.block) ** 2, axis=1)
        if power.mean() < self.ACTIVE_POWER:
            self.pending.clear()
            self.quiet = min(self.quiet + self.window, self.quiet_samples)
            self.lead = pcm.copy()
            return None
        if not self.pending:
            quiet, lead = self.quiet, self.lead
            self.quiet, self.lead = 0, None
            start = end - self.window
            if quiet < self.quiet_samples or start - self.last_text_end < self.no_text_samples:
                return None

            self.onset = start
            self.varying = 0
            # Keep a quiet lead-in and any initial low-energy sound in the
            # preceding window. All replay audio follows the last shown text.
            lead_power = np.mean(lead.reshape(-1, self.block) ** 2, axis=1)
            activity = np.flatnonzero(np.concatenate((lead_power, power)) >= self.LEAD_POWER)
            first = max(0, int(activity[0]) - 1) * self.block
            lead_in = np.concatenate((lead, pcm))[first:]
            self.pending.append(lead_in)
        else:
            self.pending.append(pcm.copy())

        # A knock will run out of active windows. Steady noise can be loud
        # throughout, so require energy to vary in multiple windows as well.
        self.varying += int(power.max() > 4 * power.min())
        if end - self.onset < self.wait_samples:
            return None
        buffered = self.pending
        self.pending = []
        return np.concatenate(buffered) if self.varying >= 2 else None

    def record(self, end, replay_samples):
        # The new stream must fill its own rolling context before rearming.
        self.resume_at = end - replay_samples + self.roll_samples
        self.reset_count += 1
        self.resets.append({
            "onset_s": round(self.onset / self.rate, 3),
            "audio_s": round(end / self.rate, 3),
            "replay_start_s": round((end - replay_samples) / self.rate, 3),
        })
        return self.resets[-1]
