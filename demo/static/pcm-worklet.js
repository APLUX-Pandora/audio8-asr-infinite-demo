// SPDX-License-Identifier: Apache-2.0
// Adapted from Edge0-AI/Audio8-ASR-Infinite client/pcm-worklet.js.
// APLUX modified the resampling and added multichannel input, reset, and end-of-stream flushing.

// Audio capture of the demo page: the page's sound (any rate, any channel count) to 16 kHz mono PCM16, posted in fixed
// chunks (default 1600 samples = 100 ms).
//
// Pcm16Resampler: streaming linear interpolation. Output sample j is taken at source position j * srcRate / dstRate
// (computed from j, so the rate never drifts), between the two source samples around it; channels are averaged first.
// Used twice: by the AudioWorklet below and, where AudioWorklet is missing (plain http pages), by the page's
// ScriptProcessorNode fallback (index.html loads this file as a script too).
//
// Pcm16Worklet: the AudioWorklet around it, plus an epoch: port.postMessage({epoch}) restarts the resampler, and every
// chunk is posted as {epoch, buffer} so the page can drop audio captured before a start or a seek.
class Pcm16Resampler {
  constructor(srcRate, dstRate, chunkSamples, emit) {
    this.step = srcRate / dstRate;
    this.srcRate = srcRate;
    this.dstRate = dstRate;
    this.chunkSamples = chunkSamples;
    this.emit = emit;                    // emit(ArrayBuffer of chunkSamples PCM16 samples)
    this.reset();
  }

  reset() {
    this.j = 0;                          // index of the next output sample
    this.base = 0;                       // source index of the first sample of the next block
    this.last = 0;                       // source sample base - 1
    this.chunk = new Int16Array(this.chunkSamples);
    this.fill = 0;
    this.finished = false;
  }

  push(channels) {
    if (this.finished) return;
    const n = channels[0].length;
    if (!n) return;
    const mono = new Float64Array(n);
    for (const ch of channels) {
      for (let i = 0; i < n; i += 1) mono[i] += ch[i];
    }
    if (channels.length > 1) {
      for (let i = 0; i < n; i += 1) mono[i] /= channels.length;
    }
    const at = (k) => (k < this.base ? this.last : mono[k - this.base]);
    const end = this.base + n;           // source samples available: [base - 1, end)
    for (;;) {
      const pos = this.j * this.step;
      const k = Math.floor(pos);
      if (k + 1 >= end) break;           // the right neighbour is not here yet
      const a = at(k);
      const v = Math.max(-1, Math.min(1, a + (at(k + 1) - a) * (pos - k)));
      this.chunk[this.fill] = v < 0 ? v * 0x8000 : v * 0x7fff;
      this.fill += 1;
      this.j += 1;
      if (this.fill === this.chunkSamples) {
        const buf = this.chunk.buffer;
        this.chunk = new Int16Array(this.chunkSamples);
        this.fill = 0;
        this.emit(buf);
      }
    }
    this.last = mono[n - 1];
    this.base = end;
  }

  flush() {
    if (this.finished) return;
    this.finished = true;
    // At EOF there is no right interpolation neighbour. Hold the final sample
    // for the remaining source duration; do not add a whole synthetic chunk.
    const targetCount = Math.ceil(this.base * this.dstRate / this.srcRate);
    const v = Math.max(-1, Math.min(1, this.last));
    while (this.j < targetCount) {
      this.chunk[this.fill++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      this.j++;
      if (this.fill === this.chunkSamples) {
        const buf = this.chunk.buffer;
        this.chunk = new Int16Array(this.chunkSamples); this.fill = 0;
        this.emit(buf);
      }
    }
    if (this.fill) {
      this.emit(this.chunk.slice(0, this.fill).buffer);
      this.chunk = new Int16Array(this.chunkSamples); this.fill = 0;
    }
  }
}

if (typeof AudioWorkletProcessor !== "undefined") {
  class Pcm16Worklet extends AudioWorkletProcessor {
    constructor(options) {
      super();
      const o = options.processorOptions || {};
      this.epoch = 0;
      this.resampler = new Pcm16Resampler(o.sourceSampleRate || sampleRate, o.targetSampleRate || 16000,
        o.chunkSamples || 1600, (buf) => this.port.postMessage({ epoch: this.epoch, buffer: buf }, [buf]));
      this.port.onmessage = (e) => {
        if (e.data && e.data.command === "flush") {
          if (e.data.epoch === this.epoch) {
            this.resampler.flush();
            // Port ordering guarantees every audio buffer precedes its ack.
            this.port.postMessage({ epoch: this.epoch, flushed: true });
          }
        } else if (e.data && e.data.epoch !== undefined) {
          this.epoch = e.data.epoch;
          this.resampler.reset();
        }
      };
    }

    process(inputs) {
      const channels = inputs[0];
      if (channels && channels.length > 0 && channels[0].length > 0) this.resampler.push(channels);
      return true;
    }
  }
  registerProcessor("pcm16-worklet", Pcm16Worklet);
}
