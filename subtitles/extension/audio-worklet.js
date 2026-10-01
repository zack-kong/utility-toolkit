class VatPcm16Processor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0;
    this.ratio = sampleRate / 16000;
    this.output = [];
    this.targetSamples = 320; // 20 ms at 16 kHz
  }

  process(inputs) {
    const channels = inputs[0];
    const input = channels?.[0];
    if (!input) return true;
    const mono = (index) => {
      let sum = 0;
      for (const channel of channels) sum += channel[index];
      return sum / channels.length;
    };
    while (this.phase < input.length) {
      const index = Math.floor(this.phase);
      const fraction = this.phase - index;
      const next = Math.min(index + 1, input.length - 1);
      const value = Math.max(-1, Math.min(1,
        mono(index) * (1 - fraction) + mono(next) * fraction));
      this.output.push(value < 0 ? value * 32768 : value * 32767);
      this.phase += this.ratio;
      if (this.output.length === this.targetSamples) {
        const pcm = new Int16Array(this.output);
        this.port.postMessage(pcm.buffer, [pcm.buffer]);
        this.output = [];
      }
    }
    this.phase -= input.length;
    return true;
  }
}
registerProcessor("vat-pcm16", VatPcm16Processor);
