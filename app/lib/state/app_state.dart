import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../services/api.dart';
import '../services/live_client.dart';
import '../services/platform_api.dart';

enum Persistence { saved, notSaved, pending, failed, ephemeral }

class FeedItem {
  FeedItem({
    required this.key,
    required this.time,
    required this.eventType,
    required this.modality,
    required this.sourceText,
    this.structured,
    this.model,
    required this.persistence,
    this.review = 'n/a',
    this.raw,
    this.isError = false,
    this.sequence,
  });
  final String key;
  final DateTime time;
  final String eventType;
  final String modality; // speech | image | text | system
  final String sourceText;
  final Map<String, dynamic>? structured;
  final String? model;
  Persistence persistence;
  String review;
  Map<String, dynamic>? raw;
  final bool isError;
  int? sequence;
}

class TranscriptLine {
  TranscriptLine(this.speaker, this.text, {this.final_ = false, this.saved});
  final String speaker; // researcher | labmate
  String text;
  bool final_;
  bool? saved; // null = not applicable / pending
}

class Snapshot {
  Snapshot(this.id, this.b64, this.time, this.source);
  final String id;
  final String b64;
  final DateTime time;
  final String source; // camera | upload
  Map<String, dynamic>? result;
  String? error;
}

String newKey(String prefix) {
  final r = Random.secure();
  return '$prefix-${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}-'
      '${List.generate(8, (_) => r.nextInt(36).toRadixString(36)).join()}';
}

/// Single source of UI truth. Each capability flag is independent; none is inferred from another.
/// `recordingActive` is only ever set from a backend response.
class AppController extends ChangeNotifier {
  AppController({
    required this.api,
    required this.media,
    required LiveSocketFactory socketFactory,
    this.experimentId = 'exp_001',
    this.pollInterval = const Duration(milliseconds: 1500),
    this.heartbeatInterval = const Duration(seconds: 15),
    this.frameInterval = const Duration(seconds: 2),
    this.perceptionFrameInterval = const Duration(milliseconds: 500),
    this.perceptionWindowFrames = 6,
  }) {
    live = LiveClient(
      socketFactory: socketFactory,
      onSetupComplete: _onSetupComplete,
      onAudio: (b64, rate) {
        if (!voiceGate || _speaking) media.playPcm(b64, rate); // router mode: only voice [Larvis] messages
      },
      onInputTranscript: _onInputTranscript,
      onOutputTranscript: _onOutputTranscript,
      onTurnComplete: _onTurnComplete,
      onInterrupted: _onInterrupted,
      onToolCall: _onToolCall,
      onClosed: _onLiveClosed,
      onGoAway: _onGoAway,
    );
  }

  final LabmateApi api;
  final MediaBridge media;
  late final LiveClient live;
  String experimentId;
  final Duration pollInterval, heartbeatInterval, frameInterval;

  // ---- the eight independent states (spec section 13) ----
  bool appConnected = false;
  bool geminiConnected = false;
  bool microphoneEnabled = false;
  bool cameraOpen = false;
  bool cameraStreamingToGemini = false;
  bool recordingActive = false;
  bool snapshotAnalysisInProgress = false;
  bool databaseConnected = false;

  bool geminiConnecting = false;
  // ---- one-press live feed (composes the independent states above; never replaces them) ----
  bool liveFeedActive = false;
  bool liveFeedStarting = false;
  Map<String, dynamic>? latestPerception;
  bool latestPerceptionSaved = false;
  int perceptionWindows = 0, perceptionSaved = 0;
  int _perceptionInFlight = 0; // up to 2 windows in flight -> an update every ~3 s despite ~6 s model latency
  final List<(DateTime, String, String)> activity = []; // (time, text, kind: action|enter|leave|flag)
  Set<String> _lastLabels = {};
  final List<(DateTime, String)> _frameBuf = [];
  Timer? _perceptionTimer;
  Completer<bool>? _setupWaiter;
  final Duration perceptionFrameInterval;
  final int perceptionWindowFrames;
  String? geminiModel;
  Map<String, dynamic>? recording;
  String cameraFacing = 'environment';
  bool multipleCameras = false;
  double micLevel = 0;
  String micPermission = 'unknown', cameraPermission = 'unknown';
  Map<String, dynamic>? capabilities, health;
  String? lastError;
  DateTime? lastDbWriteSeen;
  int framesSent = 0;
  int lastSeq = 0;

  final List<FeedItem> feed = [];
  final Map<String, FeedItem> _feedIndex = {};
  final List<TranscriptLine> transcript = [];
  final List<Snapshot> snapshots = [];
  List<Map<String, dynamic>> log = [];

