import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';
import 'dart:ui_web' as ui_web;

import 'package:web/web.dart' as web;

import 'platform_api.dart';

@JS('LabmateMedia')
external _LM get _lm;

extension type _LM(JSObject _) implements JSObject {
  external JSAny? unlockAudio();
  external void playPcm(JSString b64, JSNumber rate);
  external void stopPlayback();
  external JSPromise<JSAny?> micStart(JSFunction onChunk, JSFunction onLevel);
  external void micStop();
  external JSBoolean micActive();
  external void attachVideo(web.HTMLVideoElement el);
  external JSPromise<JSAny?> cameraOpen(JSString facing);
  external void cameraClose();
  external JSBoolean cameraActive();
  external JSString cameraTrackStates();
  external JSPromise<JSBoolean> hasMultipleCameras();
  external JSString? captureFrame(JSNumber maxWidth, JSNumber quality);
  external JSNumber videoAspect();
  external JSPromise<JSString> permission(JSString name);
  external void pickImage(JSFunction onPicked);
  external void downloadJson(JSString filename, JSString text);
  external JSBoolean beacon(JSString url);
  external void onPageHide(JSFunction cb);
  external void stopAll();
}

const cameraViewType = 'labmate-camera-preview';
bool _registered = false;

/// Registers the <video> element Flutter embeds via HtmlElementView(viewType: cameraViewType).
void registerCameraView() {
  if (_registered) return;
  _registered = true;
  ui_web.platformViewRegistry.registerViewFactory(cameraViewType, (int id) {
    final v = web.HTMLVideoElement()
      ..autoplay = true
      ..muted = true
      ..setAttribute('playsinline', 'true') // required on iOS to avoid fullscreen takeover
      ..style.width = '100%'
      ..style.height = '100%'
      ..style.objectFit = 'contain'
      ..style.backgroundColor = '#000';
    _lm.attachVideo(v);
    return v;
  });
}

class WebMediaBridge implements MediaBridge {
  @override
  void unlockAudio() => _lm.unlockAudio();
  @override
  void playPcm(String b64, int rate) => _lm.playPcm(b64.toJS, rate.toJS);
  @override
  void stopPlayback() => _lm.stopPlayback();

  @override
  Future<void> micStart(void Function(String) onChunk, void Function(double) onLevel) async {
    await _lm
        .micStart(((JSString s) => onChunk(s.toDart)).toJS, ((JSNumber n) => onLevel(n.toDartDouble)).toJS)
        .toDart;
  }

  @override
  void micStop() => _lm.micStop();
  @override
  bool micActive() => _lm.micActive().toDart;
  @override
  Future<void> cameraOpen(String facing) async => _lm.cameraOpen(facing.toJS).toDart;
  @override
  void cameraClose() => _lm.cameraClose();
  @override
  bool cameraActive() => _lm.cameraActive().toDart;
  @override
  String cameraTrackStates() => _lm.cameraTrackStates().toDart;
  @override
  Future<bool> hasMultipleCameras() async => (await _lm.hasMultipleCameras().toDart).toDart;
  @override
  String? captureFrame(int maxWidth, double quality) => _lm.captureFrame(maxWidth.toJS, quality.toJS)?.toDart;
  @override
  double videoAspect() => _lm.videoAspect().toDartDouble;
  @override
  Future<String> permission(String name) async => (await _lm.permission(name.toJS).toDart).toDart;
  @override
  void pickImage(void Function(String) onPicked) => _lm.pickImage(((JSString s) => onPicked(s.toDart)).toJS);
  @override
  void downloadJson(String filename, String text) => _lm.downloadJson(filename.toJS, text.toJS);
  @override
  bool beacon(String url) => _lm.beacon(url.toJS).toDart;
  @override
  void onPageHide(void Function() cb) => _lm.onPageHide(cb.toJS);
  @override
  void stopAll() => _lm.stopAll();
}

class _WebLiveSocket implements LiveSocket {
  _WebLiveSocket(this._ws);
  final web.WebSocket _ws;
  @override
  void send(String data) {
    if (_ws.readyState == web.WebSocket.OPEN) _ws.send(data.toJS);
  }

  @override
  void close([int code = 1000, String reason = '']) => _ws.close(code, reason);
}

LiveSocket webLiveSocketFactory(String url,
    {required void Function() onOpen,
    required void Function(String) onMessage,
    required void Function(int, String) onClose}) {
  final ws = web.WebSocket(url)..binaryType = 'arraybuffer';
  ws.onopen = ((web.Event _) => onOpen()).toJS;
  ws.onmessage = ((web.MessageEvent e) {
    final d = e.data;
    if (d.isA<JSString>()) {
      onMessage((d as JSString).toDart);
    } else if (d.isA<JSArrayBuffer>()) {
      // Gemini Live sends JSON frames as binary messages.
      onMessage(utf8.decode((d as JSArrayBuffer).toDart.asUint8List()));
    }
  }).toJS;
  ws.onclose = ((web.CloseEvent e) => onClose(e.code, e.reason)).toJS;
  return _WebLiveSocket(ws);
}

String currentOrigin() => web.window.location.origin;
