// LABMATE browser media bridge. Called from Dart via dart:js_interop (lib/services/media_bridge_web.dart).
// Nothing here runs until the user presses a button: no getUserMedia on load, ever.
(function () {
  "use strict";

  // AudioWorklet: downsample mic input to 16 kHz mono Int16 PCM, emit ~100 ms chunks.
  const WORKLET_SRC = `
    class PcmDownsampler extends AudioWorkletProcessor {
      constructor() { super(); this.ratio = sampleRate / 16000; this.pos = 0; this.buf = new Int16Array(1600); this.n = 0; }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (!ch) return true;
        let sumSq = 0;
        for (; this.pos < ch.length; this.pos += this.ratio) {
          const s = Math.max(-1, Math.min(1, ch[Math.floor(this.pos)]));
          sumSq += s * s;
          this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
          if (this.n === this.buf.length) {
            this.port.postMessage({ pcm: this.buf.buffer, rms: Math.sqrt(sumSq / this.n) }, [this.buf.buffer]);
            this.buf = new Int16Array(1600); this.n = 0; sumSq = 0;
          }
        }
        this.pos -= ch.length;
        return true;
      }
    }
    registerProcessor('pcm-downsampler', PcmDownsampler);`;

  function bytesToB64(buf) {
    const bytes = new Uint8Array(buf);
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }

  const M = {
    _out: null, _next: 0, _sources: new Set(),
    _mic: null,           // {stream, ctx, node, src}
    _cam: null,           // {stream}
    _video: null,
    _lastCamTracks: [],

    // ---------- output audio (Gemini speech, 24 kHz PCM16) ----------
    // Must be called inside a user gesture (iOS/Safari autoplay rules).
    unlockAudio() {
      if (!this._out) this._out = new (window.AudioContext || window.webkitAudioContext)();
      if (this._out.state === "suspended") this._out.resume();
      // Play one silent sample so iOS fully unlocks the output path.
      const b = this._out.createBuffer(1, 1, 22050);
      const s = this._out.createBufferSource(); s.buffer = b; s.connect(this._out.destination); s.start(0);
      return this._out.state;
    },
    playPcm(b64, rate) {
      if (!this._out) return;
      const bin = atob(b64), n = bin.length >> 1;
      const buf = this._out.createBuffer(1, n, rate || 24000), ch = buf.getChannelData(0);
      for (let i = 0; i < n; i++) {
        let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
        if (v >= 0x8000) v -= 0x10000;
        ch[i] = v / 0x8000;
      }
      const src = this._out.createBufferSource();
      src.buffer = buf; src.connect(this._out.destination);
      const t = Math.max(this._out.currentTime + 0.03, this._next);
      src.start(t); this._next = t + buf.duration;
      this._sources.add(src); src.onended = () => this._sources.delete(src);
    },
    stopPlayback() { // barge-in: drop everything queued
      for (const s of this._sources) { try { s.stop(); } catch (e) {} }
      this._sources.clear();
      this._next = 0;
    },
    isPlaying() { return this._sources.size > 0; },

    // ---------- microphone ----------
    async micStart(onChunk, onLevel) {
      if (this._mic) return true;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
      // Reuse the context unlocked in the user gesture (iOS keeps contexts created later suspended).
      if (!this._out) this.unlockAudio();
      const ctx = this._out;
      if (!this._workletLoaded) {
        const url = URL.createObjectURL(new Blob([WORKLET_SRC], { type: "application/javascript" }));
        await ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        this._workletLoaded = true;
      }
      const src = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, "pcm-downsampler");
      node.port.onmessage = (e) => { onChunk(bytesToB64(e.data.pcm)); if (onLevel) onLevel(e.data.rms); };
      src.connect(node);
      // Keep the worklet in the rendering graph via a muted sink (some engines only pull connected nodes).
      const mute = ctx.createGain(); mute.gain.value = 0; node.connect(mute); mute.connect(ctx.destination);
      if (ctx.state === "suspended") await ctx.resume();
      this._mic = { stream, node, src, mute };
      return true;
    },
    micStop() {
      const m = this._mic; this._mic = null;
      if (!m) return;
      try { m.node.port.onmessage = null; m.src.disconnect(); m.node.disconnect(); m.mute.disconnect(); } catch (e) {}
      m.stream.getTracks().forEach((t) => t.stop());
    },
    micActive() { return !!(this._mic && this._mic.stream.getAudioTracks().some((t) => t.readyState === "live")); },

    // ---------- camera ----------
    attachVideo(el) { this._video = el; if (this._cam) el.srcObject = this._cam.stream; },
    async cameraOpen(facing) {
      if (this._cam) this.cameraClose();
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facing || "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
      this._cam = { stream };
      this._lastCamTracks = stream.getTracks();
      if (this._video) { this._video.srcObject = stream; try { await this._video.play(); } catch (e) {} }
      return true;
    },
    cameraClose() {
      const c = this._cam; this._cam = null;
      if (this._video) { this._video.pause(); this._video.srcObject = null; }
      if (c) c.stream.getTracks().forEach((t) => t.stop());
    },
    cameraActive() { return !!(this._cam && this._cam.stream.getVideoTracks().some((t) => t.readyState === "live")); },
    // For tests/diagnostics: readyState of every track the last camera session opened ("ended" after close).
    cameraTrackStates() { return this._lastCamTracks.map((t) => t.readyState).join(","); },
    async hasMultipleCameras() {
      try { return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput").length > 1; }
      catch (e) { return false; }
    },
    videoAspect() { const v = this._video; return v && v.videoWidth ? v.videoWidth / v.videoHeight : 0; },
    captureFrame(maxWidth, quality) {
      const v = this._video;
      if (!this.cameraActive() || !v || !v.videoWidth) return null;
      const scale = Math.min(1, maxWidth / v.videoWidth);
      const c = document.createElement("canvas");
      c.width = Math.round(v.videoWidth * scale); c.height = Math.round(v.videoHeight * scale);
      c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
      return c.toDataURL("image/jpeg", quality).split(",")[1];
    },

    // ---------- misc ----------
    async permission(name) {
      try { return (await navigator.permissions.query({ name })).state; } catch (e) { return "unknown"; }
    },
    pickImage(onPicked) { // file upload -> downscaled JPEG base64
      const input = document.createElement("input");
      input.type = "file"; input.accept = "image/*";
      input.onchange = () => {
        const f = input.files && input.files[0]; if (!f) return;
        const img = new Image();
        img.onload = () => {
          const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
          const c = document.createElement("canvas");
          c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          URL.revokeObjectURL(img.src);
          onPicked(c.toDataURL("image/jpeg", 0.85).split(",")[1]);
        };
        img.src = URL.createObjectURL(f);
      };
      input.click();
    },
    downloadJson(filename, text) {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
      a.download = filename; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },
    beacon(url) { try { return navigator.sendBeacon(url); } catch (e) { return false; } },
    onPageHide(cb) { window.addEventListener("pagehide", () => cb()); },
    stopAll() { this.micStop(); this.cameraClose(); this.stopPlayback(); },
  };
  window.LabmateMedia = M;
})();