  // ---- protocol + UI orchestration ----
  Map<String, dynamic>? protocol; // latest ProtocolDocument
  String? highlightedStep;
  int? requestedTab; // set by model-requested show_tab; the shell consumes and clears it
  Map<String, dynamic>? telemetry;
  final List<Map<String, dynamic>> _uiQueue = [];
  Timer? _uiTimer;
  static const tabIndex = {'lab': 0, 'feed': 1, 'log': 2, 'diagnostics': 3};

  TranscriptLine? _userLine, _modelLine;
  Timer? _poll, _heartbeat, _frames, _healthTimer;
  bool _userDisconnect = false;
  int _reconnects = 0;
  bool _disposed = false;

  String? get recordingId => recordingActive ? (recording?['id'] as String?) : null;

  // ================= lifecycle =================
  Future<void> init() async {
    media.onPageHide(() {
      // Never leave media or a recording running when the tab goes away.
      media.stopAll();
      final id = recordingId;
      if (id != null) media.beacon(api.stopUrl(id));
    });
    await refreshDiagnostics();
    await _pollOnce();
    await loadProtocol();
    _poll = Timer.periodic(pollInterval, (_) => _pollOnce());
    _healthTimer = Timer.periodic(const Duration(seconds: 10), (_) => refreshDiagnostics());
    _uiTimer = Timer.periodic(const Duration(seconds: 3), (_) => flushUiActions());
  }

  // ================= UI action log (content-free) =================
  void ui(String action, {Map<String, Object?> detail = const {}, String source = 'user'}) {
    _uiQueue.add({
      'action': action,
      'source': source,
      'detail': {for (final e in detail.entries) if (e.value != null) e.key: e.value},
      'client_timestamp': DateTime.now().toUtc().toIso8601String(),
    });
    if (_uiQueue.length >= 50) flushUiActions();
  }

  Future<void> flushUiActions() async {
    if (_uiQueue.isEmpty) return;
    final batch = List.of(_uiQueue);
    _uiQueue.clear();
    try {
      await api.uiActions(experimentId, recordingId, batch);
    } catch (_) {
      if (_uiQueue.length < 200) _uiQueue.insertAll(0, batch); // retry next tick; bounded
    }
  }

  void reportTab(int index) {
    final name = tabIndex.entries.firstWhere((e) => e.value == index, orElse: () => const MapEntry('lab', 0)).key;
    ui('tab_change', detail: {'tab': name});
  }

  // ================= protocol =================
  Future<void> loadProtocol() async {
    try {
      protocol = await api.protocol(experimentId);
    } catch (_) {
      protocol = null;
    }
    _notify();
  }

  List<Map<String, dynamic>> get protocolSteps =>
      ((protocol?['content']?['steps'] as List?) ?? const []).cast<Map<String, dynamic>>();

  /// Researcher taps a step: highlight it and tell Gemini (context only, no forced reply).
  void selectProtocolStep(String id) {
    highlightedStep = id;
    ui('protocol_step_select', detail: {'step': id});
    if (live.ready) live.addContext('[Larvis UI] The researcher selected protocol step $id as the current step.');
    _notify();
  }

  Future<void> refreshDiagnostics() async {
    try {
      health = await api.health();
      capabilities ??= await api.capabilities();
      appConnected = true;
      databaseConnected = health?['database_ok'] == true;
    } catch (e) {
      appConnected = false;
      databaseConnected = false;
    }
    micPermission = await media.permission('microphone');
    cameraPermission = await media.permission('camera');
    try {
      telemetry = await api.telemetrySummary(60);
    } catch (_) {/* diagnostics only */}
    _notify();
  }

  Future<void> _pollOnce() async {
    try {
      final page = await api.pollEvents(experimentId, lastSeq);
      appConnected = true;
      databaseConnected = true;
      for (final e in (page['events'] as List).cast<Map<String, dynamic>>()) {
        _mergePersisted(e);
      }
      lastSeq = max(lastSeq, (page['last_sequence'] as num).toInt());
      _applyRecording(page['recording'] as Map<String, dynamic>?, fromPoll: true);
    } catch (e) {
      appConnected = false;
    }
    _notify();
  }

  void _applyRecording(Map<String, dynamic>? r, {bool fromPoll = false}) {
    final wasActive = recordingActive;
    if (r == null) {
      if (fromPoll && wasActive) _addSystem('Recording ended on the server (${recording?['id']}).');
      recordingActive = false;
    } else {
      recording = r;
      recordingActive = r['status'] == 'active';
      if (wasActive && !recordingActive) _addSystem('Recording ${r['status']}: ${r['stop_reason'] ?? ''}');
    }
    if (recordingActive && _heartbeat == null) {
      _heartbeat = Timer.periodic(heartbeatInterval, (_) => _sendHeartbeat());
    } else if (!recordingActive) {
      _heartbeat?.cancel();
      _heartbeat = null;
    }
  }

