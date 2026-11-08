import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:labmate/services/api.dart';
import 'package:labmate/services/platform_api.dart';
import 'package:labmate/state/app_state.dart';

class FakeMedia implements MediaBridge {
  bool mic = false, cam = false, unlocked = false;
  List<String> camTracks = [];
  int micStarts = 0, camOpens = 0;
  void Function(String)? onChunk;
  @override
  void unlockAudio() => unlocked = true;
  int played = 0;
  @override
  void playPcm(String b64, int rate) => played++;
  @override
  void stopPlayback() {}
  @override
  Future<void> micStart(void Function(String) c, void Function(double) l) async {
    micStarts++;
    mic = true;
    onChunk = c;
  }

  @override
  void micStop() => mic = false;
  @override
  bool micActive() => mic;
  @override
  Future<void> cameraOpen(String facing) async {
    camOpens++;
    cam = true;
    camTracks = ['live'];
  }

  @override
  void cameraClose() {
    cam = false;
    camTracks = camTracks.map((_) => 'ended').toList();
  }

  @override
  bool cameraActive() => cam;
  @override
  String cameraTrackStates() => camTracks.join(',');
  @override
  Future<bool> hasMultipleCameras() async => false;
  @override
  String? captureFrame(int maxWidth, double quality) => cam ? base64Encode([0xff, 0xd8, 0xff, 1, 2, 3]) : null;
  @override
  double videoAspect() => 4 / 3;
  @override
  Future<String> permission(String name) async => 'prompt';
  @override
  void pickImage(void Function(String) onPicked) {}
  @override
  void downloadJson(String filename, String text) {}
  @override
  bool beacon(String url) => true;
  @override
  void onPageHide(void Function() cb) {}
  @override
  void stopAll() {
    mic = false;
    cam = false;
  }
}

class FakeApi extends LabmateApi {
  FakeApi() : super(baseUrl: 'http://test');
  Map<String, dynamic>? serverRecording; // backend truth
  final List<Map<String, dynamic>> proposed = [];
  int perceptionCalls = 0;

  Map<String, dynamic> _rec(String status) => {
        'id': 'rec-1', 'experiment_id': 'exp-demo', 'started_at': 't', 'stopped_at': null, 'status': status,
        'last_heartbeat_at': 't', 'event_count': 0,
      };
  @override
  Future<Json> health() async => {'status': 'ok', 'database_ok': true, 'database': 'x', 'last_db_write': null};
  @override
  Future<Json> capabilities() async => {'gemini_configured': true};
  @override
  Future<Json> pollEvents(String e, int after) async =>
      {'events': [], 'last_sequence': after, 'recording': serverRecording?['status'] == 'active' ? serverRecording : null};
  @override
  Future<Json> startRecording(String e) async => serverRecording = _rec('active');
  @override
  Future<Json> stopRecording(String id, String reason) async => serverRecording = _rec('stopped');
  @override
  Future<Json> heartbeat(String id) async => serverRecording!;
  @override
  Future<Json> liveToken(String e) async => {'token': 'tok', 'model': 'gemini-3.8-live', 'websocket_url': 'wss://x'};
  final List<Map<String, dynamic>> uiLog = [];
  @override
  Future<void> uiActions(String e, String? r, List<Json> actions) async => uiLog.addAll(actions);
  @override
  Future<Json?> protocol(String e) async => {
        'version': 1,
        'content': {
          'title': 'Demo',
          'steps': [
            {'id': 'S1', 'action': 'pipette buffer', 'description': 'Pipette 1 mL'},
            {'id': 'S2', 'action': 'dispense drop', 'description': 'Add 3 drops', 'quantity': 3, 'unit': 'drops'},
          ]
        }
      };
  @override
  Future<Json> telemetrySummary(int minutes) async => {'spans': 0, 'by_name': []};
  final List<Map<String, dynamic>> routed = [];
  @override
  Future<Json> route(String e, String? s, String text, String source, String id) async {
    routed.add({'text': text, 'source': source, 'session': s});
    if (text.toLowerCase().contains('shift key')) {
      return {'category': 'non_scientific', 'tool': 'none', 'stored': false, 'spoken': null};
    }
    return {'category': 'observation', 'tool': 'propose_observation', 'args': {'channel_id': 'CH01'},
            'ambiguous': false, 'stored': s != null, 'spoken': 'Logged: one bubble in CH01.', 'result': {'ok': true}};
  }
  @override
  Future<Json> propose(Json event) async {
    if (serverRecording?['status'] != 'active') throw ApiException(409, 'recording_inactive', 'no');
    proposed.add(event);
    return {
      'ok': true, 'saved': true,
      'event': {
        'id': 'evt-${proposed.length}', 'session_id': 'rec-1', 'experiment_id': 'exp-demo',
        'sequence_number': proposed.length, 'timestamp': DateTime.now().toUtc().toIso8601String(),
        'source_modality': 'speech', 'event_type': 'transcript_segment', 'payload': event['payload'],
        'model_name': 'm', 'status': 'persisted', 'idempotency_key': event['idempotency_key'],
        'source_event_id': null, 'review_status': 'pending', 'reviews': [],
      }
    };
  }

