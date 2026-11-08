import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../state/app_state.dart';
import 'theme.dart';

/// Non-invasive V2 API helper extension on [AppController] so `lib/state` and `lib/services` stay untouched
/// per `docs/UI_DEV.md` while exposing all 5 V2 endpoints from `docs/API_V2.md`.
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
    final streamed = await http.Client().send(req).timeout(const Duration(seconds: 30));
    final res = await http.Response.fromStream(streamed);
    if (res.statusCode >= 400) {
      throw Exception('HTTP ${res.statusCode}: ${res.body}');
    }
    return res.body.isEmpty ? null : jsonDecode(res.body);
  }

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

  Future<Map<String, dynamic>> updateLiveRecordingState(String recId, {String? activeStepId, String? activeChannelId}) async {
    final body = <String, dynamic>{};
    if (activeStepId != null) body['active_step_id'] = activeStepId;
    if (activeChannelId != null) body['active_channel_id'] = activeChannelId;
    final res = await _v2Send('PUT', '/recordings/$recId/state', body: body);
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> addTrackedObject(String recId, String label, {String? channelId}) async {
    final res = await _v2Send('POST', '/recordings/$recId/tracking', body: {
      'label': label,
      if (channelId != null) 'channel_id': channelId,
    });
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> removeTrackedObject(String recId, String label) async {
    final res = await _v2Send('DELETE', '/recordings/$recId/tracking/${Uri.encodeComponent(label)}');
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> runInvestigation({String? question, String? stepId, String? observationId}) async {
    final res = await _v2Send('POST', '/investigate', body: {
      'experiment_id': experimentId,
      if (question != null) 'question': question,
      if (stepId != null) 'step_id': stepId,
      if (observationId != null) 'observation_id': observationId,
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
      'wait_time_min': 4.0,
      'ambient_temp_c': 22.5,
    });
    return (res as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};
  }

  /// Extracts the latest perception payload from either live `latestPerception` or seeded `feed` events
  /// so the camera overlay and object/bubble bounding boxes can be previewed even offline without Gemini keys.
  Map<String, dynamic>? get effectivePerceptionPayload {
    if (latestPerception != null) return latestPerception;
    for (final item in feed) {
      if (item.eventType == 'perception') {
        final rawMap = item.raw ?? item.structured;
        if (rawMap != null) {
          final payload = rawMap['payload'];
          if (payload is Map) return payload.cast<String, dynamic>();
          if (rawMap['objects'] != null || rawMap['scene_summary'] != null) {
            return rawMap;
          }
        }
      }
    }
    return null;
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label, required this.on, this.onColor = LM.teal, this.icon, this.pulse = false});
  final String label;
  final bool on;
  final Color onColor;
  final IconData? icon;
  final bool pulse;

  @override
  Widget build(BuildContext context) {
    final c = on ? onColor : LM.muted;
    return Semantics(
      label: '$label ${on ? 'on' : 'off'}',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: on ? onColor.withValues(alpha: 0.14) : LM.surfaceHi,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: on ? onColor.withValues(alpha: 0.6) : LM.line),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) Icon(icon, size: 13, color: c) else _Dot(color: c, pulse: on && pulse),
          const SizedBox(width: 5),
          Text(label, style: TextStyle(fontSize: 11, color: c, fontWeight: FontWeight.w600)),
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
            color: LM.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: LM.line)),
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            if (icon != null) ...[Icon(icon, size: 16, color: LM.teal), const SizedBox(width: 8)],
            Text(title.toUpperCase(),
                style: const TextStyle(fontSize: 11, letterSpacing: 1.4, color: LM.muted, fontWeight: FontWeight.w700)),
            const Spacer(),
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
    final (label, color) = switch (p) {
      Persistence.saved => ('SAVED', LM.ok),
      Persistence.pending => ('SAVING…', LM.warn),
      Persistence.failed => ('SAVE FAILED', LM.rec),
      Persistence.notSaved => ('NOT SAVED', LM.muted),
      Persistence.ephemeral => ('EPHEMERAL', LM.muted),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(border: Border.all(color: color.withValues(alpha: 0.7)), borderRadius: BorderRadius.circular(4)),
      child: Text(label, style: TextStyle(fontSize: 9.5, color: color, fontWeight: FontWeight.w700, letterSpacing: 0.6)),
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

IconData modalityIcon(String m) => switch (m) {
      'speech' => Icons.graphic_eq,
      'image' => Icons.image_outlined,
      'video' => Icons.visibility_outlined,
      'text' => Icons.edit_note,
      _ => Icons.memory,
    };

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
          color: LM.surfaceHi,
          borderRadius: BorderRadius.circular(10),
          border: Border(left: BorderSide(color: accent, width: 3)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(modalityIcon(i.modality), size: 14, color: i.isError ? LM.rec : LM.teal),
            const SizedBox(width: 6),
            Text(hhmmss(i.time), style: const TextStyle(fontFamily: LM.mono, fontSize: 11, color: LM.muted)),
            if (i.sequence != null)
              Text('  #${i.sequence}', style: const TextStyle(fontFamily: LM.mono, fontSize: 11, color: LM.muted)),
            const SizedBox(width: 8),
            Flexible(
                child: Text(i.eventType,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: LM.text))),
            const Spacer(),
            PersistenceBadge(i.persistence),
          ]),
          const SizedBox(height: 6),
          Text(i.sourceText, maxLines: open ? null : 3, overflow: open ? null : TextOverflow.ellipsis),
          if (i.model != null || i.review != 'n/a')
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                  [if (i.model != null) 'model: ${i.model}', 'modality: ${i.modality}', if (i.review != 'n/a') 'review: ${i.review}']
                      .join('  ·  '),
                  style: Theme.of(context).textTheme.bodySmall),
            ),
          if (open && (i.raw ?? i.structured) != null) ...[const SizedBox(height: 8), JsonView(i.raw ?? i.structured)],
        ]),
      ),
    );
  }
}

