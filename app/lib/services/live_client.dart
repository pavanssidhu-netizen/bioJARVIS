import 'dart:convert';

import 'platform_api.dart';

/// Gemini Live over a raw WebSocket using a short-lived, config-locked token from our backend.
/// Model, system prompt and tools are locked server-side in the token; the client only sends `model`
/// (+ resumption handle). Protocol: https://ai.google.dev/api/live
class LiveClient {
  LiveClient({
    required this.socketFactory,
    required this.onSetupComplete,
    required this.onAudio,
    required this.onInputTranscript,
    required this.onOutputTranscript,
    required this.onTurnComplete,
    required this.onInterrupted,
    required this.onToolCall,
    required this.onClosed,
    required this.onGoAway,
  });

  final LiveSocketFactory socketFactory;
  final void Function() onSetupComplete;
  final void Function(String b64, int rate) onAudio;
  final void Function(String text) onInputTranscript;
  final void Function(String text) onOutputTranscript;
  final void Function() onTurnComplete;
  final void Function() onInterrupted;
  final void Function(List<Map<String, dynamic>> calls) onToolCall;
  final void Function(int code, String reason) onClosed;
  final void Function() onGoAway;

  LiveSocket? _ws;
  bool _ready = false;
  String? resumptionHandle;
  bool get ready => _ready;

  void connect({required String websocketUrl, required String token, required String model}) {
    _ready = false;
    final url = '$websocketUrl?access_token=${Uri.encodeQueryComponent(token)}';
    _ws = socketFactory(url, onOpen: () {
      final setup = <String, dynamic>{'model': 'models/$model'};
      if (resumptionHandle != null) setup['sessionResumption'] = {'handle': resumptionHandle};
      _ws?.send(jsonEncode({'setup': setup}));
    }, onMessage: _handle, onClose: (code, reason) {
      _ready = false;
      _ws = null;
      onClosed(code, reason);
    });
  }

  void _handle(String raw) {
    final Map<String, dynamic> m;
    try {
      m = jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    if (m.containsKey('setupComplete')) {
      _ready = true;
      onSetupComplete();
    }
    final sc = m['serverContent'] as Map<String, dynamic>?;
    if (sc != null) {
      if (sc['interrupted'] == true) onInterrupted();
      final parts = (sc['modelTurn']?['parts'] as List?) ?? const [];
      for (final p in parts) {
        final inline = (p as Map)['inlineData'] as Map?;
        if (inline != null && '${inline['mimeType']}'.startsWith('audio/pcm')) {
          final rate = RegExp(r'rate=(\d+)').firstMatch('${inline['mimeType']}')?.group(1);
          onAudio('${inline['data']}', int.tryParse(rate ?? '') ?? 24000);
        }
      }
      final it = sc['inputTranscription']?['text'];
      if (it is String && it.isNotEmpty) onInputTranscript(it);
      final ot = sc['outputTranscription']?['text'];
      if (ot is String && ot.isNotEmpty) onOutputTranscript(ot);
      if (sc['turnComplete'] == true) onTurnComplete();
    }
    final tc = m['toolCall'] as Map<String, dynamic>?;
    if (tc != null) {
      onToolCall(((tc['functionCalls'] as List?) ?? const []).cast<Map<String, dynamic>>());
    }
    final sr = m['sessionResumptionUpdate'] as Map<String, dynamic>?;
    if (sr != null && sr['resumable'] == true && sr['newHandle'] is String) resumptionHandle = sr['newHandle'] as String;
    if (m.containsKey('goAway')) onGoAway();
  }

  void sendAudio(String b64) => _send({
        'realtimeInput': {'audio': {'data': b64, 'mimeType': 'audio/pcm;rate=16000'}}
      });

  void sendAudioStreamEnd() => _send({'realtimeInput': {'audioStreamEnd': true}});

  void sendVideoFrame(String jpegB64) => _send({
        'realtimeInput': {'video': {'data': jpegB64, 'mimeType': 'image/jpeg'}}
      });

  void sendText(String text) => _send({'realtimeInput': {'text': text}});

  /// Adds context (e.g. a snapshot analysis result) without forcing a reply.
  void addContext(String text) => _send({
        'clientContent': {
          'turns': [
            {'role': 'user', 'parts': [{'text': text}]}
          ],
          'turnComplete': false
        }
      });

  void sendToolResponses(List<Map<String, dynamic>> responses) =>
      _send({'toolResponse': {'functionResponses': responses}});

  void _send(Map<String, dynamic> msg) {
    if (_ready) _ws?.send(jsonEncode(msg));
  }

  void close() {
    _ready = false;
    _ws?.close(1000, 'client_disconnect');
    _ws = null;
  }
}
