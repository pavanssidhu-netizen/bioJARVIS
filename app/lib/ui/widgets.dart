import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../state/app_state.dart';
import 'theme.dart';

/// Non-invasive V2 API & UI helper extension on [AppController].
/// Preserves `lib/state/app_state.dart` and `lib/services/api.dart` untouched per `docs/UI_DEV.md`.
extension V2ApiExtension on AppController {
  Uri _v2Uri(String path, [Map<String, String>? q]) =>
      Uri.parse('${api.baseUrl}/api$path').replace(queryParameters: q);

  Future<dynamic> _v2Send(String method, String path, {Object? body, Map<String, String>? query}) async {
    final req = http.Request(method, _v2Uri(path, query));
    req.headers['x-labmate-session'] = api.sessionId;
    if (body != null) {
      req.headers['content-type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final streamed = await http.Client().send(req).timeout(const Duration(seconds: 25));
    final res = await http.Response.fromStream(streamed);
    if (res.statusCode >= 400) {
      throw Exception('HTTP ${res.statusCode}: ${res.body}');
    }
    return res.body.isEmpty ? null : jsonDecode(res.body);
  }

  /// Switch bottom navigation tab via Shell's `requestedTab` listener.
  void switchToTab(int index) {
    requestedTab = index;
    reportTab(index);
    // Trigger ListenableBuilder in Shell without modifying private _notify
    selectProtocolStep(highlightedStep ?? activeStepIdResolved);
  }

  String get experimentDisplayTitle {
    final raw = '${protocol?['content']?['title'] ?? ''}'.trim();
    if (raw.isEmpty || raw.toLowerCase().contains('cea')) {
      return 'CEA microfluidic assay';
    }
    return raw;
  }

  String get activeStepIdResolved {
    if (highlightedStep != null && highlightedStep!.isNotEmpty) return highlightedStep!;
    final pStep = latestPerception?['active_step_id'] as String?;
    if (pStep != null && pStep.isNotEmpty) return pStep;
    for (final f in feed) {
      final st = f.structured?['active_step_id'] ?? f.structured?['protocol_step'] ?? f.structured?['step_id'];
      if (st is String && st.isNotEmpty) return st;
    }
    final steps = protocolSteps;
    if (steps.length >= 5) return '${steps[4]['id']}';
    if (steps.isNotEmpty) return '${steps.first['id']}';
    return 'step_05';
  }

  String get activeChannelIdResolved {
    final pCh = latestPerception?['active_channel_id'] as String?;
    if (pCh != null && pCh.isNotEmpty) return pCh;
    for (final f in feed) {
      final ch = f.structured?['active_channel_id'] ?? f.structured?['channel_id'];
      if (ch is String && ch.isNotEmpty) return ch;
    }
    return 'CH08';
  }

  bool get isShowingDemoSession => !recordingActive && !geminiConnected && !cameraOpen;

  /// Returns live perception if present, otherwise the most recent perception event from feed/log,
  /// or a clearly marked demo fixture when no events are loaded.
  Map<String, dynamic> get effectivePerceptionPayload {
    if (latestPerception != null) return latestPerception!;
    for (final item in feed) {
      if (item.eventType == 'perception' && item.structured != null) {
        return item.structured!;
      }
    }
    for (final row in log) {
      if (row['event_type'] == 'perception' && row['payload'] is Map) {
        return (row['payload'] as Map).cast<String, dynamic>();
      }
    }
    return demoPerceptionFixture;
  }

  static const Map<String, dynamic> demoPerceptionFixture = {
    'is_demo_fixture': true,
    'scene_summary': 'Chip and pipette in view.',
    'active_step_id': 'step_05',
    'active_channel_id': 'CH08',
    'tracking': ['Bubbles'],
    'objects': [
      {'label': 'Chip', 'certainty': 'certain', 'box_2d': [290, 145, 795, 785]},
      {'label': 'Pipette', 'certainty': 'certain', 'box_2d': [90, 515, 465, 795]},
    ],
    'actions': [
      {'action': 'load sample', 'object': 'CH08', 'count': 1, 'certainty': 'likely', 'protocol_step': 'step_05'},
    ],
    'specialist': {
      'provider': 'specialist',
      'model': 'labmate-perception-agent-v1',
      'count': 2,
      'abstained': false,
      'review_required': true,
      'image_width': 640,
      'image_height': 360,
      'detections': [
        {'label': 'Bubble ?', 'bbox': [272, 162, 304, 194], 'confidence': 0.89, 'obstruction_risk': 'high_obstruction_candidate', 'channel_obstruction_ratio': 0.52},
        {'label': 'Bubble ?', 'bbox': [376, 174, 408, 204], 'confidence': 0.84, 'obstruction_risk': 'low', 'channel_obstruction_ratio': 0.14},
      ],
      'description': 'Two bubble candidates marked for review.',
      'sceptic_critique': 'Border-clipped meniscus candidate and wall glare excluded.',
    },
  };

  Future<List<Map<String, dynamic>>> fetchExperimentSessions() async {
    final res = await _v2Send('GET', '/experiments/$experimentId/sessions');
    return ((res as List?) ?? const []).map((e) => (e as Map).cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> fetchRecordingSummary(String recId) async {
    final res = await _v2Send('GET', '/recordings/$recId/summary');
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> fetchDependencyGraph({String? focus, String? stepId}) async {
    final q = <String, String>{};
    if (focus != null && focus.isNotEmpty) q['focus'] = focus;
    if (stepId != null && stepId.isNotEmpty) q['step_id'] = stepId;
    final res = await _v2Send('GET', '/experiments/$experimentId/graph', query: q.isEmpty ? null : q);
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<List<Map<String, dynamic>>> fetchPendingReviews() async {
    final res = await _v2Send('GET', '/reviews/pending', query: {'experiment_id': experimentId});
    return ((res as List?) ?? const []).map((e) => (e as Map).cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> fetchLiveRecordingState(String recId) async {
    final res = await _v2Send('GET', '/recordings/$recId/state');
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> updateLiveRecordingState(String recId, {String? activeStepId, String? activeChannelId, bool clearChannel = false}) async {
    final body = <String, dynamic>{};
    if (activeStepId != null) body['active_step_id'] = activeStepId;
    if (activeChannelId != null || clearChannel) body['active_channel_id'] = clearChannel ? null : activeChannelId;
    final res = await _v2Send('PUT', '/recordings/$recId/state', body: body);
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> addTrackedObject(String recId, String label, {String? channelId}) async {
    final res = await _v2Send('POST', '/recordings/$recId/tracking', body: {
      'label': label,
      'channel_id': ?channelId,
    });
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> removeTrackedObject(String recId, String label) async {
    final res = await _v2Send('DELETE', '/recordings/$recId/tracking/${Uri.encodeComponent(label)}');
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<List<Map<String, dynamic>>> fetchRetainedFrames(String recId) async {
    final res = await _v2Send('GET', '/recordings/$recId/frames');
    final list = ((res as Map?)?['frames'] as List?) ?? const [];
    return list.map((e) => (e as Map).cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> reanalyseRetainedFrames(String recId, {List<String>? frameIds, String? question}) async {
    final res = await _v2Send('POST', '/recordings/$recId/reanalyse', body: {
      'frame_ids': ?frameIds,
      if (question != null && question.isNotEmpty) 'question': question,
    });
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> runInvestigation({String? question, String? stepId, String? observationId}) async {
    final res = await _v2Send('POST', '/investigate', body: {
      'experiment_id': experimentId,
      'question': ?question,
      'step_id': ?stepId,
      'observation_id': ?observationId,
    });
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> runBayesianOptimiser({
    double obstructionRatio = 0.45,
    double sauterMeanPx = 38.0,
    double volumeVarianceUl = -1.0,
  }) async {
    final res = await _v2Send('POST', '/predictive/optimise', body: {
      'max_channel_obstruction_ratio': obstructionRatio,
      'sauter_mean_diameter_px': sauterMeanPx,
      'volume_variance_ul': volumeVarianceUl,
    });
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill({
    super.key,
    required this.label,
    required this.on,
    this.onColor = LM.teal,
    this.icon,
    this.pulse = false,
  });
  final String label;
  final bool on;
  final Color onColor;
  final IconData? icon;
  final bool pulse;

  @override
  Widget build(BuildContext context) {
    final bg = on
        ? (onColor == LM.ok
            ? LM.okBg
            : onColor == LM.warn
                ? LM.reviewBg
                : onColor.withValues(alpha: 0.14))
        : LM.pillNeutralBg;
    final fg = on
        ? (onColor == LM.ok
            ? LM.okText
            : onColor == LM.warn
                ? LM.reviewText
                : onColor)
        : LM.pillNeutralText;
    return Semantics(
      label: '$label ${on ? 'on' : 'off'}',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: on ? fg.withValues(alpha: 0.28) : LM.line),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null)
            Icon(icon, size: 13, color: fg)
          else
            _Dot(color: fg, pulse: on && pulse),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(fontSize: 12, color: fg, fontWeight: FontWeight.w600)),
        ]),
      ),
    );
  }
}

class _Dot extends StatefulWidget {
  const _Dot({required this.color, required this.pulse});
  final Color color;
  final bool pulse;
  @override
  State<_Dot> createState() => _DotState();
}

class _DotState extends State<_Dot> with SingleTickerProviderStateMixin {
  late final AnimationController _a = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));
  @override
  void didUpdateWidget(covariant _Dot old) {
    super.didUpdateWidget(old);
    widget.pulse ? _a.repeat(reverse: true) : _a.stop();
  }

  @override
  void initState() {
    super.initState();
    if (widget.pulse) _a.repeat(reverse: true);
  }

  @override
  void dispose() {
    _a.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
        opacity: widget.pulse ? Tween(begin: 0.35, end: 1.0).animate(_a) : const AlwaysStoppedAnimation(1),
        child: Container(width: 8, height: 8, decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle)),
      );
}

class Panel extends StatelessWidget {
  const Panel({super.key, required this.title, required this.child, this.trailing, this.icon});
  final String title;
  final Widget child;
  final Widget? trailing;
  final IconData? icon;
  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: LM.surface,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: LM.line, width: 1.2),
        ),
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            if (icon != null) ...[Icon(icon, size: 18, color: LM.teal), const SizedBox(width: 8)],
            Expanded(
              child: Text(
                title,
                style: const TextStyle(fontSize: 16, color: LM.text, fontWeight: FontWeight.w700),
              ),
            ),
            ?trailing,
          ]),
          const SizedBox(height: 12),
          child,
        ]),
      );
}

class PersistenceBadge extends StatelessWidget {
  const PersistenceBadge(this.p, {super.key});
  final Persistence p;
  @override
  Widget build(BuildContext context) {
    final (label, bg, fg) = switch (p) {
      Persistence.saved => ('Saved', LM.pillNeutralBg, LM.pillNeutralText),
      Persistence.pending => ('Saving…', LM.reviewBg, LM.reviewText),
      Persistence.failed => ('Save failed', const Color(0xFFFEE2E2), LM.rec),
      Persistence.notSaved => ('Not saved', LM.pillNeutralBg, LM.muted),
      Persistence.ephemeral => ('Ephemeral', LM.pillNeutralBg, LM.muted),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(label, style: TextStyle(fontSize: 11.5, color: fg, fontWeight: FontWeight.w600)),
    );
  }
}

class JsonView extends StatelessWidget {
  const JsonView(this.data, {super.key});
  final Object? data;
  @override
  Widget build(BuildContext context) {
    final text = const JsonEncoder.withIndent('  ').convert(data);
    return Stack(children: [
      Container(
        width: double.infinity,
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: LM.bg, borderRadius: BorderRadius.circular(8), border: Border.all(color: LM.line)),
        child: SelectableText(text, style: const TextStyle(fontFamily: LM.mono, fontSize: 11.5, color: LM.text, height: 1.35)),
      ),
      Positioned(
        right: 2,
        top: 2,
        child: IconButton(
          tooltip: 'Copy JSON',
          iconSize: 16,
          icon: const Icon(Icons.copy, color: LM.muted),
          onPressed: () => Clipboard.setData(ClipboardData(text: text)),
        ),
      ),
    ]);
  }
}