  Future<void> _sendHeartbeat() async {
    final id = recordingId;
    if (id == null) return;
    try {
      _applyRecording(await api.heartbeat(id));
    } on ApiException catch (e) {
      if (e.code == 'recording_inactive' || e.status == 404) _applyRecording(null, fromPoll: true);
    } catch (_) {/* transient; server will expire after timeout if we stay offline */}
    _notify();
  }

  // ================= recording (explicit user action only) =================
  Future<void> startRecording() async {
    try {
      _applyRecording(await api.startRecording(experimentId));
      ui('recording_start');
      _addSystem('Recording started (${recording?['id']}). Finalised speech, observations and saved snapshots will be stored.');
    } catch (e) {
      _error('Could not start recording: $e');
    }
    _notify();
  }

  Future<void> stopRecording([String reason = 'user_stopped']) async {
    final id = recording?['id'] as String?;
    if (id == null) return;
    try {
      _applyRecording(await api.stopRecording(id, reason));
      ui('recording_stop', detail: {'reason': reason});
      _addSystem('Recording stopped ($reason). Conversation is no longer persisted.');
    } catch (e) {
      _error('Could not stop recording: $e');
    }
    _notify();
  }

  // ================= Gemini Live =================
  /// Call directly from the button handler: unlockAudio() must run inside the user gesture.
  Future<void> connectGemini() async {
    if (geminiConnected || geminiConnecting) return;
    media.unlockAudio();
    _userDisconnect = false;
    ui('gemini_connect');
    await _openLive();
  }

  Future<void> _openLive() async {
    geminiConnecting = true;
    _notify();
    try {
      final t = await api.liveToken(experimentId);
      geminiModel = t['model'] as String;
      live.connect(websocketUrl: t['websocket_url'] as String, token: t['token'] as String, model: geminiModel!);
    } catch (e) {
      geminiConnecting = false;
      _setupWaiter?.complete(false);
      _setupWaiter = null;
      _error('Gemini connection failed: $e');
    }
  }

  void _onSetupComplete() {
    geminiConnecting = false;
    geminiConnected = true;
    _reconnects = 0;
    _setupWaiter?.complete(true);
    _setupWaiter = null;
    _addSystem('Gemini Live connected ($geminiModel).');
    _notify();
  }

  Future<bool> _waitForGemini(Duration timeout) async {
    if (geminiConnected) return true;
    _setupWaiter ??= Completer<bool>();
    return _setupWaiter!.future.timeout(timeout, onTimeout: () => false);
  }

  // ================= one-press live feed =================
  /// Landing-page "Start live feed": camera + recording + perception logging + Gemini voice.
  /// Must be invoked from the button tap (audio unlock happens synchronously first).
  Future<void> startLiveFeed() async {
    if (liveFeedActive || liveFeedStarting) return;
    liveFeedStarting = true;
    media.unlockAudio();
    ui('live_feed_start');
    _notify();
    try {
      await openCamera();
      if (!cameraOpen) throw StateError('camera did not open');
      await startRecording();
      if (!recordingActive) throw StateError('recording did not start');
      _startPerception();
      liveFeedActive = true;
      // Voice is best-effort: perception logging keeps running even if Gemini Live fails.
      await connectGemini();
      if (await _waitForGemini(const Duration(seconds: 15))) {
        await enableMic();
        setCameraStreaming(true);
      } else {
        _error('Gemini Live did not connect; perception logging continues without voice.');
      }
    } catch (e) {
      _error('Live feed could not start: $e');
      if (!liveFeedActive) await stopLiveFeed();
    }
    liveFeedStarting = false;
    _notify();
  }

  Future<void> stopLiveFeed() async {
    if (liveFeedActive || liveFeedStarting) ui('live_feed_stop');
    _stopPerception();
    if (geminiConnected || geminiConnecting) await disconnectGemini();
    disableMic();
    closeCamera();
    if (recordingActive) await stopRecording('live_feed_stopped');
    liveFeedActive = false;
    liveFeedStarting = false;
    _notify();
  }

