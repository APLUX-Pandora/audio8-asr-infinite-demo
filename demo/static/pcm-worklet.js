// SPDX-License-Identifier: Apache-2.0
// Adapted from Edge0-AI/Audio8-ASR-Infinite client/pcm-worklet.js.
// APLUX modified the resampling and added multichannel input, reset, and end-of-stream flushing.

// Audio capture of the demo page: the page's sound (any rate, any channel count) to 16 kHz mono PCM16, posted in fixed
// chunks (default 1600 samples = 100 ms).
//
// Average the channels, then low-pass filter when requested and downsampling.
// Interpolate at
// output positions derived from the total sample count so block boundaries do
// not affect timing. The AudioWorklet and ScriptProcessor use this same class.
//
// Pcm16Worklet adds an epoch: resetting changes the epoch, and each posted
// chunk carries it so the page can discard samples captured before a start or seek.
class Pcm16Resampler {
  constructor(srcRate, dstRate, chunkSamples, emit) {
    this.step = srcRate / dstRate;
    this.srcRate = srcRate;
    this.dstRate = dstRate;
    this.chunkSamples = chunkSamples;
    this.emit = emit;

    // Symmetric, DC-normalized Blackman-windowed sinc. Allow 12 output
    // samples of lookahead and leave a transition band below target Nyquist.
    const radius = this.step > 1 ? Math.ceil(12 * this.step) : 0;
    this.passthrough = Float64Array.of(1);
    this.filter = new Float64Array(2 * radius + 1);
    this.filter[0] = 1;
    if (radius) {
      const cutoff = 0.42 / this.step;
      let sum = 0;
      for (let k = -radius; k <= radius; k += 1) {
        const angle = 2 * Math.PI * cutoff * k;
        const phase = Math.PI * k / radius;
        const window = 0.42 + 0.5 * Math.cos(phase) + 0.08 * Math.cos(2 * phase);
        const weight = (k === 0 ? 2 * cutoff : Math.sin(angle) / (Math.PI * k)) * window;
        this.filter[k + radius] = weight;
        sum += weight;
      }
      for (let k = 0; k < this.filter.length; k += 1) this.filter[k] /= sum;
    }
    // The ring holds the windows around both interpolation neighbours.
    this.history = new Float64Array(this.filter.length + 1);
    this.reset();
  }

  reset(antialias = true) {
    this.activeFilter = antialias ? this.filter : this.passthrough;
    this.radius = (this.activeFilter.length - 1) / 2;
    this.outputCount = 0;
    this.sourceCount = 0;
    this.first = this.last = 0;
    this.chunk = new Int16Array(this.chunkSamples);
    this.fill = 0;
    this.finished = false;
  }

  sampleAt(index) {
    if (index < 0) return this.first;
    if (index >= this.sourceCount) return this.last;
    return this.history[index % this.history.length];
  }

  emitSample(pos) {
    const center = Math.floor(pos), fraction = pos - center;
    const left = center - this.radius;
    let value = 0, a = this.sampleAt(left);
    for (let k = 0; k < this.activeFilter.length; k += 1) {
      const b = this.sampleAt(left + k + 1);
      value += this.activeFilter[k] * (a + (b - a) * fraction);
      a = b;
    }
    const v = Math.max(-1, Math.min(1, value));
    this.chunk[this.fill++] = v < 0 ? v * 0x8000 : v * 0x7fff;
    this.outputCount += 1;
    if (this.fill === this.chunkSamples) {
      const buf = this.chunk.buffer;
      this.chunk = new Int16Array(this.chunkSamples);
      this.fill = 0;
      this.emit(buf);
    }
  }

  push(channels) {
    if (this.finished || !channels.length) return;
    let pos = this.outputCount * this.step;
    for (let i = 0; i < channels[0].length; i += 1) {
      let mono = 0;
      for (const channel of channels) mono += channel[i];
      mono /= channels.length;
      if (this.sourceCount === 0) this.first = mono;
      this.last = mono;
      this.history[this.sourceCount % this.history.length] = mono;
      this.sourceCount += 1;
      while (Math.floor(pos) + this.radius + 1 < this.sourceCount) {
        this.emitSample(pos);
        pos = this.outputCount * this.step;
      }
    }
  }

  flush() {
    if (this.finished) return;
    this.finished = true;
    // Extend the endpoint only for filtering and interpolation. Keep the
    // output length tied to the captured source duration.
    const targetCount = Math.ceil(this.sourceCount * this.dstRate / this.srcRate);
    while (this.outputCount < targetCount) this.emitSample(this.outputCount * this.step);
    if (this.fill) {
      this.emit(this.chunk.slice(0, this.fill).buffer);
      this.fill = 0;
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
          this.resampler.reset(e.data.antialias);
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