String hhmmss(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}:${t.second.toString().padLeft(2, '0')}';

String hhmm(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

IconData modalityIcon(String m) => switch (m) {
      'speech' => Icons.mic_none_rounded,
      'image' => Icons.camera_alt_outlined,
      'video' => Icons.camera_alt_outlined,
      'text' => Icons.edit_note,
      _ => Icons.assignment_turned_in_outlined,
    };

/// Renders the microfluidic chip & pipette inspection graphic with real bounding-box tags
/// following `docs/API_V2.md` coordinate conventions (`box_2d` 0..1000 vs `bbox` in pixels).
class MicrofluidicEvidenceCanvas extends StatelessWidget {
  const MicrofluidicEvidenceCanvas({
    super.key,
    required this.perception,
    this.compact = false,
  });

  final Map<String, dynamic>? perception;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFFDADFD9), Color(0xFFC5CCC6)],
        ),
        borderRadius: BorderRadius.circular(compact ? 8 : 10),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(compact ? 8 : 10),
        child: Stack(
          fit: StackFit.expand,
          children: [
            CustomPaint(painter: _MicrofluidicChipPainter()),
            CameraBoundingBoxOverlay(
              perception: perception,
              compact: compact,
              showIllustratedPipette: true,
            ),
          ],
        ),
      ),
    );
  }
}