  void _startPerception() {
    _perceptionTimer?.cancel();
    _frameBuf.clear();
    activity.clear();
    _lastLabels = {};
    _perceptionTimer = Timer.periodic(perceptionFrameInterval, (_) {
      if (!cameraOpen) return;
      final f = media.captureFrame(512, 0.6);
      if (f == null) return;
      _frameBuf.add((DateTime.now().toUtc(), f));
      if (_frameBuf.length > 12) _frameBuf.removeAt(0); // bound latency if the model is slow
      if (_frameBuf.length >= perceptionWindowFrames && _perceptionInFlight < 2) _sendPerceptionWindow();
    });
  }

  void _stopPerception() {
    _perceptionTimer?.cancel();
    _perceptionTimer = null;
    _frameBuf.clear();
  }

  Future<void> _sendPerceptionWindow() async {
    final frames = List.of(_frameBuf);
    _frameBuf.clear();
    _perceptionInFlight++;
    final key = newKey('pw');
    try {
      final r = await api.perceptionWindow({
        'frames_base64': [for (final f in frames) f.$2],
        'frame_interval_s': perceptionFrameInterval.inMilliseconds / 1000.0,
        'window_start': frames.first.$1.toIso8601String(),
        'window_end': frames.last.$1.toIso8601String(),
        'experiment_id': experimentId,
        'session_id': recordingId,
        'idempotency_key': key,
      });
      perceptionWindows++;
      latestPerception = (r['perception'] as Map).cast<String, dynamic>();
      _pushActivity(latestPerception!);
      latestPerceptionSaved = r['saved'] == true;
      if (latestPerceptionSaved) {
        perceptionSaved++;
        _mergePersisted(r['event'] as Map<String, dynamic>);
      }
      _announceFlag(r['reconciliation'] as Map<String, dynamic>?);
    } catch (e) {
      _error('Perception window failed: $e');
    }
    _perceptionInFlight--;
    _notify();
  }

  // ================= live activity ticker =================
  /// Turn each perception window into short human-readable lines: actions, objects entering/leaving frame.
  void _pushActivity(Map<String, dynamic> p) {
    final now = DateTime.now();
    final lines = <(DateTime, String, String)>[];
    for (final a in ((p['actions'] as List?) ?? const []).cast<Map>()) {
      lines.add((now, '${a['action']}${a['object'] != null && !'${a['action']}'.contains('${a['object']}') ? ' · ${a['object']}' : ''} ×${a['count']}'
          '${a['certainty'] == 'uncertain' ? ' (uncertain)' : ''}', 'action'));
    }
    final labels = {for (final o in ((p['objects'] as List?) ?? const []).cast<Map>()) '${o['label']}'.toLowerCase()};
    for (final l in labels.difference(_lastLabels)) {
      lines.add((now, '$l entered frame', 'enter'));
    }
    for (final l in _lastLabels.difference(labels)) {
      lines.add((now, '$l left frame', 'leave'));
    }
    _lastLabels = labels;
    final sp = p['specialist'] as Map?;
    if (sp != null && sp['count'] != null && (sp['count'] as num) > 0) {
      lines.add((now, 'specialist: ${sp['count']} bubble(s) measured', 'flag'));
    }
    activity.insertAll(0, lines);
    if (activity.length > 40) activity.removeRange(40, activity.length);
  }

  // ================= voice output gate =================
  /// Router mode: Gemini Live is only a voice. Its audio plays solely while answering a [Larvis] message.
  bool voiceGate = true;
  bool _speaking = false;

  void _say(String text) {
    if (!live.ready) return;
    _speaking = true;
    live.announce('[Larvis] $text');
  }

  // ================= utterance routing (no conversation) =================
  Timer? _utteranceTimer;
  Duration utterancePause = const Duration(milliseconds: 1400);
  Map<String, dynamic>? lastRoute;

  /// Every finished utterance (voice transcript or typed) -> /api/route -> one action; result spoken via Live.
  Future<void> _route(String text, String source) async {
    final key = newKey('route');
    try {
      final r = await api.route(experimentId, recordingId, text, source, key);
      lastRoute = r;
      if (r['tool'] == 'none') {
        _upsert(FeedItem(key: key, time: DateTime.now(), eventType: 'ignored (non-scientific)', modality: 'speech',
            sourceText: text, persistence: Persistence.ephemeral, raw: r));
      } else {
        _upsert(FeedItem(
            key: key,
            time: DateTime.now(),
            eventType: 'route:${r['tool']}${r['ambiguous'] == true ? ' (ambiguous)' : ''}',
            modality: source == 'typed' ? 'text' : 'speech',
            sourceText: '$text\n→ ${r['spoken'] ?? ''}',
            structured: (r['args'] as Map?)?.cast<String, dynamic>(),
            model: r['router_model'] as String?,
            persistence: r['stored'] == true ? Persistence.saved : Persistence.ephemeral,
            raw: r,
            isError: (r['result'] as Map?)?['ok'] == false));
        final spoken = r['spoken'];
        if (spoken is String && spoken.isNotEmpty) _say(spoken);
        if (r['stored'] == true) unawaited(_pollOnce());
      }
    } catch (e) {
      _error('Routing failed: $e');
    }
    _notify();
  }