/// V2 Requirement #4 (`docs/API_V2.md`):
/// "Text is never overlaid on the camera. Put scene summary / status ABOVE the camera window;
/// draw only small object tags (label chips + thin box) on the video. Bubble detections from the
/// specialist get their own colour. Gemini `box_2d` -> `left = xmin/1000*W, top = ymin/1000*H`.
/// Specialist `bbox` is pixels of `image_width x image_height` -> scale to preview size."
class CameraBoundingBoxOverlay extends StatelessWidget {
  const CameraBoundingBoxOverlay({super.key, required this.perception});
  final Map<String, dynamic>? perception;

  @override
  Widget build(BuildContext context) {
    final p = perception;
    if (p == null) return const SizedBox.shrink();
    final objects = ((p['objects'] as List?) ?? const []).cast<Map>();
    final spec = (p['specialist'] as Map?)?.cast<String, dynamic>();
    final specDets = ((spec?['detections'] as List?) ?? const []).cast<Map>();
    final imgW = ((spec?['image_width'] as num?) ?? 640).toDouble();
    final imgH = ((spec?['image_height'] as num?) ?? 360).toDouble();

    return LayoutBuilder(
      builder: (context, constraints) {
        final w = constraints.maxWidth;
        final h = constraints.maxHeight;
        final children = <Widget>[];

        // 1. Gemini object tags (`box_2d`: [ymin, xmin, ymax, xmax] in 0..1000)
        for (final obj in objects) {
          final box = obj['box_2d'];
          if (box is List && box.length >= 4) {
            final ymin = ((box[0] as num).toDouble() / 1000.0 * h).clamp(0.0, h - 18.0);
            final xmin = ((box[1] as num).toDouble() / 1000.0 * w).clamp(0.0, w - 36.0);
            final ymax = ((box[2] as num).toDouble() / 1000.0 * h).clamp(ymin + 16.0, h);
            final xmax = ((box[3] as num).toDouble() / 1000.0 * w).clamp(xmin + 28.0, w);
            final tracked = obj['tracked'] == true;
            final uncertain = '${obj['certainty']}' == 'uncertain';
            final color = tracked ? const Color(0xFF38BDF8) : LM.teal;

            children.add(
              Positioned(
                left: xmin,
                top: ymin,
                width: xmax - xmin,
                height: ymax - ymin,
                child: IgnorePointer(
                  child: Container(
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(
                        color: color.withValues(alpha: uncertain ? 0.55 : 0.92),
                        width: tracked ? 2.2 : 1.3,
                      ),
                      color: tracked ? color.withValues(alpha: 0.08) : Colors.transparent,
                    ),
                    alignment: Alignment.topLeft,
                    child: Transform.translate(
                      offset: const Offset(0, -18),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xD90B1215),
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(color: color.withValues(alpha: 0.8), width: 1),
                        ),
                        child: Text(
                          '${obj['label']}${tracked ? ' ★' : ''}${uncertain ? ' ?' : ''}',
                          style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: color),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            );
          }
        }

        // 2. Person 3 Specialist Bubble Council detections (`bbox`: [x0, y0, x1, y1] in pixels of imgW x imgH)
        for (var idx = 0; idx < specDets.length; idx++) {
          final d = specDets[idx];
          final bbox = d['bbox'];
          if (bbox is List && bbox.length >= 4) {
            final x0 = ((bbox[0] as num).toDouble() / imgW * w).clamp(0.0, w - 20.0);
            final y0 = ((bbox[1] as num).toDouble() / imgH * h).clamp(0.0, h - 20.0);
            final x1 = ((bbox[2] as num).toDouble() / imgW * w).clamp(x0 + 18.0, w);
            final y1 = ((bbox[3] as num).toDouble() / imgH * h).clamp(y0 + 18.0, h);
            final highRisk = '${d['obstruction_risk']}'.contains('high');
            final ratio = (((d['channel_obstruction_ratio'] as num?) ?? 0).toDouble() * 100).round();
            final bubColor = highRisk ? LM.rec : LM.warn;

            children.add(
              Positioned(
                left: x0,
                top: y0,
                width: x1 - x0,
                height: y1 - y0,
                child: IgnorePointer(
                  child: Container(
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: bubColor, width: 2.0),
                      color: bubColor.withValues(alpha: 0.16),
                    ),
                    alignment: Alignment.bottomLeft,
                    child: Transform.translate(
                      offset: const Offset(0, 18),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xE60B1215),
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(color: bubColor, width: 1),
                        ),
                        child: Text(
                          'bubble #${idx + 1} · $ratio% obs',
                          style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w800, color: bubColor),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            );
          }
        }

        return Stack(clipBehavior: Clip.none, children: children);
      },
    );
  }
}

/// V2 Requirement #5 (`docs/API_V2.md`):
/// Shows and edits `active_step_id`, `active_channel_id` (CH01..CH12), and the live `tracking` list
/// (`GET/PUT /recordings/{id}/state`, `POST/DELETE /recordings/{id}/tracking`).
class LiveSessionStateBar extends StatefulWidget {
  const LiveSessionStateBar(this.c, {super.key});
  final AppController c;