class _MicrofluidicChipPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // Subtle slide glass body
    final chipRect = Rect.fromLTWH(w * 0.16, h * 0.30, w * 0.62, h * 0.48);
    final chipFill = Paint()..color = const Color(0xFFD5DBD5).withValues(alpha: 0.75);
    final chipBorder = Paint()
      ..color = const Color(0xFF7D8B86)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    canvas.drawRRect(RRect.fromRectAndRadius(chipRect, const Radius.circular(3)), chipFill);
    canvas.drawRRect(RRect.fromRectAndRadius(chipRect, const Radius.circular(3)), chipBorder);

    // Microfluidic channels & branches
    final channelPaint = Paint()
      ..color = const Color(0xFF6B7975)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;

    final midY = h * 0.55;
    // Central parallel microchannels
    for (final dy in [-3.0, 0.0, 3.0]) {
      canvas.drawLine(Offset(w * 0.34, midY + dy), Offset(w * 0.61, midY + dy), channelPaint);
    }

    // Left inlet tree
    final leftPorts = [
      Offset(w * 0.25, h * 0.54),
      Offset(w * 0.28, h * 0.43),
      Offset(w * 0.28, h * 0.65),
      Offset(w * 0.36, h * 0.43),
      Offset(w * 0.36, h * 0.65),
    ];
    for (final pt in leftPorts) {
      canvas.drawLine(pt, Offset(w * 0.38, midY), channelPaint);
    }

    // Right outlet branches
    final rightPorts = [
      Offset(w * 0.65, h * 0.41),
      Offset(w * 0.65, h * 0.67),
    ];
    for (final pt in rightPorts) {
      canvas.drawLine(Offset(w * 0.59, midY), pt, channelPaint);
    }

    // Port reservoirs (ports & capture chambers)
    final portFill = Paint()..color = const Color(0xFFB3BDB8);
    final portRing = Paint()
      ..color = const Color(0xFF43534F)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6;
    final allPorts = [
      ...leftPorts,
      ...rightPorts,
      Offset(w * 0.435, h * 0.43),
      Offset(w * 0.435, h * 0.60),
      Offset(w * 0.59, h * 0.48),
    ];
    for (final pt in allPorts) {
      canvas.drawCircle(pt, w * 0.015, portFill);
      canvas.drawCircle(pt, w * 0.015, portRing);
    }

    // Pipette tip entering from top-right
    final pipPath = Path()
      ..moveTo(w * 0.80, h * 0.02)
      ..lineTo(w * 0.87, h * 0.08)
      ..lineTo(w * 0.53, h * 0.43)
      ..lineTo(w * 0.51, h * 0.41)
      ..close();
    final pipPaint = Paint()
      ..shader = const LinearGradient(
        colors: [Color(0xFF3E6C70), Color(0xFF83AEB2), Color(0xFF2B5256)],
      ).createShader(Rect.fromLTWH(w * 0.50, 0, w * 0.40, h * 0.45));
    canvas.drawPath(pipPath, pipPaint);
    canvas.drawPath(
      pipPath,
      Paint()
        ..color = const Color(0xFF29484B)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.1,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// Draws Gemini `box_2d` (`[ymin, xmin, ymax, xmax]` 0..1000) and Specialist `bbox` (`[x1, y1, x2, y2]` pixels)
/// per `docs/API_V2.md`.
class CameraBoundingBoxOverlay extends StatelessWidget {
  const CameraBoundingBoxOverlay({
    super.key,
    required this.perception,
    this.compact = false,
    this.showIllustratedPipette = false,
  });

  final Map<String, dynamic>? perception;
  final bool compact;
  final bool showIllustratedPipette;

  @override
  Widget build(BuildContext context) {
    final p = perception;
    if (p == null) return const SizedBox.shrink();

    final baseObjects = ((p['objects'] as List?) ?? const []).cast<Map>();
    final hasPipette = baseObjects.any((o) => '${o['label'] ?? ''}'.toLowerCase().contains('pipette'));
    final rawObjects = <Map>[
      ...baseObjects,
      if (showIllustratedPipette && !hasPipette)
        const {'label': 'Pipette', 'certainty': 'certain', 'box_2d': [65, 515, 455, 795]},
    ];
    final spec = (p['specialist'] as Map?)?.cast<String, dynamic>();
    final rawBubbles = ((spec?['detections'] as List?) ?? const []).cast<Map>();
    final imgW = ((spec?['image_width'] as num?) ?? 640).toDouble();
    final imgH = ((spec?['image_height'] as num?) ?? 360).toDouble();

    return LayoutBuilder(
      builder: (context, constraints) {
        final w = constraints.maxWidth;
        final h = constraints.maxHeight;
        if (w <= 0 || h <= 0) return const SizedBox.shrink();

        final children = <Widget>[];

        // 1. Gemini general objects (`box_2d` = [ymin, xmin, ymax, xmax] in 0..1000)
        for (final obj in rawObjects) {
          final box = obj['box_2d'];
          if (box is! List || box.length < 4) continue;
          final rawLabel = '${obj['label'] ?? 'Object'}';
          // Skip duplicate generic bubble box if specialist detections are present
          if (rawBubbles.isNotEmpty && rawLabel.toLowerCase().contains('bubble')) continue;

          final ymin = (box[0] as num).toDouble().clamp(0, 1000);
          final xmin = (box[1] as num).toDouble().clamp(0, 1000);
          final ymax = (box[2] as num).toDouble().clamp(0, 1000);
          final xmax = (box[3] as num).toDouble().clamp(0, 1000);

          final left = (xmin / 1000.0) * w;
          final top = (ymin / 1000.0) * h;
          final bw = ((xmax - xmin) / 1000.0 * w).clamp(24.0, w - left);
          final bh = ((ymax - ymin) / 1000.0 * h).clamp(20.0, h - top);
          final label = _cleanObjectLabel(rawLabel);

          children.add(
            Positioned(
              left: left,
              top: top,
              width: bw,
              height: bh,
              child: IgnorePointer(
                child: Container(
                  decoration: BoxDecoration(
                    border: Border.all(color: LM.teal, width: compact ? 1.1 : 1.5),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
            ),
          );
          if (!compact) {
            children.add(
              Positioned(
                left: left,
                top: (top - 20).clamp(2.0, h - 22.0),
                child: IgnorePointer(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: LM.teal,
                      borderRadius: BorderRadius.circular(3),
                    ),
                    child: Text(
                      label,
                      style: const TextStyle(color: Colors.white, fontSize: 10.5, fontWeight: FontWeight.w600),
                    ),
                  ),
                ),
              ),
            );
          }
        }

        // 2. Specialist bubble detections (`bbox` = [x1, y1, x2, y2] in pixels of image_width x image_height)
        for (var idx = 0; idx < rawBubbles.length; idx++) {
          final det = rawBubbles[idx];
          final bbox = det['bbox'];
          if (bbox is! List || bbox.length < 4) continue;
          final x1 = (bbox[0] as num).toDouble();
          final y1 = (bbox[1] as num).toDouble();
          final x2 = (bbox[2] as num).toDouble();
          final y2 = (bbox[3] as num).toDouble();

          final left = ((x1 / imgW) * w).clamp(4.0, w - 28.0);
          final top = ((y1 / imgH) * h).clamp(4.0, h - 28.0);
          final bw = (((x2 - x1) / imgW) * w).clamp(18.0, w - left);
          final bh = (((y2 - y1) / imgH) * h).clamp(18.0, h - top);

          children.add(
            Positioned(
              left: left,
              top: top,
              width: bw,
              height: bh,
              child: IgnorePointer(
                child: Container(
                  decoration: BoxDecoration(
                    border: Border.all(color: LM.reviewBorder, width: compact ? 1.2 : 1.6),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
            ),
          );

          if (!compact) {
            final pillTop = idx.isEven ? (top - 22).clamp(4.0, h - 24.0) : (top + bh + 3).clamp(4.0, h - 24.0);
            children.add(
              Positioned(
                left: (left - 8).clamp(4.0, w - 74.0),
                top: pillTop,
                child: IgnorePointer(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: LM.reviewBg,
                      borderRadius: BorderRadius.circular(4),
                      border: Border.all(color: LM.reviewBorder),
                    ),
                    child: const Text(
                      'Bubble ?',
                      style: TextStyle(color: LM.reviewText, fontSize: 10.5, fontWeight: FontWeight.w700),
                    ),
                  ),
                ),
              ),
            );
          }
        }

        return Stack(fit: StackFit.expand, children: children);
      },
    );
  }

  String _cleanObjectLabel(String raw) {
    final lower = raw.toLowerCase();
    if (lower.contains('chip')) return 'Chip';
    if (lower.contains('pipette')) return 'Pipette';
    if (lower.contains('inlet')) return 'Inlet';
    return raw.isNotEmpty ? '${raw[0].toUpperCase()}${raw.substring(1)}' : 'Object';
  }
}

/// Interactive Bottom Sheet for All Protocol Steps (`Step X of N` -> `All steps`).
Future<void> showProtocolStepsSheet(BuildContext context, AppController c) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: LM.surface,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (ctx) {
      final steps = c.protocolSteps;
      final activeId = c.activeStepIdResolved;
      return DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.72,
        minChildSize: 0.45,
        maxChildSize: 0.92,
        builder: (_, scrollController) {
          return Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 4,
                    decoration: BoxDecoration(color: LM.line, borderRadius: BorderRadius.circular(2)),
                  ),
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(c.experimentDisplayTitle, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: LM.text)),
                          const SizedBox(height: 2),
                          Text('Protocol v${c.protocol?['version'] ?? 1} · Tap a step to set active context',
                              style: const TextStyle(fontSize: 12.5, color: LM.muted)),
                        ],
                      ),
                    ),
                    IconButton(onPressed: () => Navigator.pop(ctx), icon: const Icon(Icons.close)),
                  ],
                ),
                const Divider(height: 20),
                Expanded(
                  child: steps.isEmpty
                      ? const Center(child: Text('No protocol steps loaded.', style: TextStyle(color: LM.muted)))
                      : ListView.builder(
                          controller: scrollController,
                          itemCount: steps.length,
                          itemBuilder: (_, index) {
                            final s = steps[index];
                            final id = '${s['id']}';
                            final selected = id == activeId;
                            return Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: InkWell(
                                borderRadius: BorderRadius.circular(12),
                                onTap: () async {
                                  c.selectProtocolStep(id);
                                  if (c.recordingId != null) {
                                    try {
                                      await c.updateLiveRecordingState(c.recordingId!, activeStepId: id);
                                    } catch (_) {}
                                  }
                                  if (ctx.mounted) Navigator.pop(ctx);
                                },
                                child: Container(
                                  padding: const EdgeInsets.all(12),
                                  decoration: BoxDecoration(
                                    color: selected ? LM.softTeal : LM.surface,
                                    borderRadius: BorderRadius.circular(12),
                                    border: Border.all(color: selected ? LM.teal : LM.line, width: selected ? 1.5 : 1),
                                  ),
                                  child: Row(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                        decoration: BoxDecoration(
                                          color: selected ? LM.teal : LM.bg,
                                          borderRadius: BorderRadius.circular(6),
                                        ),
                                        child: Text(
                                          'Step ${index + 1}',
                                          style: TextStyle(
                                            fontSize: 11.5,
                                            fontWeight: FontWeight.w700,
                                            color: selected ? Colors.white : LM.text,
                                          ),
                                        ),
                                      ),
                                      const SizedBox(width: 10),
                                      Expanded(
                                        child: Column(
                                          crossAxisAlignment: CrossAxisAlignment.start,
                                          children: [
                                            Text(
                                              '${s['action'] ?? s['description']}',
                                              style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: LM.text),
                                            ),
                                            const SizedBox(height: 3),
                                            Text('${s['description']}', style: const TextStyle(fontSize: 13, color: LM.muted)),
                                            if (s['tolerance'] != null) ...[
                                              const SizedBox(height: 4),
                                              Text('Rule: ${s['tolerance']}', style: const TextStyle(fontSize: 11.5, color: LM.teal)),
                                            ],
                                          ],
                                        ),
                                      ),
                                      if (selected) const Icon(Icons.check_circle, color: LM.teal, size: 20),
                                    ],
                                  ),
                                ),
                              ),
                            );
                          },
                        ),
                ),
              ],
            ),
          );
        },
      );
    },
  );
}