  // ================= spoken camera flags =================
  Map<String, dynamic>? latestFlag;
  String? _lastAnnounced;
  DateTime _lastAnnounceAt = DateTime.fromMillisecondsSinceEpoch(0);

  /// A deterministic camera flag (steering engine verdict needing sign-off) is voiced by Gemini, throttled
  /// to one per 20 s and never repeated for the same message. The text comes from the engine, not the model.
  void _announceFlag(Map<String, dynamic>? rc) {
    if (rc == null || rc['requires_human_approval'] != true) return;
    latestFlag = rc;
    final msg = '${rc['spoken_response'] ?? ''}'.trim();
    final now = DateTime.now();
    if (msg.isEmpty || msg == _lastAnnounced || now.difference(_lastAnnounceAt) < const Duration(seconds: 20)) return;
    _lastAnnounced = msg;
    _lastAnnounceAt = now;
    final cross = rc['cross_check'] as Map?;
    final note = cross != null && cross['agree'] == false
        ? ' (Note: Gemini counted ${cross['gemini_count']} and the specialist counted ${cross['specialist_count']}; ask the researcher to confirm.)'
        : '';
    _say('Camera flag: $msg$note');
  }

  /// Typed equivalent of the voice query path (same backend agent as the query_lab_log tool).
  Future<Map<String, dynamic>?> askLog(String question) async {
    ui('log_query_typed');
    try {
      final r = await api.query(experimentId, question);
      _upsert(FeedItem(
          key: newKey('q'),
          time: DateTime.now(),
          eventType: 'log_query',
          modality: 'text',
          sourceText: 'Q: $question\nA: ${r['answer']}',
          structured: r,
          model: r['model'] as String?,
          persistence: Persistence.ephemeral));
      _notify();
      return r;
    } catch (e) {
      _error('Log query failed: $e');
      return null;
    }
  }

  Future<void> disconnectGemini() async {
    _userDisconnect = true;
    ui('gemini_disconnect');
    disableMic();
    setCameraStreaming(false);
    live.close();
    live.resumptionHandle = null;
    media.stopPlayback();
    geminiConnected = false;
    geminiConnecting = false;
    _finaliseTurn();
    if (recordingActive) await stopRecording('gemini_disconnected');
    _notify();
  }

  void _onLiveClosed(int code, String reason) {
    final wasConnected = geminiConnected || geminiConnecting;
    geminiConnected = false;
    geminiConnecting = false;
    _finaliseTurn();
    if (!_userDisconnect && wasConnected) {
      if (_reconnects < 3) {
        _reconnects++;
        _addSystem('Gemini connection closed ($code ${reason.isEmpty ? '' : reason}); reconnecting ($_reconnects/3)...');
        Future.delayed(Duration(milliseconds: 500 * _reconnects), () {
          if (!_userDisconnect && !_disposed) _openLive();
        });
      } else {
        disableMic();
        setCameraStreaming(false);
        _error('Gemini connection lost ($code $reason). Press Connect to retry.');
      }
    }
    _notify();
  }

  void _onGoAway() => _addSystem('Gemini session ending soon; will resume automatically.');

  // ================= microphone =================
  Future<void> enableMic() async {
    if (!geminiConnected) {
      _error('Connect to Gemini before enabling the microphone.');
      return;
    }
    try {
      await media.micStart((b64) {
        if (live.ready) live.sendAudio(b64);
      }, (rms) {
        micLevel = rms;
      });
    } catch (e) {
      _error('Microphone unavailable: $e');
    }
    microphoneEnabled = media.micActive();
    if (microphoneEnabled) ui('mic_on');
    micPermission = await media.permission('microphone');
    _notify();
  }

  void disableMic() {
    if (!microphoneEnabled && !media.micActive()) return;
    media.micStop();
    ui('mic_off');
    live.sendAudioStreamEnd();
    microphoneEnabled = media.micActive();
    micLevel = 0;
    _notify();
  }

  void sendTypedMessage(String text) {
    if (text.trim().isEmpty) return;
    _finaliseTurn();
    _userLine = TranscriptLine('researcher', text.trim());
    transcript.add(_userLine!);
    _finaliseUser(source: 'typed'); // routed like speech; never a chat with the model
    _notify();
  }