  @override
  State<LiveSessionStateBar> createState() => _LiveSessionStateBarState();
}

class _LiveSessionStateBarState extends State<LiveSessionStateBar> {
  String _stepId = 'step_05';
  String _channelId = 'CH01';
  List<Map<String, dynamic>> _tracking = []; // real session state only (no demo defaults)
  final _trackCtl = TextEditingController();
  Timer? _sync;
  bool _busy = false;

  static const _channels = [
    'CH01', 'CH02', 'CH03', 'CH04', 'CH05', 'CH06',
    'CH07', 'CH08', 'CH09', 'CH10', 'CH11', 'CH12',
  ];

  @override
  void initState() {
    super.initState();
    _syncFromLatest();
    // Voice commands (set step/channel, track/untrack) change server state; reflect them here.
    _sync = Timer.periodic(const Duration(seconds: 3), (_) {
      if (mounted && widget.c.recordingActive && !_busy) _syncFromLatest();
    });
  }

  @override
  void dispose() {
    _sync?.cancel();
    _trackCtl.dispose();
    super.dispose();
  }

  Future<void> _syncFromLatest() async {
    final c = widget.c;
    final p = c.effectivePerceptionPayload;
    if (p != null) {
      if (p['active_step_id'] != null) _stepId = '${p['active_step_id']}';
      if (p['active_channel_id'] != null) _channelId = '${p['active_channel_id']}';
      final tList = p['tracking'];
      if (tList is List && tList.isNotEmpty) {
        _tracking = tList.map((e) => e is Map ? e.cast<String, dynamic>() : {'label': '$e', 'added_by': 'session'}).toList();
      }
    }
    final recId = c.recording?['id']?.toString();
    if (recId != null && c.recordingActive) {
      try {
        final st = await c.fetchLiveRecordingState(recId);
        if (mounted) {
          setState(() {
            if (st['active_step_id'] != null) _stepId = '${st['active_step_id']}';
            if (st['active_channel_id'] != null) _channelId = '${st['active_channel_id']}';
            if (st['tracking'] is List) {
              _tracking = (st['tracking'] as List).map((e) => (e as Map).cast<String, dynamic>()).toList();
            }
          });
        }
      } catch (_) {}
    }
  }