/// Interactive Bottom Sheet for Pending Reviews, Human Sign-Off (`Accept`, `Dispute`, `Correct`, `Reject`),
/// Dependency Impact, and Deep Investigation (`POST /api/investigate`).
Future<void> showReviewObservationSheet(
  BuildContext context,
  AppController c, {
  String? targetObservationId,
  String? initialSummary,
  String? initialChannel,
  String? initialStep,
}) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: LM.surface,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (ctx) => _ReviewObservationSheet(
      c: c,
      targetObservationId: targetObservationId,
      initialSummary: initialSummary,
      initialChannel: initialChannel,
      initialStep: initialStep,
    ),
  );
}

class _ReviewObservationSheet extends StatefulWidget {
  const _ReviewObservationSheet({
    required this.c,
    this.targetObservationId,
    this.initialSummary,
    this.initialChannel,
    this.initialStep,
  });

  final AppController c;
  final String? targetObservationId;
  final String? initialSummary;
  final String? initialChannel;
  final String? initialStep;

  @override
  State<_ReviewObservationSheet> createState() => _ReviewObservationSheetState();
}

class _ReviewObservationSheetState extends State<_ReviewObservationSheet> {
  List<Map<String, dynamic>> _pending = [];
  bool _loading = true;
  bool _investigating = false;
  Map<String, dynamic>? _investigationResult;
  final _correctionCtl = TextEditingController();
  bool _showCorrectionInput = false;

