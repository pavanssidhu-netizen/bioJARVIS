import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.status, this.code, this.message);
  final int status;
  final String code;
  final String message;
  @override
  String toString() => '$code ($status): $message';
}

typedef Json = Map<String, dynamic>;

/// Thin typed-ish wrapper over the LABMATE REST API (see docs/API_CONTRACTS.md).
/// Same-origin: on Vercel the deployment-protection cookie is sent automatically.
class LabmateApi {
  LabmateApi({required this.baseUrl, http.Client? client, String? sessionId})
      : _http = client ?? http.Client(),
        sessionId = sessionId ?? _newSessionId();
  final String baseUrl;
  final http.Client _http;

  /// Per page-load id sent as x-labmate-session: groups this device's telemetry into one Langfuse session.
  final String sessionId;

  static String _newSessionId() {
    final r = Random.secure();
    return 'web-${List.generate(16, (_) => r.nextInt(36).toRadixString(36)).join()}';
  }

  Uri _u(String path, [Map<String, String>? q]) => Uri.parse('$baseUrl/api$path').replace(queryParameters: q);

  Future<dynamic> _send(String method, String path, {Object? body, Map<String, String>? query}) async {
    final req = http.Request(method, _u(path, query));
    req.headers['x-labmate-session'] = sessionId;
    if (body != null) {
      req.headers['content-type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(seconds: 60)));
    final text = res.body;
    dynamic data;
    try {
      data = text.isEmpty ? null : jsonDecode(text);
    } catch (_) {
      data = null;
    }
    if (res.statusCode >= 400) {
      final m = data is Map ? data : const {};
      throw ApiException(res.statusCode, '${m['error'] ?? 'http_${res.statusCode}'}',
          '${m['message'] ?? (text.length > 200 ? text.substring(0, 200) : text)}');
    }
    return data;
  }

  Future<Json> health() async => (await _send('GET', '/health')) as Json;
  Future<Json> capabilities() async => (await _send('GET', '/capabilities')) as Json;
  Future<List<dynamic>> experiments() async => (await _send('GET', '/experiments')) as List<dynamic>;
  Future<Json> startRecording(String experimentId) async =>
      (await _send('POST', '/recordings/start', body: {'experiment_id': experimentId})) as Json;
  Future<Json> stopRecording(String id, String reason) async =>
      (await _send('POST', '/recordings/$id/stop', body: {'reason': reason})) as Json;
  Future<Json> heartbeat(String id) async => (await _send('POST', '/recordings/$id/heartbeat')) as Json;
  Future<Json> pollEvents(String experimentId, int afterSeq) async =>
      (await _send('GET', '/events/$experimentId', query: {'after_seq': '$afterSeq'})) as Json;
  Future<List<dynamic>> observations(String experimentId) async =>
      (await _send('GET', '/observations', query: {'experiment_id': experimentId, 'limit': '500'})) as List<dynamic>;
  Future<Json> propose(Json event) async => (await _send('POST', '/observations/propose', body: event)) as Json;
  Future<Json> review(String id, String action, {Json? correction, String? reviewer}) async =>
      (await _send('POST', '/observations/$id/review',
          body: {'action': action, 'correction': correction, 'reviewer': reviewer})) as Json;
  Future<Json> vision(Json body) async => (await _send('POST', '/vision/analyse', body: body)) as Json;
  Future<Json> perceptionWindow(Json body) async => (await _send('POST', '/perception/window', body: body)) as Json;
  Future<Json> query(String experimentId, String question) async =>
      (await _send('POST', '/query', body: {'experiment_id': experimentId, 'question': question})) as Json;
  Future<Json> liveToken(String experimentId) async =>
      (await _send('POST', '/live/token', query: {'experiment_id': experimentId})) as Json;
  Future<Json> toolCall(Json body) async => (await _send('POST', '/tools/call', body: body)) as Json;
  Future<Json> route(String experimentId, String? sessionId, String text, String source, String utteranceId) async =>
      (await _send('POST', '/route', body: {
        'experiment_id': experimentId, 'session_id': sessionId, 'text': text, 'source': source, 'utterance_id': utteranceId,
      })) as Json;
  Future<Json?> protocol(String experimentId) async => (await _send('GET', '/experiments/$experimentId/protocol')) as Json?;
  Future<void> uiActions(String experimentId, String? recordingId, List<Json> actions) async => _send('POST', '/ui/actions',
      body: {'experiment_id': experimentId, 'recording_session_id': recordingId, 'actions': actions});
  Future<Json> telemetrySummary(int minutes) async =>
      (await _send('GET', '/telemetry/summary', query: {'minutes': '$minutes'})) as Json;

  String stopUrl(String recordingId) => '$baseUrl/api/recordings/$recordingId/stop';
}