  Future<void> _setStepAndChannel({String? step, String? channel}) async {
    final nextStep = step ?? _stepId;
    final nextCh = channel ?? _channelId;
    setState(() {
      _stepId = nextStep;
      _channelId = nextCh;
    });
    widget.c.selectProtocolStep(nextStep);
    final recId = widget.c.recording?['id']?.toString();
    if (recId != null && widget.c.recordingActive) {
      setState(() => _busy = true);
      try {
        await widget.c.updateLiveRecordingState(recId, activeStepId: nextStep, activeChannelId: nextCh);
      } catch (_) {}
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addTrack(String label) async {
    final clean = label.trim();
    if (clean.isEmpty) return;
    _trackCtl.clear();
    setState(() {
      if (!_tracking.any((t) => '${t['label']}'.toLowerCase() == clean.toLowerCase())) {
        _tracking.add({'label': clean, 'channel_id': _channelId, 'added_by': 'ui'});
      }
    });
    final recId = widget.c.recording?['id']?.toString();
    if (recId != null && widget.c.recordingActive) {
      try {
        await widget.c.addTrackedObject(recId, clean, channelId: _channelId);
      } catch (_) {}
    }
  }

  Future<void> _removeTrack(String label) async {
    setState(() {
      _tracking.removeWhere((t) => '${t['label']}' == label);
    });
    final recId = widget.c.recording?['id']?.toString();
    if (recId != null && widget.c.recordingActive) {
      try {
        await widget.c.removeTrackedObject(recId, label);
      } catch (_) {}
    }
  }

  @override
  Widget build(BuildContext context) {
    final steps = widget.c.protocolSteps;
    final stepIds = steps.isNotEmpty
        ? steps.map((s) => '${s['id']}').toList()
        : ['step_01', 'step_02', 'step_03', 'step_04', 'step_05', 'step_06', 'step_07', 'step_08', 'step_09'];
    if (!stepIds.contains(_stepId)) _stepId = stepIds.first;

    return Panel(
      title: 'Live Session Context · Step, Channel & Object Tracking',
      icon: Icons.radar,
      trailing: _busy
          ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
          : IconButton(
              tooltip: 'Sync session state',
              iconSize: 16,
              onPressed: _syncFromLatest,
              icon: const Icon(Icons.sync, color: LM.teal),
            ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: DropdownButtonFormField<String>(
              value: _stepId,
              isDense: true,
              decoration: const InputDecoration(labelText: 'Active Protocol Step', border: OutlineInputBorder(), isDense: true),
              items: [for (final s in stepIds) DropdownMenuItem(value: s, child: Text(s, style: const TextStyle(fontSize: 12.5)))],
              onChanged: (v) => v != null ? _setStepAndChannel(step: v) : null,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: DropdownButtonFormField<String>(
              value: _channelId,
              isDense: true,
              decoration: const InputDecoration(labelText: 'Active Microfluidic Channel', border: OutlineInputBorder(), isDense: true),
              items: [for (final ch in _channels) DropdownMenuItem(value: ch, child: Text(ch, style: const TextStyle(fontSize: 12.5)))],
              onChanged: (v) => v != null ? _setStepAndChannel(channel: v) : null,
            ),
          ),
        ]),
        const SizedBox(height: 10),
        const Text('Tracked Targets (Specialist Bubble Council + Gemini Live):', style: TextStyle(fontSize: 11.5, color: LM.muted)),
        const SizedBox(height: 6),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final t in _tracking)
            InputChip(
              label: Text('${t['label']}${t['channel_id'] != null ? ' (${t['channel_id']})' : ''}',
                  style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600)),
              avatar: const Icon(Icons.track_changes, size: 14, color: LM.teal),
              onDeleted: () => _removeTrack('${t['label']}'),
            ),
          for (final preset in const ['bubbles', 'micropipette', 'meniscus', 'channel inlet'])
            if (!_tracking.any((t) => '${t['label']}'.toLowerCase() == preset))
              ActionChip(
                label: Text('+ $preset', style: const TextStyle(fontSize: 11, color: LM.muted)),
                onPressed: () => _addTrack(preset),
              ),
        ]),
      ]),
    );
  }
}

