import 'package:flutter/material.dart';

import '../state/app_state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class FeedPage extends StatefulWidget {
  const FeedPage(this.c, {super.key});
  final AppController c;
  @override
  State<FeedPage> createState() => _FeedPageState();
}

class _FeedPageState extends State<FeedPage> {
  String _filter = 'All';
  String _query = '';
  final _searchCtl = TextEditingController();
  final Set<String> _expandedKeys = {};
  final Set<String> _jsonOpenKeys = {};

  static const _filters = ['All', 'Notes', 'Camera', 'Reviews'];

  @override
  void dispose() {
    _searchCtl.dispose();
    super.dispose();
  }

  bool _matchesFilter(FeedItem i) {
    final p = i.structured ?? const {};
    final isReviewItem = i.eventType == 'reconciliation' ||
        i.eventType == 'correction' ||
        p['requires_human_approval'] == true ||
        (i.review != 'n/a' && i.review != 'unreviewed');
    final isCameraItem = i.modality == 'image' ||
        i.modality == 'video' ||
        i.eventType == 'perception' ||
        i.eventType == 'visual_observation';
    final isNoteItem = i.modality == 'speech' ||
        i.eventType == 'observation_proposal' ||
        i.eventType == 'transcript_segment';

    final catMatch = switch (_filter) {
      'Notes' => isNoteItem,
      'Camera' => isCameraItem,
      'Reviews' => isReviewItem,
      'Errors' => i.isError,
      _ => true,
    };
    if (!catMatch) return false;

    final q = _query.trim().toLowerCase();
    if (q.isEmpty) return true;
    final blob = [
      i.eventType,
      i.modality,
      i.sourceText,
      '${p['channel_id'] ?? p['active_channel_id'] ?? ''}',
      '${p['step_id'] ?? p['active_step_id'] ?? p['protocol_step'] ?? ''}',
      '${p['spoken_response'] ?? ''}',
    ].join(' ').toLowerCase();
    return blob.contains(q);
  }

  int _countNeedsReview(List<FeedItem> all) {
    var count = 0;
    const resolved = {'accepted', 'disputed', 'corrected', 'rejected'};
    for (final i in all) {
      if (resolved.contains(i.review)) continue;
      final p = i.structured ?? const {};
      if (i.eventType == 'reconciliation' && p['requires_human_approval'] == true) {
        count++;
      }
    }
    return count;
  }