  // ================= camera =================
  Future<void> openCamera() async {
    try {
      await media.cameraOpen(cameraFacing);
      multipleCameras = await media.hasMultipleCameras();
    } catch (e) {
      _error('Camera unavailable: $e');
    }
    cameraOpen = media.cameraActive();
    if (cameraOpen) ui('camera_open', detail: {'facing': cameraFacing});
    cameraPermission = await media.permission('camera');
    _notify();
  }

  void closeCamera() {
    setCameraStreaming(false);
    if (cameraOpen) ui('camera_close');
    media.cameraClose();
    cameraOpen = media.cameraActive();
    _notify();
  }

  Future<void> flipCamera() async {
    cameraFacing = cameraFacing == 'environment' ? 'user' : 'environment';
    ui('camera_flip', detail: {'facing': cameraFacing});
    if (cameraOpen) {
      final streaming = cameraStreamingToGemini;
      setCameraStreaming(false);
      await openCamera();
      if (streaming) setCameraStreaming(true);
    }
    _notify();
  }

  /// Separate, explicit permission for Gemini to see camera frames (1 frame / 2 s, 640 px JPEG).
  void setCameraStreaming(bool on) {
    _frames?.cancel();
    _frames = null;
    if (on && (!cameraOpen || !geminiConnected)) {
      _error('Open the camera and connect Gemini before sharing frames.');
      on = false;
    }
    if (on != cameraStreamingToGemini) ui(on ? 'frames_share_on' : 'frames_share_off');
    cameraStreamingToGemini = on;
    if (on) {
      _frames = Timer.periodic(frameInterval, (_) {
        if (!cameraOpen || !live.ready) return;
        final f = media.captureFrame(640, 0.6);
        if (f != null) {
          live.sendVideoFrame(f);
          framesSent++;
        }
      });
    }
    _notify();
  }

  // ================= snapshots / vision =================
  Snapshot? captureSnapshot() {
    final b64 = media.captureFrame(1280, 0.85);
    if (b64 == null) {
      _error('No camera frame available. Open the camera first.');
      return null;
    }
    final s = Snapshot(newKey('snap'), b64, DateTime.now(), 'camera');
    ui('snapshot_capture', detail: {'snapshot': s.id});
    snapshots.insert(0, s);
    _notify();
    return s;
  }

  void uploadImage() => media.pickImage((b64) {
        snapshots.insert(0, Snapshot(newKey('upl'), b64, DateTime.now(), 'upload'));
        ui('image_upload');
        _notify();
      });

  Future<void> analyseSnapshot(Snapshot s, String question, {required bool save}) async {
    if (save && !recordingActive) {
      _error('Saving requires an active recording.');
      return;
    }
    snapshotAnalysisInProgress = true;
    ui('snapshot_analyse', detail: {'snapshot': s.id, 'save': save});
    _notify();
    final key = newKey('vis');
    try {
      final r = await api.vision({
        'image_base64': s.b64,
        'question': question,
        'experiment_id': experimentId,
        'save': save,
        'session_id': save ? recordingId : null,
        'idempotency_key': save ? key : null,
      });
      s.result = r;
      s.error = null;
      final saved = r['saved'] == true;
      if (saved) {
        _mergePersisted(r['event'] as Map<String, dynamic>);
      } else {
        _upsert(FeedItem(
            key: key,
            time: DateTime.now(),
            eventType: 'visual_observation',
            modality: 'image',
            sourceText: '${r['description']}',
            structured: (r['structured'] as Map?)?.cast<String, dynamic>(),
            model: r['model'] as String?,
            persistence: save ? Persistence.failed : Persistence.notSaved,
            raw: r));
      }
      // Give the live conversation the result so "what did you see in that snapshot?" is grounded.
      if (live.ready) {
        live.addContext('[Larvis snapshot analysis ${s.id} by ${r['model']}; ${saved ? 'SAVED' : 'NOT saved'}] '
            'Question: $question. Result: ${jsonEncode(r['structured'])}');
      }
    } catch (e) {
      s.error = '$e';
      _error('Snapshot analysis failed: $e');
    }
    snapshotAnalysisInProgress = false;
    _notify();
  }

  // ================= transcripts =================
  void _onInputTranscript(String t) {
    if (_modelLine != null) _finaliseTurn();
    if (_userLine == null) {
      _userLine = TranscriptLine('researcher', '');
      transcript.add(_userLine!);
    }
    _userLine!.text += t;
    _utteranceTimer?.cancel();
    _utteranceTimer = Timer(utterancePause, () {
      _finaliseUser();
      _notify();
    });
    _notify();
  }