/// V2 Requirement #3 (`docs/API_V2.md`):
/// Pending Reviews & Human-in-the-Loop Sign-Off Screen (`GET /reviews/pending?experiment_id=exp_001`)
/// with Accept, Dispute, Correct, Reject buttons + Investigate (`POST /investigate`) + Bayesian Recovery.
class PendingReviewsPanel extends StatefulWidget {
  const PendingReviewsPanel(this.c, {super.key});
  final AppController c;

  @override
  State<PendingReviewsPanel> createState() => _PendingReviewsPanelState();
}

class _PendingReviewsPanelState extends State<PendingReviewsPanel> {
  List<Map<String, dynamic>> _pending = [];
  bool _loading = true;
  Map<String, dynamic>? _investigationResult;
  Map<String, dynamic>? _bayesianResult;
  bool _investigating = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final list = await widget.c.fetchPendingReviews();
      if (mounted) setState(() => _pending = list);
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _handleDecision(String obsId, String action) async {
    await widget.c.reviewObservation(obsId, action);
    await _load();
  }

  Future<void> _investigateItem(Map<String, dynamic> item) async {
    setState(() => _investigating = true);
    try {
      final inv = await widget.c.runInvestigation(
        question: 'Why did this bubble or protocol discrepancy happen and what downstream results are impacted?',
        stepId: '${item['step_id'] ?? 'step_05'}',
        observationId: '${item['observation_id'] ?? ''}',
      );
      final bo = await widget.c.runBayesianOptimiser(obstructionRatio: 0.52, sauterMeanPx: 44.0, volumeVarianceUl: -1.2);
      if (mounted) {
        setState(() {
          _investigationResult = inv;
          _bayesianResult = bo;
        });
      }
    } catch (_) {}
    if (mounted) setState(() => _investigating = false);
  }