  @override
  void initState() {
    super.initState();
    _loadPending();
  }

  @override
  void dispose() {
    _correctionCtl.dispose();
    super.dispose();
  }

  Future<void> _loadPending() async {
    setState(() => _loading = true);
    try {
      final list = await widget.c.fetchPendingReviews();
      if (mounted) setState(() => _pending = list);
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _submitDecision(String obsId, String action, {Map<String, dynamic>? correction}) async {
    await widget.c.reviewObservation(obsId, action, correction: correction);
    await _loadPending();
    if (mounted && _pending.isEmpty) {
      Navigator.pop(context);
    }
  }

  Future<void> _runDeepInvestigation(String? obsId, String? stepId, String summary) async {
    setState(() => _investigating = true);
    try {
      final res = await widget.c.runInvestigation(
        observationId: obsId,
        stepId: stepId ?? widget.c.activeStepIdResolved,
        question: summary.isNotEmpty ? summary : 'Why did this microfluidic channel discrepancy occur?',
      );
      if (mounted) setState(() => _investigationResult = res);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Investigation error: $e')));
      }
    }
    if (mounted) setState(() => _investigating = false);
  }

  @override
  Widget build(BuildContext context) {
    final item = _pending.isNotEmpty ? _pending.first : null;
    final obsId = widget.targetObservationId ?? '${item?['observation_id'] ?? ''}';
    final summary = widget.initialSummary ??
        '${item?['spoken_response'] ?? item?['rationale'] ?? 'Two bubble candidates marked for review in selected channel.'}';
    final stepId = widget.initialStep ?? '${item?['step_id'] ?? widget.c.activeStepIdResolved}';
    final affected = (item?['affected_structured'] as Map?)?.cast<String, dynamic>() ?? const {};
    final channels = ((affected['channels'] as List?) ?? [widget.initialChannel ?? widget.c.activeChannelIdResolved]).join(', ');
    final samples = ((affected['samples'] as List?) ?? const ['S02']).join(', ');
    final results = ((affected['derived_values'] as List?) ?? const ['result_S02']).join(', ');
    final violated = ((item?['violated_constraints'] as List?) ?? const ['c_01']).join(', ');

    return Padding(
      padding: EdgeInsets.fromLTRB(16, 12, 16, MediaQuery.of(context).viewInsets.bottom + 20),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(color: LM.line, borderRadius: BorderRadius.circular(2)),
              ),
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: LM.reviewBg,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: LM.reviewBorder),
                  ),
                  child: Text(
                    _pending.isNotEmpty ? '${_pending.length} Pending Review' : 'Observation Review',
                    style: const TextStyle(color: LM.reviewText, fontSize: 12, fontWeight: FontWeight.w700),
                  ),
                ),
                const Spacer(),
                IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.close)),
              ],
            ),
            const SizedBox(height: 8),
            const Text('Human-in-the-Loop Sign-Off', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800, color: LM.text)),
            const SizedBox(height: 4),
            const Text(
              'Original observations are immutable. Your decision appends an audited review record.',
              style: TextStyle(fontSize: 12.5, color: LM.muted),
            ),
            const SizedBox(height: 14),
            if (_loading)
              const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()))
            else ...[
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: LM.reviewBg,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: LM.reviewBorder),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(summary, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: LM.reviewText)),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        _tagChip('Rule: $violated', LM.surface, LM.reviewText),
                        if (channels.isNotEmpty) _tagChip('Channel: $channels', LM.surface, LM.teal),
                        if (samples.isNotEmpty) _tagChip('Sample: $samples', LM.surface, LM.text),
                        if (results.isNotEmpty) _tagChip('May affect: $results', LM.surface, LM.rec),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilledButton.icon(
                    onPressed: obsId.isEmpty ? null : () => _submitDecision(obsId, 'accept'),
                    icon: const Icon(Icons.check_circle_outline, size: 18),
                    label: const Text('Accept'),
                  ),
                  OutlinedButton.icon(
                    onPressed: obsId.isEmpty ? null : () => _submitDecision(obsId, 'dispute'),
                    icon: const Icon(Icons.flag_outlined, size: 18),
                    label: const Text('Dispute'),
                  ),
                  OutlinedButton.icon(
                    onPressed: () => setState(() => _showCorrectionInput = !_showCorrectionInput),
                    icon: const Icon(Icons.edit_outlined, size: 18),
                    label: const Text('Correct'),
                  ),
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(foregroundColor: LM.rec),
                    onPressed: obsId.isEmpty ? null : () => _submitDecision(obsId, 'reject'),
                    icon: const Icon(Icons.cancel_outlined, size: 18),
                    label: const Text('Reject'),
                  ),
                ],
              ),
              if (_showCorrectionInput) ...[
                const SizedBox(height: 12),
                TextField(
                  controller: _correctionCtl,
                  maxLines: 2,
                  decoration: const InputDecoration(
                    labelText: 'Correction note (preserves original observation)',
                    hintText: 'e.g. Scratch on chip surface, not a gas bubble',
                  ),
                ),
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerRight,
                  child: FilledButton(
                    onPressed: obsId.isEmpty || _correctionCtl.text.trim().isEmpty
                        ? null
                        : () => _submitDecision(obsId, 'correct', correction: {'summary': _correctionCtl.text.trim()}),
                    child: const Text('Save correction'),
                  ),
                ),
              ],
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: _investigating ? null : () => _runDeepInvestigation(obsId.isEmpty ? null : obsId, stepId, summary),
                icon: _investigating
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.biotech_outlined, color: LM.teal),
                label: const Text('Investigate discrepancy (PubMed · UniProt · PubChem)'),
              ),
              if (_investigationResult != null) ...[
                const SizedBox(height: 10),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: LM.softTeal,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: LM.line),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Multi-Database Scientific Investigation',
                          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: LM.teal)),
                      const SizedBox(height: 4),
                      Text('${_investigationResult!['spoken_summary'] ?? ''}', style: const TextStyle(fontSize: 12.5, color: LM.text)),
                      const SizedBox(height: 6),
                      for (final rec in ((_investigationResult!['recommended_actions'] as List?) ?? const []).take(3))
                        Padding(
                          padding: const EdgeInsets.only(bottom: 3),
                          child: Text('$rec', style: const TextStyle(fontSize: 12, color: LM.muted)),
                        ),
                    ],
                  ),
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }

  Widget _tagChip(String text, Color bg, Color fg) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: LM.line),
        ),
        child: Text(text, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: fg)),
      );
}

