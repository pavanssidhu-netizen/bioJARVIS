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
  bool hideTranscript = false;

  @override
  void initState() {
    super.initState();
    widget.c.loadLog();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final rows = c.log.where((e) => !hideTranscript || e['event_type'] != 'transcript_segment').toList();
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 0, 12, 4),
        child: Row(children: [
          FilterChip(
              label: const Text('Hide transcript'), selected: hideTranscript, onSelected: (v) => setState(() => hideTranscript = v)),
          const Spacer(),
          IconButton(tooltip: 'Refresh', onPressed: c.loadLog, icon: const Icon(Icons.refresh, color: LM.teal)),
          TextButton.icon(onPressed: c.log.isEmpty ? null : c.exportLog, icon: const Icon(Icons.download), label: const Text('Export JSON')),
        ]),
      ),
      Expanded(
        child: rows.isEmpty
            ? const Center(child: Text('No stored observations for this experiment.', style: TextStyle(color: LM.muted)))
            : ListView.builder(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
                itemCount: rows.length,
                itemBuilder: (_, i) => _LogTile(c, rows[i], key: ValueKey(rows[i]['id'])),
              ),
      ),
    ]);
  }
}

class _LogTile extends StatelessWidget {
  const _LogTile(this.c, this.e, {super.key});
  final AppController c;
  final Map<String, dynamic> e;

  Color _statusColor(String s) => switch (s) {
        'accepted' => LM.ok,
        'disputed' => LM.warn,
        'rejected' => LM.rec,
        'corrected' => LM.teal,
        _ => LM.muted,
      };

  Future<void> _correct(BuildContext context) async {
    final p = e['payload'] as Map;
    final ctl = TextEditingController(text: '${p['summary'] ?? p['text'] ?? p['description'] ?? ''}');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Add correction'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('The original record is kept unchanged; a new linked correction event is created.',
              style: TextStyle(color: LM.muted, fontSize: 12)),
          const SizedBox(height: 10),
          TextField(controller: ctl, maxLines: 4, decoration: const InputDecoration(border: OutlineInputBorder())),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save correction')),
        ],
      ),
    );
    if (ok == true && ctl.text.trim().isNotEmpty) {
      await c.reviewObservation('${e['id']}', 'correct', correction: {'summary': ctl.text.trim()});
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = (e['payload'] as Map).cast<String, dynamic>();
    final status = '${e['review_status']}';
    final reviews = (e['reviews'] as List?) ?? const [];
    final ts = DateTime.tryParse('${e['timestamp']}')?.toLocal();
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10), side: const BorderSide(color: LM.line)),
      child: ExpansionTile(
        shape: const Border(),
        tilePadding: const EdgeInsets.symmetric(horizontal: 12),
        leading: Icon(modalityIcon('${e['source_modality']}'), color: LM.teal, size: 18),
        title: Text('${p['summary'] ?? p['text'] ?? p['description'] ?? p['correction'] ?? e['event_type']}',
            maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13.5)),
        subtitle: Text('#${e['sequence_number']} · ${e['event_type']} · ${ts != null ? hhmmss(ts) : ''}',
            style: Theme.of(context).textTheme.bodySmall),
        trailing: Text(status.toUpperCase(),
            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: _statusColor(status), letterSpacing: 0.8)),
        childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
        children: [
          Wrap(spacing: 6, runSpacing: 6, children: [
            OutlinedButton(onPressed: () => c.reviewObservation('${e['id']}', 'accept'), child: const Text('Accept')),
            OutlinedButton(onPressed: () => c.reviewObservation('${e['id']}', 'dispute'), child: const Text('Dispute')),
            OutlinedButton(onPressed: () => _correct(context), child: const Text('Correct')),
            OutlinedButton(
                style: OutlinedButton.styleFrom(foregroundColor: LM.rec),
                onPressed: () => c.reviewObservation('${e['id']}', 'reject'),
                child: const Text('Reject')),
          ]),
          if (reviews.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Align(alignment: Alignment.centerLeft, child: Text('History', style: TextStyle(fontWeight: FontWeight.w700))),
            for (final r in reviews)
              Align(
                alignment: Alignment.centerLeft,
                child: Text('${r['timestamp']} · ${r['action']}${r['correction'] != null ? ' → ${r['correction']}' : ''}',
                    style: Theme.of(context).textTheme.bodySmall),
              ),
          ],
          const SizedBox(height: 10),
          JsonView(e),
        ],
      ),
    );
  }
}