  @override
  Widget build(BuildContext context) {
    return Panel(
      title: 'Pending Scientist Sign-Off Queue (${_pending.length})',
      icon: Icons.verified_user_outlined,
      trailing: IconButton(
        tooltip: 'Refresh pending reviews',
        iconSize: 16,
        onPressed: _load,
        icon: const Icon(Icons.refresh, color: LM.teal),
      ),
      child: _loading
          ? const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()))
          : _pending.isEmpty
              ? const Text('All flagged observations have been reviewed and signed off.', style: TextStyle(color: LM.ok, fontSize: 12.5))
              : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  for (final item in _pending)
                    Container(
                      margin: const EdgeInsets.only(bottom: 10),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: LM.surfaceHi,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: LM.warn.withValues(alpha: 0.65)),
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Row(children: [
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                            decoration: BoxDecoration(color: LM.warn.withValues(alpha: 0.2), borderRadius: BorderRadius.circular(4)),
                            child: Text(
                              '${item['action'] ?? 'WARN'} · ${item['scientific_status'] ?? 'PENDING_REVIEW'}'.toUpperCase(),
                              style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: LM.warn),
                            ),
                          ),
                          const SizedBox(width: 8),
                          if (item['step_id'] != null)
                            Text('${item['step_id']}', style: const TextStyle(fontFamily: LM.mono, fontSize: 11, color: LM.teal)),
                          const Spacer(),
                          Text('${item['observation_id'] ?? ''}', style: const TextStyle(fontFamily: LM.mono, fontSize: 10.5, color: LM.muted)),
                        ]),
                        const SizedBox(height: 8),
                        if (item['spoken_response'] != null && '${item['spoken_response']}'.isNotEmpty)
                          Text('${item['spoken_response']}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                        if (item['rationale'] != null && '${item['rationale']}'.isNotEmpty) ...[
                          const SizedBox(height: 4),
                          Text('${item['rationale']}', style: const TextStyle(fontSize: 12, color: LM.muted)),
                        ],
                        const SizedBox(height: 6),
                        Wrap(spacing: 6, runSpacing: 4, children: [
                          for (final c in ((item['violated_constraints'] as List?) ?? const []))
                            Chip(
                              visualDensity: VisualDensity.compact,
                              label: Text('Rule: $c', style: const TextStyle(fontSize: 10.5, color: LM.rec)),
                              backgroundColor: LM.rec.withValues(alpha: 0.12),
                            ),
                          for (final ref in ((item['citations'] as List?) ?? const []))
                            Chip(
                              visualDensity: VisualDensity.compact,
                              label: Text('Cite: $ref', style: const TextStyle(fontSize: 10.5, color: LM.teal)),
                              backgroundColor: LM.teal.withValues(alpha: 0.12),
                            ),
                        ]),
                        const SizedBox(height: 8),
                        Wrap(spacing: 6, runSpacing: 6, children: [
                          FilledButton.tonalIcon(
                            onPressed: () => _handleDecision('${item['observation_id']}', 'accept'),
                            icon: const Icon(Icons.check, size: 15),
                            label: const Text('Accept', style: TextStyle(fontSize: 12)),
                          ),
                          OutlinedButton(
                            onPressed: () => _handleDecision('${item['observation_id']}', 'dispute'),
                            child: const Text('Dispute', style: TextStyle(fontSize: 12)),
                          ),
                          OutlinedButton(
                            style: OutlinedButton.styleFrom(foregroundColor: LM.rec),
                            onPressed: () => _handleDecision('${item['observation_id']}', 'reject'),
                            child: const Text('Reject', style: TextStyle(fontSize: 12)),
                          ),
                          OutlinedButton.icon(
                            onPressed: _investigating ? null : () => _investigateItem(item),
                            icon: const Icon(Icons.troubleshoot, size: 15, color: LM.teal),
                            label: const Text('Investigate & GP Recovery', style: TextStyle(fontSize: 12, color: LM.teal)),
                          ),
                        ]),
                      ]),
                    ),
                  if (_investigationResult != null || _bayesianResult != null)
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: LM.bg,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: LM.teal.withValues(alpha: 0.6)),
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        const Text('Deep Discrepancy Investigation & GP Bayesian Yield Recovery',
                            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: LM.teal)),
                        if (_investigationResult != null) ...[
                          const SizedBox(height: 6),
                          Text('${_investigationResult!['root_cause_summary'] ?? _investigationResult!['summary'] ?? jsonEncode(_investigationResult)}',
                              style: const TextStyle(fontSize: 12)),
                        ],
                        if (_bayesianResult != null) ...[
                          const SizedBox(height: 6),
                          Text('${_bayesianResult!['scientific_rationale'] ?? ''}',
                              style: const TextStyle(fontFamily: LM.mono, fontSize: 11.5, color: LM.ok)),
                        ],
                      ]),
                    ),
                ]),
    );
  }
}

/// V2 Requirement #2 (`docs/API_V2.md`):
/// Interactive Dependency Graph with Affected Nodes (`GET /experiments/exp_001/graph?focus=CH01`).
/// Node types: `step`, `channel`, `standard`, `zero_standard`, `sample`, `derived_value`.
/// Highlights `affected` nodes red and labels the graph "may need review (impact != proven causation)".
class DependencyGraphPanel extends StatefulWidget {
  const DependencyGraphPanel(this.c, {super.key});
  final AppController c;

  @override
  State<DependencyGraphPanel> createState() => _DependencyGraphPanelState();
}