  void _onOutputTranscript(String t) {
    if (voiceGate && !_speaking) return; // unsolicited model chatter is muted and not shown
    if (_userLine != null) _finaliseUser();
    if (_modelLine == null) {
      _modelLine = TranscriptLine('labmate', '');
      transcript.add(_modelLine!);
    }
    _modelLine!.text += t;
    _notify();
  }

  void _onTurnComplete() {
    _speaking = false;
    _finaliseTurn();
  }

  void _onInterrupted() {
    media.stopPlayback(); // barge-in: stop speaking immediately
    if (_modelLine != null) _modelLine!.text += ' …';
    _finaliseTurn();
  }

  void _finaliseTurn() {
    _finaliseUser();
    if (_modelLine != null) {
      _modelLine!.final_ = true;
      _modelLine = null;
    }
    _trimTranscript();
    _notify();
  }

  /// A finalised researcher utterance is persisted ONLY if the backend says recording is active.
  void _finaliseUser({String source = 'voice'}) {
    _utteranceTimer?.cancel();
    final line = _userLine;
    _userLine = null;
    if (line == null) return;
    line.final_ = true;
    line.text = line.text.trim();
    if (line.text.isEmpty) return;
    unawaited(_route(line.text, source));
    final key = newKey('seg');
    final id = recordingId;
    final item = FeedItem(
        key: key,
        time: DateTime.now(),
        eventType: 'transcript_segment',
        modality: 'speech',
        sourceText: line.text,
        model: geminiModel,
        persistence: id == null ? Persistence.ephemeral : Persistence.pending);
    _upsert(item);
    if (id == null) {
      line.saved = false;
      return;
    }
    api.propose({
      'session_id': id,
      'experiment_id': experimentId,
      'source_modality': 'speech',
      'event_type': 'transcript_segment',
      'payload': {'speaker': 'researcher', 'text': line.text, 'transcribed_by': geminiModel},
      'model_name': geminiModel,
      'idempotency_key': key,
    }).then((ack) {
      line.saved = true;
      _mergePersisted(ack['event'] as Map<String, dynamic>);
      _notify();
    }).catchError((Object e) {
      line.saved = false;
      item.persistence = (e is ApiException && e.code == 'recording_inactive') ? Persistence.notSaved : Persistence.failed;
      _notify();
    });
  }

  void _trimTranscript() {
    if (transcript.length > 200) transcript.removeRange(0, transcript.length - 200);
  }

  // ================= tools =================
  Future<void> _onToolCall(List<Map<String, dynamic>> calls) async {
    final responses = <Map<String, dynamic>>[];
    for (final c in calls) {
      final name = '${c['name']}';
      final args = (c['args'] as Map?)?.cast<String, dynamic>() ?? {};
      Map<String, dynamic> result;
      try {
        String? image;
        if (name == 'request_visual_analysis' && snapshots.isNotEmpty) {
          final wanted = args['image_id'];
          image = (snapshots.firstWhere((s) => s.id == wanted, orElse: () => snapshots.first)).b64;
        }
        result = await api.toolCall({
          'name': name,
          'args': args,
          'experiment_id': experimentId,
          'session_id': recordingId,
          'call_id': c['id'],
          'image_base64': image,
        });
      } catch (e) {
        result = {'ok': false, 'saved': false, 'error': 'backend_unreachable', 'message': '$e'};
      }
      if (name == 'request_ui_action' && result['ok'] == true && result['ui_action'] is Map) {
        result = {...result, ..._executeUiAction((result['ui_action'] as Map).cast<String, dynamic>())};
      }
      _upsert(FeedItem(
          key: 'tool-${c['id'] ?? newKey('t')}',
          time: DateTime.now(),
          eventType: 'tool:$name',
          modality: 'system',
          sourceText: result['ok'] == true
              ? (result['saved'] == true ? 'Saved ${result['event_id']}' : 'OK')
              : '${result['error']}: ${result['message'] ?? ''}',
          structured: {'args': args, 'result': result},
          model: geminiModel,
          persistence: result['saved'] == true ? Persistence.saved : Persistence.ephemeral,
          isError: result['ok'] != true));
      responses.add({'id': c['id'], 'name': name, 'response': result});
      if (result['saved'] == true) unawaited(_pollOnce());
    }
    live.sendToolResponses(responses);
    _notify();
  }