class FeedTile extends StatefulWidget {
  const FeedTile(this.item, {super.key});
  final FeedItem item;
  @override
  State<FeedTile> createState() => _FeedTileState();
}

class _FeedTileState extends State<FeedTile> {
  bool open = false;
  @override
  Widget build(BuildContext context) {
    final i = widget.item;
    final accent = i.isError ? LM.rec : (i.persistence == Persistence.saved ? LM.teal : LM.line);
    return InkWell(
      onTap: () => setState(() => open = !open),
      borderRadius: BorderRadius.circular(10),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: LM.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border(left: BorderSide(color: accent, width: 3)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(modalityIcon(i.modality), size: 15, color: i.isError ? LM.rec : LM.teal),
            const SizedBox(width: 6),
            Text(hhmm(i.time), style: const TextStyle(fontFamily: LM.mono, fontSize: 11.5, color: LM.muted)),
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                i.eventType,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: LM.text),
              ),
            ),
            const Spacer(),
            PersistenceBadge(i.persistence),
          ]),
          const SizedBox(height: 6),
          Text(i.sourceText, maxLines: open ? null : 3, overflow: open ? null : TextOverflow.ellipsis),
          if (open && (i.raw ?? i.structured) != null) ...[
            const SizedBox(height: 8),
            JsonView(i.raw ?? i.structured),
          ],
        ]),
      ),
    );
  }
}