  @override
  Future<Json> perceptionWindow(Json body) async {
    perceptionCalls++;
    return {
      'perception': {'scene_summary': 'dropper', 'objects': [], 'actions': [{'action': 'dispense drop', 'count': 2, 'certainty': 'likely'}]},
      'saved': false, 'skipped_reason': 'no_change',
      'reconciliation': {
        'action': 'warn', 'requires_human_approval': true, 'step_id': 'step_05',
        'spoken_response': 'Possible bubble in CH01; the standard curve may need review.',
        'cross_check': {'gemini_count': 1, 'specialist_count': 1, 'agree': true},
      },
    };
  }

  @override
  Future<Json> toolCall(Json body) async {
    if (body['name'] == 'request_ui_action') {
      final a = (body['args'] as Map)['action'];
      if (a == 'start_recording') return {'ok': false, 'error': 'ui_action_not_allowed'};
      return {'ok': true, 'approved': true, 'ui_action': {'action': a, 'argument': (body['args'] as Map)['argument'] ?? ''}};
    }
    return {'ok': true, 'answer': '2 drops', 'echo': body};
  }
}

class FakeSocket implements LiveSocket {
  FakeSocket(this.onOpen, this.onMessage, this.onClose);
  final void Function() onOpen;
  final void Function(String) onMessage;
  final void Function(int, String) onClose;
  final List<Map<String, dynamic>> sent = [];
  @override
  void send(String data) => sent.add(jsonDecode(data) as Map<String, dynamic>);
  @override
  void close([int code = 1000, String reason = '']) => onClose(code, reason);
  void server(Map<String, dynamic> m) => onMessage(jsonEncode(m));
}