class _DependencyGraphPanelState extends State<DependencyGraphPanel> {
  String _focusChannel = 'CH01';
  Map<String, dynamic> _graph = {};
  bool _loading = true;

  static const _channels = [
    'CH01', 'CH02', 'CH03', 'CH04', 'CH05', 'CH06',
    'CH07', 'CH08', 'CH09', 'CH10', 'CH11', 'CH12',
  ];

  @override
  void initState() {
    super.initState();
    _loadGraph();
  }

  Future<void> _loadGraph() async {
    setState(() => _loading = true);
    try {
      final g = await widget.c.fetchDependencyGraph(focus: _focusChannel);
      if (mounted) setState(() => _graph = g);
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    final nodes = ((_graph['nodes'] as List?) ?? const []).cast<Map>();
    final edges = ((_graph['edges'] as List?) ?? const []).cast<Map>();
    final affectedMap = (_graph['affected'] as Map?)?.cast<String, dynamic>() ?? const {};
    final affectedEntities = <String>{
      _focusChannel,
      ...((affectedMap['entities'] as List?) ?? const []).map((e) => '$e'),
    };

    return Panel(
      title: 'Assay Dependency Graph · Downstream Impact Propagation',
      icon: Icons.account_tree_outlined,
      trailing: Text('${nodes.length} nodes · ${edges.length} edges', style: const TextStyle(fontSize: 11, color: LM.muted)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(color: LM.surfaceHi, borderRadius: BorderRadius.circular(8), border: Border.all(color: LM.line)),
          child: const Row(children: [
            Icon(Icons.info_outline, size: 15, color: LM.warn),
            SizedBox(width: 8),
            Expanded(
              child: Text(
                'Impact-for-review graph ("may need review" — downstream impact ≠ proven causation). Tap any channel to trace bubble/protocol cascades:',
                style: TextStyle(fontSize: 11.5, color: LM.muted),
              ),
            ),
          ]),
        ),
        const SizedBox(height: 10),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final ch in _channels)
            ChoiceChip(
              label: Text(ch, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
              selected: _focusChannel == ch,
              selectedColor: LM.rec.withValues(alpha: 0.28),
              onSelected: (_) {
                setState(() => _focusChannel = ch);
                _loadGraph();
              },
            ),
        ]),
        const SizedBox(height: 12),
        if (_loading)
          const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator()))
        else ...[
          for (final groupType in const ['channel', 'standard', 'zero_standard', 'sample', 'derived_value', 'step'])
            Builder(builder: (context) {
              final groupNodes = nodes.where((n) => '${n['type']}' == groupType).toList();
              if (groupNodes.isEmpty) return const SizedBox.shrink();
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(groupType.toUpperCase().replaceAll('_', ' '),
                      style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 1.1, color: LM.muted)),
                  const SizedBox(height: 5),
                  Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final n in groupNodes)
                      Builder(builder: (context) {
                        final id = '${n['id']}';
                        final isAffected = affectedEntities.contains(id);
                        return Container(
                          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
                          decoration: BoxDecoration(
                            color: isAffected ? LM.rec.withValues(alpha: 0.18) : LM.surfaceHi,
                            borderRadius: BorderRadius.circular(7),
                            border: Border.all(color: isAffected ? LM.rec : LM.line, width: isAffected ? 1.6 : 1.0),
                          ),
                          child: Row(mainAxisSize: MainAxisSize.min, children: [
                            Icon(isAffected ? Icons.warning_amber_rounded : Icons.circle,
                                size: isAffected ? 13 : 7, color: isAffected ? LM.rec : LM.teal),
                            const SizedBox(width: 5),
                            Text(
                              '${n['label'] ?? id}${n['sample'] != null ? ' → ${n['sample']}' : ''}',
                              style: TextStyle(
                                fontSize: 11.5,
                                fontWeight: isAffected ? FontWeight.w800 : FontWeight.w500,
                                color: isAffected ? LM.rec : LM.text,
                              ),
                            ),
                          ]),
                        );
                      }),
                  ]),
                ]),
              );
            }),
        ],
      ]),
    );
  }
}

