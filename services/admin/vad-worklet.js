class ClaimPilotVad extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = new Float32Array(960);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) {
      return true;
    }
    let offset = 0;
    while (offset < channel.length) {
      const room = this.pending.length - this.filled;
      const take = Math.min(room, channel.length - offset);
      this.pending.set(channel.subarray(offset, offset + take), this.filled);
      this.filled += take;
      offset += take;
      if (this.filled === this.pending.length) {
        this.port.postMessage(this.pending.slice(0));
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("claimpilot-vad", ClaimPilotVad);
