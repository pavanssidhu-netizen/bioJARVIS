import 'package:flutter/material.dart';

import '../state/app_state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class LogPage extends StatefulWidget {
  const LogPage(this.c, {super.key});
  final AppController c;
  @override
  State<LogPage> createState() => _LogPageState();
}

class _LogPageState extends State<LogPage> {
  int _subTab = 0; // 0 = Notebook, 1 = Sessions
  bool _hideTranscript = true;
  String? _selectedSessionId;
  List<Map<String, dynamic>> _sessions = [];
  final Map<String, Map<String, dynamic>> _sessionSummaries = {};
  Map<String, dynamic>? _graphData;
  String _graphFocusChannel = 'CH08';
  bool _loadingSessions = false;

  @override
  void initState() {
    super.initState();
    widget.c.loadLog();
    _loadV2HistoryAndGraph();
  }

  Future<void> _loadV2HistoryAndGraph() async {
    setState(() => _loadingSessions = true);
    try {
      final sess = await widget.c.fetchExperimentSessions();
      final graph = await widget.c.fetchDependencyGraph(focus: _graphFocusChannel);
      if (mounted) {
        setState(() {
          _sessions = sess;
          _graphData = graph;
        });
      }
      for (final s in sess.take(6)) {
        final id = '${s['id']}';
        final sum = await widget.c.fetchRecordingSummary(id);
        if (mounted) setState(() => _sessionSummaries[id] = sum);
      }
    } catch (_) {}
    if (mounted) setState(() => _loadingSessions = false);
  }

  Future<void> _updateGraphFocus(String ch) async {
    setState(() => _graphFocusChannel = ch);
    try {
      final graph = await widget.c.fetchDependencyGraph(focus: ch);
      if (mounted) setState(() => _graphData = graph);
    } catch (_) {}
  }