void main() {
  late FakeMedia media;
  late FakeApi api;
  FakeSocket? sock;
  late AppController c;

  setUp(() {
    media = FakeMedia();
    api = FakeApi();
    sock = null;
    c = AppController(
      api: api,
      media: media,
      socketFactory: (url, {required onOpen, required onMessage, required onClose}) {
        sock = FakeSocket(onOpen, onMessage, onClose);
        scheduleMicrotask(() {
          onOpen();
          sock!.server({'setupComplete': {}});
        });
        return sock!;
      },
      pollInterval: const Duration(hours: 1),
      perceptionFrameInterval: const Duration(milliseconds: 10),
      perceptionWindowFrames: 3,
    );
  });
  tearDown(() => c.dispose());

  test('everything is off by default and init acquires no media', () async {
    await c.init();
    expect(c.microphoneEnabled, isFalse);
    expect(c.cameraOpen, isFalse);
    expect(c.recordingActive, isFalse);
    expect(c.geminiConnected, isFalse);
    expect(c.cameraStreamingToGemini, isFalse);
    expect(media.micStarts, 0);
    expect(media.camOpens, 0);
    expect(c.appConnected, isTrue);
  });

  test('connecting Gemini does not enable the microphone', () async {
    await c.connectGemini();
    await Future<void>.delayed(Duration.zero);
    expect(c.geminiConnected, isTrue);
    expect(c.microphoneEnabled, isFalse);
    expect(media.micStarts, 0);
    expect(sock!.sent.first['setup']['model'], 'models/gemini-3.8-live');
  });

  test('close camera stops tracks and frame streaming', () async {
    await c.connectGemini();
    await Future<void>.delayed(Duration.zero);
    await c.openCamera();
    c.setCameraStreaming(true);
    expect(c.cameraOpen && c.cameraStreamingToGemini, isTrue);
    c.closeCamera();
    expect(c.cameraOpen, isFalse);
    expect(c.cameraStreamingToGemini, isFalse);
    expect(media.cameraTrackStates(), 'ended');
  });

  test('camera streaming refused unless camera open and Gemini connected', () async {
    await c.openCamera();
    c.setCameraStreaming(true);
    expect(c.cameraStreamingToGemini, isFalse);
  });

  test('recording state comes from the backend, including server-side expiry', () async {
    await c.init();
    await c.startRecording();
    expect(c.recordingActive, isTrue);
    api.serverRecording = null; // e.g. heartbeat timeout on the server
    await c.refreshDiagnostics();
    await c.stopRecording(); // still callable
    expect(c.recordingActive, isFalse);
  });

  test('speech is persisted only while recording', () async {
    await c.connectGemini();
    await Future<void>.delayed(Duration.zero);
    sock!.server({'serverContent': {'inputTranscription': {'text': 'hello there'}}});
    sock!.server({'serverContent': {'turnComplete': true}});
    await Future<void>.delayed(Duration.zero);
    expect(api.proposed, isEmpty);
    expect(c.feed.any((f) => f.sourceText == 'hello there' && f.persistence == Persistence.ephemeral), isTrue);

    await c.startRecording();
    sock!.server({'serverContent': {'inputTranscription': {'text': 'tube A turned blue'}}});
    sock!.server({'serverContent': {'turnComplete': true}});
    await Future<void>.delayed(const Duration(milliseconds: 5));
    expect(api.proposed.single['payload']['text'], 'tube A turned blue');
    expect(c.feed.firstWhere((f) => f.sourceText == 'tube A turned blue').persistence, Persistence.saved);
  });

  test('tool calls are relayed to the backend and answered to Gemini', () async {
    await c.connectGemini();
    await Future<void>.delayed(Duration.zero);
    sock!.server({
      'toolCall': {
        'functionCalls': [
          {'id': 'fc1', 'name': 'query_lab_log', 'args': {'question': 'how many drops?'}}
        ]
      }
    });
    await Future<void>.delayed(const Duration(milliseconds: 5));
    final resp = sock!.sent.lastWhere((m) => m.containsKey('toolResponse'));
    final fr = resp['toolResponse']['functionResponses'][0];
    expect(fr['id'], 'fc1');
    expect(fr['response']['answer'], '2 drops');
  });

  test('disconnect stops mic and recording; unexpected close does not leave mic streaming forever', () async {
    await c.connectGemini();
    await Future<void>.delayed(Duration.zero);
    await c.enableMic();
    await c.startRecording();
    expect(c.microphoneEnabled && c.recordingActive, isTrue);
    await c.disconnectGemini();
    expect(c.geminiConnected, isFalse);
    expect(c.microphoneEnabled, isFalse);
    expect(c.recordingActive, isFalse);
  });

  test('start live feed turns on camera, recording, voice and perception; stop turns all off', () async {
    await c.init();
    await c.startLiveFeed();
    expect(media.unlocked, isTrue);
    expect(c.liveFeedActive, isTrue);
    expect(c.cameraOpen, isTrue);
    expect(c.recordingActive, isTrue);
    expect(c.geminiConnected, isTrue);
    expect(c.microphoneEnabled, isTrue);
    expect(c.cameraStreamingToGemini, isTrue);
    await Future<void>.delayed(const Duration(milliseconds: 80));
    expect(api.perceptionCalls, greaterThan(0));
    expect(c.latestPerception?['actions'][0]['count'], 2);

    await c.stopLiveFeed();
    expect(c.liveFeedActive, isFalse);
    expect(c.cameraOpen, isFalse);
    expect(c.microphoneEnabled, isFalse);
    expect(c.recordingActive, isFalse);
    expect(c.geminiConnected, isFalse);
    expect(media.cameraTrackStates(), 'ended');
    final calls = api.perceptionCalls;
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(api.perceptionCalls, calls); // perception loop halted
  });

  Future<Map<String, dynamic>> toolRoundTrip(String action, [String arg = '']) async {
    sock!.server({
      'toolCall': {
        'functionCalls': [
          {'id': 'fc-$action', 'name': 'request_ui_action', 'args': {'action': action, 'argument': arg}}
        ]
      }
    });
    await Future<void>.delayed(const Duration(milliseconds: 5));
    final resp = sock!.sent.lastWhere((m) => m.containsKey('toolResponse'));
    return (resp['toolResponse']['functionResponses'][0]['response'] as Map).cast<String, dynamic>();
  }

  test('model UI actions run only after backend approval and report the real outcome', () async {
    await c.init();
    await c.connectGemini();
    await Future<void>.delayed(Duration.zero);
    expect(c.protocolSteps.map((s) => s['id']), ['S1', 'S2']);

    var r = await toolRoundTrip('show_protocol_step', 'S2');
    expect(r['executed'], isTrue);
    expect(c.highlightedStep, 'S2');

    r = await toolRoundTrip('show_tab', 'log');
    expect(c.requestedTab, 2);

    r = await toolRoundTrip('capture_snapshot'); // camera closed -> honest failure, nothing captured
    expect(r['ok'], isFalse);
    expect(r['error'], 'camera_closed');
    expect(c.snapshots, isEmpty);
    await c.openCamera();
    r = await toolRoundTrip('capture_snapshot');
    expect(r['executed'], isTrue);
    expect(c.snapshots.single.id, r['snapshot_id']);

    r = await toolRoundTrip('start_recording'); // refused by backend policy -> never executed
    expect(r['ok'], isFalse);
    expect(c.recordingActive, isFalse);
  });

  test('UI actions are batched to the backend, content-free, with source attribution', () async {
    await c.init();
    await c.startLiveFeed();
    c.reportTab(2);
    c.selectProtocolStep('S1');
    await c.stopLiveFeed();
    await c.flushUiActions();
    final actions = api.uiLog.map((a) => a['action']).toList();
    expect(actions, containsAllInOrder(['live_feed_start', 'camera_open', 'recording_start', 'gemini_connect', 'mic_on',
        'frames_share_on', 'tab_change', 'protocol_step_select', 'live_feed_stop']));
    expect(api.uiLog.every((a) => a['source'] == 'user'), isTrue);
    expect(api.uiLog.firstWhere((a) => a['action'] == 'tab_change')['detail'], {'tab': 'log'});
  });

  test('camera flag from the engine is voiced once via Live (throttled, not repeated)', () async {
    await c.init();
    await c.startLiveFeed();
    await Future<void>.delayed(const Duration(milliseconds: 120)); // several perception windows
    final announces = sock!.sent.where((m) => m['clientContent']?['turnComplete'] == true).toList();
    expect(announces.length, 1);
    final text = announces.single['clientContent']['turns'][0]['parts'][0]['text'] as String;
    expect(text, contains('Possible bubble in CH01'));
    expect(c.latestFlag?['action'], 'warn');
    await c.stopLiveFeed();
  });

  test('utterances are routed (voice + typed), results voiced via [Larvis]; noise is ignored', () async {
    await c.init();
    await c.connectGemini();
    await Future<void>.delayed(Duration.zero);
    await c.startRecording();
    // typed -> router (not a chat message to Gemini)
    c.sendTypedMessage('one bubble in channel one');
    await Future<void>.delayed(const Duration(milliseconds: 5));
    expect(api.routed.last, {'text': 'one bubble in channel one', 'source': 'typed', 'session': 'rec-1'});
    expect(sock!.sent.any((m) => m['realtimeInput']?['text'] != null), isFalse);
    final ann = sock!.sent.where((m) => m['clientContent']?['turnComplete'] == true).toList();
    expect(ann.last['clientContent']['turns'][0]['parts'][0]['text'], '[Larvis] Logged: one bubble in CH01.');
    // voice: a pause ends the utterance even though Live stays silent (no turnComplete)
    c.utterancePause = const Duration(milliseconds: 20);
    sock!.server({'serverContent': {'inputTranscription': {'text': 'I pressed the shift key'}}});
    await Future<void>.delayed(const Duration(milliseconds: 60));
    expect(api.routed.last['source'], 'voice');
    expect(sock!.sent.where((m) => m['clientContent']?['turnComplete'] == true).length, ann.length); // noise: no voice
    expect(c.feed.first.eventType, 'ignored (non-scientific)');
    // voice gate: unsolicited model audio is muted; audio answering a [Larvis] announcement plays
    sock!.server({'serverContent': {'turnComplete': true}});
    final before = media.played;
    sock!.server({'serverContent': {'modelTurn': {'parts': [{'inlineData': {'mimeType': 'audio/pcm;rate=24000', 'data': 'AAAA'}}]}}});
    expect(media.played, before);
    c.sendTypedMessage('one bubble in channel one');
    await Future<void>.delayed(const Duration(milliseconds: 5));
    sock!.server({'serverContent': {'modelTurn': {'parts': [{'inlineData': {'mimeType': 'audio/pcm;rate=24000', 'data': 'AAAA'}}]}}});
    expect(media.played, before + 1);
  });

  test('api client sends a stable session header', () {
    final a = LabmateApi(baseUrl: 'http://x');
    expect(a.sessionId, startsWith('web-'));
    expect(a.sessionId.length, greaterThan(10));
  });
}