  List<FeedItem> _orderTimelineItems(List<FeedItem> items) {
    if (_filter != 'All' || _query.trim().isNotEmpty || items.length < 4) {
      return items;
    }
    // Keep all items, but ensure the top of the All-feed surfaces diverse event types
    // (e.g. review/protocol check, camera observation with thumbnail, researcher note)
    // when multiple seeded events share the same batch timestamp.
    final top = <FeedItem>[];
    final usedKeys = <String>{};

    void pickFirst(bool Function(FeedItem) pred) {
      for (final item in items) {
        if (!usedKeys.contains(item.key) && pred(item)) {
          top.add(item);
          usedKeys.add(item.key);
          return;
        }
      }
    }

    pickFirst((i) => i.review == 'accepted' || i.eventType == 'correction' || i.eventType == 'review');
    pickFirst((i) => i.eventType == 'reconciliation' && i.structured?['requires_human_approval'] == true);
    pickFirst((i) => i.eventType == 'perception' || i.eventType == 'visual_observation');
    pickFirst((i) => i.eventType == 'observation_proposal' || i.modality == 'speech');

    return [
      ...top,
      for (final item in items)
        if (!usedKeys.contains(item.key)) item,
    ];
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final allItems = c.feed;
    final filtered = _orderTimelineItems(allItems.where(_matchesFilter).toList());
    final needReviewCount = _countNeedsReview(allItems);
    final hasErrors = allItems.any((f) => f.isError);
    final filterTabs = hasErrors ? [..._filters, 'Errors'] : _filters;

    final sessionLabel = c.recordingActive && c.recording?['id'] != null
        ? 'Session ${c.recording!['id']}'
        : 'Session 02';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Data feed',
                style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: LM.text, letterSpacing: -0.4),
              ),
              const SizedBox(height: 2),
              Text(
                '${c.experimentDisplayTitle} · $sessionLabel',
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: LM.text),
              ),
              const SizedBox(height: 2),
              Text(
                '${allItems.length} events · $needReviewCount need review',
                style: const TextStyle(fontSize: 13.5, color: LM.text),
              ),
              const SizedBox(height: 12),

              // Search & Filter Card
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: LM.surface,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: LM.line, width: 1.2),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(
                      height: 42,
                      child: TextField(
                        controller: _searchCtl,
                        onChanged: (v) => setState(() => _query = v),
                        decoration: InputDecoration(
                          hintText: 'Search events',
                          prefixIcon: const Icon(Icons.search, color: LM.muted, size: 20),
                          suffixIcon: _query.isNotEmpty
                              ? IconButton(
                                  icon: const Icon(Icons.clear, size: 18),
                                  onPressed: () {
                                    _searchCtl.clear();
                                    setState(() => _query = '');
                                  },
                                )
                              : null,
                          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        for (var idx = 0; idx < filterTabs.length; idx++) ...[
                          if (idx > 0) const SizedBox(width: 8),
                          Expanded(
                            child: _FilterPill(
                              label: filterTabs[idx],
                              selected: _filter == filterTabs[idx],
                              onTap: () => setState(() => _filter = filterTabs[idx]),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),

        // Timeline List
        Expanded(
          child: filtered.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      allItems.isEmpty ? 'No events recorded yet.' : 'No events match "$_filter" / "$_query".',
                      style: const TextStyle(color: LM.muted, fontSize: 14),
                    ),
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 2, 16, 28),
                  itemCount: filtered.length,
                  itemBuilder: (_, idx) {
                    final item = filtered[idx];
                    final isExpanded = _expandedKeys.contains(item.key);
                    final isJsonOpen = _jsonOpenKeys.contains(item.key);
                    return _TimelineEventRow(
                      c: c,
                      item: item,
                      expanded: isExpanded,
                      jsonOpen: isJsonOpen,
                      onToggleExpand: () => setState(() {
                        if (isExpanded) {
                          _expandedKeys.remove(item.key);
                        } else {
                          _expandedKeys.add(item.key);
                        }
                      }),
                      onToggleJson: () => setState(() {
                        if (isJsonOpen) {
                          _jsonOpenKeys.remove(item.key);
                        } else {
                          _jsonOpenKeys.add(item.key);
                        }
                      }),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class _FilterPill extends StatelessWidget {
  const _FilterPill({required this.label, required this.selected, required this.onTap});
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(10),
      onTap: onTap,
      child: Container(
        height: 36,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected ? LM.teal : LM.softTeal,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: selected ? LM.teal : LM.teal.withValues(alpha: 0.45),
            width: 1.1,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: selected ? Colors.white : LM.text,
          ),
        ),
      ),
    );
  }
}

class _TimelineEventRow extends StatelessWidget {
  const _TimelineEventRow({
    required this.c,
    required this.item,
    required this.expanded,
    required this.jsonOpen,
    required this.onToggleExpand,
    required this.onToggleJson,
  });

  final AppController c;
  final FeedItem item;
  final bool expanded;
  final bool jsonOpen;
  final VoidCallback onToggleExpand;
  final VoidCallback onToggleJson;

  (String, String, IconData) _formatEventHeader(FeedItem i) {
    final p = i.structured ?? const {};
    if (i.eventType == 'reconciliation') {
      final spoken = '${p['spoken_response'] ?? ''}'.trim();
      final shortText = spoken.isNotEmpty
          ? (spoken.length > 90 ? '${spoken.substring(0, 88)}…' : spoken)
          : 'Review requested for the channel inspection.';
      return ('Protocol check.', shortText, Icons.assignment_turned_in_outlined);
    }
    if (i.eventType == 'perception' || i.eventType == 'visual_observation') {
      final spec = (p['specialist'] as Map?)?.cast<String, dynamic>();
      final bCount = (spec?['count'] as num?)?.toInt() ?? 0;
      final summary = bCount > 0
          ? '$bCount bubble candidate${bCount == 1 ? '' : 's'} marked. ${p['scene_summary'] ?? ''}'
          : '${p['scene_summary'] ?? i.sourceText}';
      return ('Camera observation.', summary.trim(), Icons.camera_alt_rounded);
    }
    if (i.eventType == 'correction' || (i.review != 'n/a' && i.review != 'unreviewed' && i.eventType == 'review')) {
      return ('Review decision.', i.sourceText, Icons.check_circle_rounded);
    }
    if (i.modality == 'speech' || i.eventType == 'observation_proposal' || i.eventType == 'transcript_segment') {
      final raw = '${p['summary'] ?? p['text'] ?? i.sourceText}'.trim();
      return ('Researcher note.', raw.endsWith('.') ? raw : '$raw.', Icons.mic_rounded);
    }
    if (i.isError) {
      return ('System alert.', i.sourceText, Icons.error_outline_rounded);
    }
    return ('System event.', i.sourceText, Icons.info_outline_rounded);
  }

  String? _extractChannel(FeedItem i) {
    final p = i.structured ?? const {};
    final ch = p['channel_id'] ?? p['active_channel_id'];
    if (ch is String && ch.isNotEmpty) return ch;
    final aff = (p['affected_structured'] as Map?)?['channels'] as List?;
    if (aff != null && aff.isNotEmpty) return '${aff.first}';
    return null;
  }

  String? _extractStepBadge(FeedItem i) {
    final p = i.structured ?? const {};
    final raw = '${p['step_id'] ?? p['active_step_id'] ?? p['protocol_step'] ?? ''}'.trim();
    if (raw.isEmpty) return null;
    final m = RegExp(r'(\d+)$').firstMatch(raw);
    if (m != null) return 'Step ${int.parse(m.group(1)!)}';
    return raw;
  }

  (String, Color, Color)? _resolveReviewBadge(FeedItem i) {
    final p = i.structured ?? const {};
    final rev = i.review;
    if (rev == 'accepted') return ('Accepted', const Color(0xFFCDEAE1), LM.text);
    if (rev == 'disputed') return ('Disputed', LM.reviewBg, LM.reviewText);
    if (rev == 'corrected') return ('Corrected', LM.softTeal, LM.teal);
    if (rev == 'rejected') return ('Discarded', LM.pillNeutralBg, LM.muted);

    final needsApproval = p['requires_human_approval'] == true ||
        ((p['specialist'] as Map?)?['review_required'] == true);
    if (needsApproval) {
      return ('Needs review', LM.reviewBg, LM.reviewText);
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final (title, summary, icon) = _formatEventHeader(item);
    final channel = _extractChannel(item);
    final stepBadge = _extractStepBadge(item);
    final revBadge = _resolveReviewBadge(item);
    final isCameraEvent = item.eventType == 'perception' || item.eventType == 'visual_observation';
    final obsId = '${item.raw?['id'] ?? item.structured?['observation_id'] ?? ''}';

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Left timeline gutter: time + icon + continuous line
          SizedBox(
            width: 56,
            child: Column(
              children: [
                const SizedBox(height: 12),
                Text(
                  hhmm(item.time),
                  style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600, color: LM.text),
                ),
                const SizedBox(height: 8),
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(
                    color: item.isError ? LM.rec.withValues(alpha: 0.12) : LM.softTeal,
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    icon,
                    size: 17,
                    color: item.isError ? LM.rec : LM.teal,
                  ),
                ),
                Expanded(
                  child: Container(
                    width: 2,
                    margin: const EdgeInsets.only(top: 6),
                    color: LM.line,
                  ),
                ),
              ],
            ),
          ),

          // Vertical separator line matching visual reference
          Container(
            width: 1.2,
            color: LM.line,
            margin: const EdgeInsets.only(right: 12),
          ),

          // Right content area
          Expanded(
            child: InkWell(
              borderRadius: BorderRadius.circular(10),
              onTap: onToggleExpand,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 4),
                decoration: const BoxDecoration(
                  border: Border(bottom: BorderSide(color: LM.line, width: 1)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            title,
                            style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w800, color: LM.text),
                          ),
                        ),
                        PersistenceBadge(item.persistence),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Text(
                            summary,
                            maxLines: expanded ? null : 3,
                            overflow: expanded ? null : TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 14.5, color: LM.text, height: 1.35),
                          ),
                        ),
                        const SizedBox(width: 6),
                        Icon(
                          expanded ? Icons.keyboard_arrow_down : Icons.chevron_right,
                          size: 18,
                          color: LM.muted,
                        ),
                      ],
                    ),

                    // Evidence thumbnail for camera observations
                    if (isCameraEvent) ...[
                      const SizedBox(height: 8),
                      SizedBox(
                        width: 176,
                        height: 92,
                        child: Container(
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: LM.line),
                          ),
                          child: MicrofluidicEvidenceCanvas(
                            perception: item.structured,
                            compact: true,
                          ),
                        ),
                      ),
                    ],

                    // Step, Channel, and Review Status chips
                    if (stepBadge != null || channel != null || revBadge != null) ...[
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          if (stepBadge != null)
                            _MetaChip(label: stepBadge, bg: const Color(0xFFCDEAE1), fg: LM.text),
                          if (channel != null)
                            _MetaChip(label: channel, bg: const Color(0xFFCDEAE1), fg: LM.text),
                          if (revBadge != null)
                            _MetaChip(label: revBadge.$1, bg: revBadge.$2, fg: revBadge.$3),
                        ],
                      ),
                    ],

                    // Expanded section: Review actions + Expandable Technical JSON
                    if (expanded) ...[
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 8,
                        runSpacing: 6,
                        children: [
                          if (obsId.isNotEmpty)
                            FilledButton.tonalIcon(
                              onPressed: () => showReviewObservationSheet(
                                context,
                                c,
                                targetObservationId: obsId,
                                initialSummary: summary,
                                initialChannel: channel,
                              ),
                              icon: const Icon(Icons.rate_review_outlined, size: 16),
                              label: const Text('Review observation'),
                            ),
                          OutlinedButton.icon(
                            onPressed: onToggleJson,
                            icon: Icon(jsonOpen ? Icons.code_off : Icons.code, size: 16),
                            label: Text(jsonOpen ? 'Hide technical JSON' : 'Technical JSON'),
                          ),
                        ],
                      ),
                      if (jsonOpen && (item.raw ?? item.structured) != null) ...[
                        const SizedBox(height: 8),
                        JsonView(item.raw ?? item.structured),
                      ],
                    ],
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.label, required this.bg, required this.fg});
  final String label;
  final Color bg;
  final Color fg;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3.5),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(7),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: fg),
      ),
    );
  }
}