  Future<void> _showCorrectionDialog(BuildContext context, Map<String, dynamic> e) async {
    final p = (e['payload'] as Map?)?.cast<String, dynamic>() ?? const {};
    final ctl = TextEditingController(text: '${p['summary'] ?? p['text'] ?? p['description'] ?? ''}');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: LM.surface,
        title: const Text('Add correction'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'The original record is kept unchanged; a new linked correction event is created.',
              style: TextStyle(color: LM.muted, fontSize: 12.5),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: ctl,
              maxLines: 3,
              decoration: const InputDecoration(border: OutlineInputBorder()),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save correction')),
        ],
      ),
    );
    if (ok == true && ctl.text.trim().isNotEmpty) {
      await widget.c.reviewObservation('${e['id']}', 'correct', correction: {'summary': ctl.text.trim()});
    }
  }

  void _showEvidenceDetailModal(BuildContext context, Map<String, dynamic> e, int figNum) {
    final p = (e['payload'] as Map?)?.cast<String, dynamic>() ?? const {};
    final spec = (p['specialist'] as Map?)?.cast<String, dynamic>();
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: LM.surface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.75,
        maxChildSize: 0.92,
        minChildSize: 0.45,
        builder: (_, scroll) => ListView(
          controller: scroll,
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 24),
          children: [
            Row(
              children: [
                Text(
                  'Fig. ${figNum.toString().padLeft(2, '0')} — Channel inspection',
                  style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: LM.text),
                ),
                const Spacer(),
                IconButton(onPressed: () => Navigator.pop(ctx), icon: const Icon(Icons.close)),
              ],
            ),
            const SizedBox(height: 8),
            AspectRatio(
              aspectRatio: 16 / 10,
              child: MicrofluidicEvidenceCanvas(perception: p),
            ),
            const SizedBox(height: 12),
            if (spec != null) ...[
              Text('Specialist Perception: ${spec['description'] ?? ''}',
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: LM.text)),
              if (spec['sceptic_critique'] != null) ...[
                const SizedBox(height: 4),
                Text('Sceptic audit: ${spec['sceptic_critique']}', style: const TextStyle(fontSize: 13, color: LM.muted)),
              ],
              const SizedBox(height: 10),
            ],
            const Text('Immutable Event Record (JSON)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: LM.muted)),
            const SizedBox(height: 6),
            JsonView(e),
          ],
        ),
      ),
    );
  }

  String _formatDateHeading(DateTime dt) {
    const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const months = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December',
    ];
    final w = weekdays[(dt.weekday - 1).clamp(0, 6)];
    final m = months[(dt.month - 1).clamp(0, 11)];
    return '$w, ${dt.day} $m';
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;

    // Map reconciliation events by source_event_id so Notebook entries show their reconciliation flags cleanly
    final reconBySource = <String, Map<String, dynamic>>{};
    for (final e in c.log) {
      if (e['event_type'] == 'reconciliation' && e['source_event_id'] != null) {
        reconBySource['${e['source_event_id']}'] = e;
      }
    }

    // Filter notebook entries
    final rawNotebookRows = c.log.where((e) {
      final type = '${e['event_type']}';
      if (_hideTranscript && type == 'transcript_segment') return false;
      if (type == 'reconciliation') return false; // merged into parent observation card
      if (_selectedSessionId != null && '${e['session_id']}' != _selectedSessionId) return false;
      return true;
    }).toList();

    // Order notebook entries so the session opens with the researcher note + AI camera observation figure
    final notebookRows = <Map<String, dynamic>>[];
    final usedIds = <String>{};
    for (final e in rawNotebookRows.reversed) {
      if (e['event_type'] == 'observation_proposal') {
        notebookRows.add(e);
        usedIds.add('${e['id']}');
        break;
      }
    }
    for (final e in rawNotebookRows) {
      if (e['event_type'] == 'perception' || e['event_type'] == 'visual_observation') {
        notebookRows.add(e);
        usedIds.add('${e['id']}');
        break;
      }
    }
    for (final e in rawNotebookRows) {
      if (!usedIds.contains('${e['id']}')) {
        notebookRows.add(e);
      }
    }

    final latestTs = notebookRows.isNotEmpty
        ? (DateTime.tryParse('${notebookRows.first['timestamp']}')?.toLocal() ?? DateTime.now())
        : DateTime(2026, 11, 8, 10, 13);

    final sessionLabel = _selectedSessionId != null
        ? 'Session $_selectedSessionId'
        : 'Session 02';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Top Header: Experiment log + Export button + Segmented Switcher
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 2, 16, 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Text(
                    'Experiment log',
                    style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800, color: LM.text),
                  ),
                  const Spacer(),
                  IconButton(
                    tooltip: 'Refresh log',
                    visualDensity: VisualDensity.compact,
                    onPressed: () {
                      c.loadLog();
                      _loadV2HistoryAndGraph();
                    },
                    icon: const Icon(Icons.refresh, size: 19, color: LM.muted),
                  ),
                  InkWell(
                    borderRadius: BorderRadius.circular(8),
                    onTap: c.log.isEmpty ? null : c.exportLog,
                    child: const Padding(
                      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.description_outlined, size: 18, color: LM.text),
                          SizedBox(width: 5),
                          Text('Export', style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600, color: LM.text)),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),

              // Notebook | Sessions segmented control
              Container(
                height: 40,
                decoration: BoxDecoration(
                  color: LM.surface,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: LM.teal, width: 1.2),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: InkWell(
                        borderRadius: const BorderRadius.horizontal(left: Radius.circular(8)),
                        onTap: () => setState(() => _subTab = 0),
                        child: Container(
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            color: _subTab == 0 ? LM.teal : Colors.transparent,
                            borderRadius: const BorderRadius.horizontal(left: Radius.circular(8)),
                          ),
                          child: Text(
                            'Notebook',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: _subTab == 0 ? Colors.white : LM.text,
                            ),
                          ),
                        ),
                      ),
                    ),
                    Expanded(
                      child: InkWell(
                        borderRadius: const BorderRadius.horizontal(right: Radius.circular(8)),
                        onTap: () => setState(() => _subTab = 1),
                        child: Container(
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            color: _subTab == 1 ? LM.teal : Colors.transparent,
                            borderRadius: const BorderRadius.horizontal(right: Radius.circular(8)),
                          ),
                          child: Text(
                            'Sessions',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: _subTab == 1 ? Colors.white : LM.text,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),

        // Main body: Either Warm Ivory Notebook OR Sessions & Dependency Graph view
        Expanded(
          child: _subTab == 0
              ? _buildNotebookView(context, c, notebookRows, reconBySource, latestTs, sessionLabel)
              : _buildSessionsAndGraphView(context, c),
        ),
      ],
    );
  }

  Widget _buildNotebookView(
    BuildContext context,
    AppController c,
    List<Map<String, dynamic>> rows,
    Map<String, Map<String, dynamic>> reconBySource,
    DateTime latestTs,
    String sessionLabel,
  ) {
    var figCounter = 0;

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: LM.paperBg,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(14)),
        border: Border.all(color: LM.paperLine, width: 1.2),
      ),
      child: ClipRRect(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(14)),
        child: CustomPaint(
          painter: _NotebookPaperPainter(),
          child: ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              // Notebook Header Section
              _NotebookRowLayout(
                timestamp: '',
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(0, 14, 0, 14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (c.isShowingDemoSession)
                        Center(
                          child: Container(
                            margin: const EdgeInsets.only(bottom: 10),
                            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 3.5),
                            decoration: BoxDecoration(
                              color: const Color(0xFFE3E7E3),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: const Text(
                              'Demo data',
                              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Color(0xFF53676F)),
                            ),
                          ),
                        ),
                      Text(
                        _formatDateHeading(latestTs),
                        style: const TextStyle(fontSize: 23, fontWeight: FontWeight.w800, color: LM.text, letterSpacing: -0.3),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        c.experimentDisplayTitle,
                        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w500, color: LM.text),
                      ),
                      const SizedBox(height: 2),
                      Row(
                        children: [
                          Text(
                            sessionLabel,
                            style: const TextStyle(fontSize: 14.5, color: LM.muted),
                          ),
                          if (_selectedSessionId != null) ...[
                            const SizedBox(width: 8),
                            InkWell(
                              onTap: () => setState(() => _selectedSessionId = null),
                              child: const Text('Show all', style: TextStyle(fontSize: 12.5, color: LM.teal, fontWeight: FontWeight.w600)),
                            ),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              const Divider(height: 1, thickness: 1, color: LM.paperLine),

              if (rows.isEmpty)
                const _NotebookRowLayout(
                  timestamp: '—',
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Text('No stored observations for this experiment yet.', style: TextStyle(color: LM.muted)),
                  ),
                )
              else
                for (final e in rows)
                  Builder(
                    builder: (context) {
                      final isCamera = e['event_type'] == 'perception' || e['event_type'] == 'visual_observation';
                      if (isCamera) figCounter++;
                      return _NotebookEntryItem(
                        c: c,
                        event: e,
                        reconciliation: reconBySource['${e['id']}'],
                        figNumber: isCamera ? figCounter : null,
                        onCorrect: () => _showCorrectionDialog(context, e),
                        onViewEvidence: isCamera ? () => _showEvidenceDetailModal(context, e, figCounter) : null,
                      );
                    },
                  ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSessionsAndGraphView(BuildContext context, AppController c) {
    final affected = (_graphData?['affected'] as Map?)?.cast<String, dynamic>() ?? const {};
    final affStruct = (affected['structured'] as Map?)?.cast<String, dynamic>() ?? const {};
    final affSamples = ((affStruct['samples'] as List?) ?? const []).join(', ');
    final affResults = ((affStruct['derived_values'] as List?) ?? const []).join(', ');

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 28),
      children: [
        // Filter controls
        Row(
          children: [
            FilterChip(
              label: const Text('Hide raw speech segments'),
              selected: _hideTranscript,
              onSelected: (v) => setState(() => _hideTranscript = v),
            ),
            const Spacer(),
            Text('${c.log.length} raw events', style: const TextStyle(fontSize: 12.5, color: LM.muted)),
          ],
        ),
        const SizedBox(height: 10),

        // Past Sessions List
        Panel(
          title: 'Recorded Sessions (${_sessions.length})',
          icon: Icons.history_edu_outlined,
          child: _loadingSessions
              ? const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()))
              : _sessions.isEmpty
                  ? const Text('No sessions recorded yet.', style: TextStyle(color: LM.muted))
                  : Column(
                      children: [
                        for (var idx = 0; idx < _sessions.length; idx++)
                          Builder(
                            builder: (context) {
                              final s = _sessions[idx];
                              final id = '${s['id']}';
                              final flagged = (s['flagged_count'] as num?)?.toInt() ?? 0;
                              final sum = _sessionSummaries[id];
                              final notes = (sum?['notes'] as List?) ?? const [];
                              return Container(
                                margin: const EdgeInsets.only(bottom: 10),
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: LM.bg,
                                  borderRadius: BorderRadius.circular(12),
                                  border: Border.all(color: flagged > 0 ? LM.reviewBorder : LM.line),
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      children: [
                                        Text(
                                          'Session ${(idx + 1).toString().padLeft(2, '0')} ($id)',
                                          style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: LM.text),
                                        ),
                                        const Spacer(),
                                        if (flagged > 0)
                                          Container(
                                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                                            decoration: BoxDecoration(
                                              color: LM.reviewBg,
                                              borderRadius: BorderRadius.circular(6),
                                            ),
                                            child: Text(
                                              '$flagged needs review',
                                              style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: LM.reviewText),
                                            ),
                                          ),
                                      ],
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      '${s['event_count'] ?? 0} events · Status: ${s['status'] ?? 'stopped'}',
                                      style: const TextStyle(fontSize: 12.5, color: LM.muted),
                                    ),
                                    if (notes.isNotEmpty) ...[
                                      const SizedBox(height: 6),
                                      for (final n in notes.take(2))
                                        Text(
                                          '• ${(n['payload'] as Map?)?['summary'] ?? ''}',
                                          style: const TextStyle(fontSize: 12.5, color: LM.text),
                                        ),
                                    ],
                                    const SizedBox(height: 8),
                                    Align(
                                      alignment: Alignment.centerRight,
                                      child: TextButton.icon(
                                        onPressed: () => setState(() {
                                          _selectedSessionId = id;
                                          _subTab = 0;
                                        }),
                                        icon: const Icon(Icons.menu_book_outlined, size: 16),
                                        label: const Text('Open in Notebook'),
                                      ),
                                    ),
                                  ],
                                ),
                              );
                            },
                          ),
                      ],
                    ),
        ),
        const SizedBox(height: 12),

        // 12-Channel CEA Dependency & Impact Graph
        Panel(
          title: 'Channel Dependency & Impact Graph',
          icon: Icons.account_tree_outlined,
          trailing: const Text('may need review', style: TextStyle(fontSize: 11.5, color: LM.reviewText, fontWeight: FontWeight.w600)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Tap any microfluidic channel (CH01–CH12) to trace which standards, samples, and results may need review:',
                style: TextStyle(fontSize: 12.5, color: LM.muted),
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (var i = 1; i <= 12; i++)
                    Builder(
                      builder: (_) {
                        final ch = 'CH${i.toString().padLeft(2, '0')}';
                        final selected = ch == _graphFocusChannel;
                        return ChoiceChip(
                          label: Text(ch),
                          selected: selected,
                          selectedColor: LM.teal,
                          labelStyle: TextStyle(
                            color: selected ? Colors.white : LM.text,
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                          ),
                          onSelected: (_) => _updateGraphFocus(ch),
                        );
                      },
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: LM.reviewBg,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: LM.reviewBorder),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Downstream impact if $_graphFocusChannel is flagged:',
                      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: LM.reviewText),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Samples / Standards: ${affSamples.isEmpty ? 'STD01 / S02' : affSamples}',
                      style: const TextStyle(fontSize: 12.5, color: LM.text),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Derived Results: ${affResults.isEmpty ? 'result_S02' : affResults}',
                      style: const TextStyle(fontSize: 12.5, color: LM.reviewText, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _NotebookRowLayout extends StatelessWidget {
  const _NotebookRowLayout({required this.timestamp, required this.child});
  final String timestamp;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 62,
            child: Padding(
              padding: const EdgeInsets.only(left: 12, top: 14, right: 6),
              child: Text(
                timestamp,
                style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w500, color: LM.text),
              ),
            ),
          ),
          Container(width: 1.2, color: LM.paperLine),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: child,
            ),
          ),
        ],
      ),
    );
  }
}

