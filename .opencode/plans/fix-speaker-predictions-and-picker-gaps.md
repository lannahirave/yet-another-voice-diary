# Plan: Fix Speaker Predictions & Picker Gaps in CurrentSession

## Summary

Two fixes in `CurrentSession.tsx`:
- **B1**: Subscribe to `speaker_segment` WebSocket events so resolved contacts update utterances in real time
- **A**: Virtualizer measurement before auto-scroll to prevent gaps when picker is open

## Fix B1: Subscribe to `speaker_segment` events

### File: `frontend/src/components/CurrentSession.tsx`

**Add after line 462** (system ws error handler, before `await sysWs.connect(sessionId)`):

```tsx
    sysWs.on('speaker_segment', (data) => {
      const d = data as { id: string; contact_id: string | null; status: string }
      if (d.contact_id && d.status === 'identified') {
        setUtterances((prev) =>
          prev.map((u) =>
            u.speakerSegmentId === d.id ? { ...u, speakerId: d.contact_id } : u,
          ),
        )
      }
    })
```

**Add after line 538** (mic ws error handler, before `const streamPromise = ...`):

```tsx
      ws.on('speaker_segment', (data) => {
        const d = data as { id: string; contact_id: string | null; status: string }
        if (d.contact_id && d.status === 'identified') {
          setUtterances((prev) =>
            prev.map((u) =>
              u.speakerSegmentId === d.id ? { ...u, speakerId: d.contact_id } : u,
            ),
          )
        }
      })
```

Both handlers do the same thing: when a `speaker_segment` event arrives with a resolved `contact_id` and `status === 'identified'`, find all utterances with matching `speaker_segment_id` and update their `speakerId` to the resolved contact.

## Fix A: Virtualizer measurement before auto-scroll

### File: `frontend/src/components/CurrentSession.tsx`

**Change lines 372-376** from:

```tsx
  useEffect(() => {
    if (showLive && transcriptRef.current) {
      rowVirtualizer.scrollToIndex(utterances.length - 1, { align: 'end' })
    }
  }, [utterances, showLive, rowVirtualizer])
```

To:

```tsx
  useEffect(() => {
    if (showLive && transcriptRef.current) {
      rowVirtualizer.measure()
      rowVirtualizer.scrollToIndex(utterances.length - 1, { align: 'end' })
    }
  }, [utterances, showLive, rowVirtualizer])
```

This ensures the virtualizer re-measures all row heights (including any expanded picker panels) before computing scroll positions for new utterances.

## Why B2 (backend `speaker_contact_id` patching) is NOT needed

`create_utterance()` in `session_repo.py:161` does a `LEFT JOIN speaker_segments` to get `speaker_contact_id` from the DB. Since the coordinator emits all `speaker_segment` events first (which trigger `on_seg()` → resolver → `create_speaker_segment()` saving the resolved `contact_id`), then emits `utterance` events (triggering `create_utterance()` which JOINs the already-saved segment), the utterance payload **already has the correct `speaker_contact_id`**.

## Verification

```bash
cd D:\web_app\frontend && npm run typecheck
cd D:\web_app\frontend && npm run test:unit
```