  /// Runs a backend-approved, allowlisted UI action and reports what ACTUALLY happened back to the model.
  Map<String, dynamic> _executeUiAction(Map<String, dynamic> a) {
    final action = '${a['action']}', arg = '${a['argument'] ?? ''}';
    Map<String, dynamic> out;
    switch (action) {
      case 'capture_snapshot':
        final s = cameraOpen ? captureSnapshot() : null;
        out = s == null
            ? {'ok': false, 'executed': false, 'error': 'camera_closed', 'message': 'Camera is not open.'}
            : {'executed': true, 'snapshot_id': s.id, 'note': 'Use request_visual_analysis with this image_id.'};
      case 'show_tab':
        requestedTab = tabIndex[arg];
        out = {'executed': requestedTab != null};
      case 'show_protocol_step':
        highlightedStep = arg;
        out = {'executed': true};
      case 'flip_camera':
        if (cameraOpen) {
          unawaited(flipCamera());
          out = {'executed': true};
        } else {
          out = {'ok': false, 'executed': false, 'error': 'camera_closed'};
        }
      default:
        out = {'ok': false, 'executed': false, 'error': 'unsupported_ui_action'};
    }
    ui(action, detail: {'argument': arg, 'executed': out['executed'] == true}, source: 'model');
    _notify();
    return out;
  }

  // ================= feed / log =================
  void _mergePersisted(Map<String, dynamic> e) {
    final key = '${e['idempotency_key']}';
    final p = (e['payload'] as Map).cast<String, dynamic>();
    final item = FeedItem(
      key: key,
      time: DateTime.tryParse('${e['timestamp']}')?.toLocal() ?? DateTime.now(),
      eventType: '${e['event_type']}',
      modality: '${e['source_modality']}',
      sourceText: e['event_type'] == 'perception'
          ? '${p['scene_summary']}'
              '${((p['actions'] as List?) ?? const []).map((a) => '\n• ${a['action']} ×${a['count']} (${a['certainty']})').join()}'
          : '${p['text'] ?? p['summary'] ?? p['description'] ?? p['correction'] ?? ''}',
      structured: p,
      model: e['model_name'] as String?,
      persistence: Persistence.saved,
      review: '${e['review_status']}',
      raw: e,
      sequence: (e['sequence_number'] as num).toInt(),
    );
    _upsert(item);
    lastSeq = max(lastSeq, item.sequence!);
    final ts = DateTime.tryParse('${e['timestamp']}');
    if (ts != null && (lastDbWriteSeen == null || ts.isAfter(lastDbWriteSeen!))) lastDbWriteSeen = ts;
  }

  void _upsert(FeedItem item) {
    final existing = _feedIndex[item.key];
    if (existing != null) {
      final i = feed.indexOf(existing);
      if (i >= 0) feed[i] = item;
    } else {
      feed.insert(0, item);
      if (feed.length > 500) _feedIndex.remove(feed.removeLast().key);
    }
    _feedIndex[item.key] = item;
  }

  void _addSystem(String msg) => _upsert(FeedItem(
      key: newKey('sys'),
      time: DateTime.now(),
      eventType: 'status',
      modality: 'system',
      sourceText: msg,
      persistence: Persistence.ephemeral));

  void _error(String msg) {
    lastError = msg;
    _upsert(FeedItem(
        key: newKey('err'),
        time: DateTime.now(),
        eventType: 'error',
        modality: 'system',
        sourceText: msg,
        persistence: Persistence.ephemeral,
        isError: true));
    _notify();
  }

  Future<void> loadLog() async {
    try {
      log = (await api.observations(experimentId)).cast<Map<String, dynamic>>().reversed.toList();
    } catch (e) {
      _error('Could not load experiment log: $e');
    }
    _notify();
  }

  Future<void> reviewObservation(String id, String action, {Map<String, dynamic>? correction}) async {
    try {
      await api.review(id, action, correction: correction, reviewer: 'researcher');
      ui('review_action', detail: {'action': action});
      await loadLog();
      // Reflect review state in the feed too.
      for (final f in feed) {
        if (f.raw?['id'] == id) f.review = {'accept': 'accepted', 'dispute': 'disputed', 'correct': 'corrected', 'reject': 'rejected'}[action]!;
      }
      await _pollOnce();
    } catch (e) {
      _error('Review failed: $e');
    }
  }

  void exportLog() => media.downloadJson('labmate-$experimentId-${DateTime.now().toIso8601String()}.json',
      const JsonEncoder.withIndent('  ').convert({'experiment_id': experimentId, 'observations': log}));

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _poll?.cancel();
    _utteranceTimer?.cancel();
    _heartbeat?.cancel();
    _frames?.cancel();
    _healthTimer?.cancel();
    _uiTimer?.cancel();
    flushUiActions();
    live.close();
    media.stopAll();
    super.dispose();
  }
}