class _NotebookEntryItem extends StatefulWidget {
  const _NotebookEntryItem({
    required this.c,
    required this.event,
    this.reconciliation,
    this.figNumber,
    required this.onCorrect,
    this.onViewEvidence,
  });

  final AppController c;
  final Map<String, dynamic> event;
  final Map<String, dynamic>? reconciliation;
  final int? figNumber;
  final VoidCallback onCorrect;
  final VoidCallback? onViewEvidence;

  @override
  State<_NotebookEntryItem> createState() => _NotebookEntryItemState();
}

class _NotebookEntryItemState extends State<_NotebookEntryItem> {
  bool _actionsOpen = false;

  @override
  Widget build(BuildContext context) {
    final e = widget.event;
    final p = (e['payload'] as Map?)?.cast<String, dynamic>() ?? const {};
    final recP = (widget.reconciliation?['payload'] as Map?)?.cast<String, dynamic>() ?? const {};
    final ts = DateTime.tryParse('${e['timestamp']}')?.toLocal();
    final timeStr = ts != null ? hhmm(ts) : '10:12';

    final isCamera = e['event_type'] == 'perception' || e['event_type'] == 'visual_observation';
    final channel = '${p['channel_id'] ?? p['active_channel_id'] ?? recP['channel_id'] ?? 'CH08'}';
    final categoryLabel = isCamera ? 'AI observation · $channel' : 'Researcher note · $channel';

    final spec = (p['specialist'] as Map?)?.cast<String, dynamic>();
    final bCount = (spec?['count'] as num?)?.toInt() ?? 0;
    final bodyText = isCamera
        ? (bCount > 0 ? 'Two bubble candidates marked for review.' : '${p['scene_summary'] ?? 'Channel inspection recorded.'}')
        : '${p['summary'] ?? p['text'] ?? p['description'] ?? e['event_type']}';

    final status = '${e['review_status'] ?? 'unreviewed'}';
    const resolved = {'accepted', 'disputed', 'corrected', 'rejected'};
    final needsReview = !resolved.contains(status) &&
        (recP['requires_human_approval'] == true || spec?['review_required'] == true || isCamera);

    final (badgeLabel, badgeBg, badgeFg) = switch (status) {
      'accepted' => ('Accepted', LM.okBg, LM.okText),
      'disputed' => ('Disputed', LM.reviewBg, LM.reviewText),
      'corrected' => ('Corrected', LM.softTeal, LM.teal),
      'rejected' => ('Discarded', LM.pillNeutralBg, LM.muted),
      _ => needsReview ? ('Needs review', LM.reviewBg, LM.reviewText) : ('Recorded', Colors.transparent, LM.muted),
    };

    final reviews = (e['reviews'] as List?) ?? const [];

    return Column(
      children: [
        _NotebookRowLayout(
          timestamp: timeStr,
          child: Padding(
            padding: const EdgeInsets.only(top: 12, bottom: 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Header line: Category · Channel + Needs review pill
                InkWell(
                  onTap: () => setState(() => _actionsOpen = !_actionsOpen),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          categoryLabel,
                          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: LM.text),
                        ),
                      ),
                      if (badgeLabel != 'Recorded')
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
                          decoration: BoxDecoration(
                            color: badgeBg,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            badgeLabel,
                            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: badgeFg),
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 8),

                // Main observation text (wraps naturally across ruled lines)
                Text(
                  bodyText,
                  style: const TextStyle(fontSize: 15.5, color: LM.text, height: 1.65),
                ),

                // Embedded Evidence Figure & Caption
                if (isCamera) ...[
                  const SizedBox(height: 12),
                  Container(
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: LM.paperLine, width: 1.2),
                    ),
                    child: AspectRatio(
                      aspectRatio: 16 / 10,
                      child: MicrofluidicEvidenceCanvas(perception: p),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          'Fig. ${(widget.figNumber ?? 1).toString().padLeft(2, '0')} — Channel inspection',
                          style: const TextStyle(fontSize: 13, color: LM.text, fontWeight: FontWeight.w500),
                        ),
                      ),
                      if (widget.onViewEvidence != null)
                        InkWell(
                          onTap: widget.onViewEvidence,
                          child: const Text(
                            'View evidence',
                            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: LM.teal),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 14),
                ],

                // Prominent Review observation button (matches Reference Image 3)
                if (needsReview || isCamera)
                  SizedBox(
                    height: 46,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: LM.teal,
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                      onPressed: () => showReviewObservationSheet(
                        context,
                        widget.c,
                        targetObservationId: '${e['id']}',
                        initialSummary: bodyText,
                        initialChannel: channel,
                      ),
                      child: const Text('Review observation', style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w600)),
                    ),
                  ),

                // Expandable inline Accept / Dispute / Correct / Reject bar + audit history
                if (_actionsOpen) ...[
                  const SizedBox(height: 10),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      OutlinedButton(
                        onPressed: () => widget.c.reviewObservation('${e['id']}', 'accept'),
                        child: const Text('Accept'),
                      ),
                      OutlinedButton(
                        onPressed: () => widget.c.reviewObservation('${e['id']}', 'dispute'),
                        child: const Text('Dispute'),
                      ),
                      OutlinedButton(
                        onPressed: widget.onCorrect,
                        child: const Text('Correct'),
                      ),
                      OutlinedButton(
                        style: OutlinedButton.styleFrom(foregroundColor: LM.rec),
                        onPressed: () => widget.c.reviewObservation('${e['id']}', 'reject'),
                        child: const Text('Reject'),
                      ),
                    ],
                  ),
                  if (reviews.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    for (final r in reviews)
                      Text(
                        'Audit: ${r['action']} (${r['timestamp']})',
                        style: const TextStyle(fontSize: 12, color: LM.muted),
                      ),
                  ],
                ],
              ],
            ),
          ),
        ),
        const Divider(height: 1, thickness: 1, color: LM.paperLine),
      ],
    );
  }
}

class _NotebookPaperPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = LM.paperLine.withValues(alpha: 0.55)
      ..strokeWidth = 0.8;

    const lineSpacing = 28.0;
    for (double y = 116.0; y < size.height; y += lineSpacing) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