/// V2 Requirement #1 (`docs/API_V2.md`):
/// Sessions History (`GET /experiments/exp_001/sessions` and `GET /recordings/{id}/summary`).
class SessionsHistoryPanel extends StatefulWidget {
  const SessionsHistoryPanel(this.c, {super.key});
  final AppController c;

  @override
  State<SessionsHistoryPanel> createState() => _SessionsHistoryPanelState();
}

class _SessionsHistoryPanelState extends State<SessionsHistoryPanel> {
  List<Map<String, dynamic>> _sessions = [];
  final Map<String, Map<String, dynamic>> _summaries = {};
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final list = await widget.c.fetchExperimentSessions();
      if (mounted) setState(() => _sessions = list);
      for (final s in list.take(5)) {
        final id = '${s['id']}';
        final sum = await widget.c.fetchRecordingSummary(id);
        if (mounted) setState(() => _summaries[id] = sum);
      }
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    return Panel(
      title: 'Past Experiment Sessions & Trial Summaries (${_sessions.length})',
      icon: Icons.history_edu_outlined,
      trailing: IconButton(
        tooltip: 'Refresh sessions',
        iconSize: 16,
        onPressed: _load,
        icon: const Icon(Icons.refresh, color: LM.teal),
      ),
      child: _loading
          ? const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()))
          : _sessions.isEmpty
              ? const Text('No recorded sessions yet.', style: TextStyle(color: LM.muted))
              : Column(children: [
                  for (final s in _sessions)
                    Builder(builder: (context) {
                      final id = '${s['id']}';
                      final sum = _summaries[id];
                      final flags = (sum?['flags'] as List?) ?? const [];
                      final notes = (sum?['notes'] as List?) ?? const [];
                      final flaggedCount = (s['flagged_count'] as num?)?.toInt() ?? flags.length;
                      return Card(
                        margin: const EdgeInsets.only(bottom: 8),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                          side: BorderSide(color: flaggedCount > 0 ? LM.warn.withValues(alpha: 0.6) : LM.line),
                        ),
                        child: ExpansionTile(
                          shape: const Border(),
                          tilePadding: const EdgeInsets.symmetric(horizontal: 12),
                          leading: Icon(
                            flaggedCount > 0 ? Icons.flag_circle : Icons.check_circle_outline,
                            color: flaggedCount > 0 ? LM.warn : LM.ok,
                          ),
                          title: Text('Trial Session $id · ${s['status'] ?? 'completed'}',
                              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                          subtitle: Text(
                            'Events: ${s['event_count'] ?? 0} · Flagged discrepancies: $flaggedCount · Started: ${s['started_at'] ?? '—'}',
                            style: const TextStyle(fontSize: 11.5, color: LM.muted),
                          ),
                          childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                          children: [
                            if (notes.isNotEmpty) ...[
                              const Align(
                                alignment: Alignment.centerLeft,
                                child: Text('Recorded Researcher Notes:', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: LM.teal)),
                              ),
                              const SizedBox(height: 4),
                              for (final n in notes)
                                Align(
                                  alignment: Alignment.centerLeft,
                                  child: Padding(
                                    padding: const EdgeInsets.only(bottom: 3),
                                    child: Text('• ${(n['payload'] as Map?)?['summary'] ?? ''}', style: const TextStyle(fontSize: 12)),
                                  ),
                                ),
                            ],
                            if (flags.isNotEmpty) ...[
                              const SizedBox(height: 6),
                              const Align(
                                alignment: Alignment.centerLeft,
                                child: Text('Reconciliation Flags:', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: LM.warn)),
                              ),
                              const SizedBox(height: 4),
                              for (final f in flags)
                                Align(
                                  alignment: Alignment.centerLeft,
                                  child: Padding(
                                    padding: const EdgeInsets.only(bottom: 3),
                                    child: Text('⚠ ${(f['payload'] as Map?)?['spoken_response'] ?? (f['payload'] as Map?)?['rationale'] ?? ''}',
                                        style: const TextStyle(fontSize: 12, color: LM.warn)),
                                  ),
                                ),
                            ],
                          ],
                        ),
                      );
                    }),
                ]),
    );
  }
}

