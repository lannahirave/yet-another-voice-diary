"""Debug HTML report generator.

Produces a styled report with inline CSS/JS and waveform previews.
Audio sources can be base64 blobs or sidecar WAV files.
"""
from __future__ import annotations

import json
from typing import Any


def generate_debug_html(
    *,
    session_id: str,
    started_at: str,
    ended_at: str,
    config_snapshot: dict[str, Any],
    utterances: list[dict[str, Any]],
    vad_events: list[dict[str, Any]],
    pipeline_events: list[dict[str, Any]],
    queue_items: list[dict[str, Any]],
) -> str:
    total_words = sum(len(u["transcript"].split()) for u in utterances)
    total_ms = sum(u["duration_ms"] for u in utterances)
    speaker_set: dict[str, int] = {}
    for u in utterances:
        for seg in u.get("speaker_segments", []):
            cid = seg.get("contact_id") or seg.get("speaker", "__unk__")
            speaker_set[cid] = speaker_set.get(cid, 0) + 1
    speaker_json = json.dumps(list(speaker_set.keys()))

    data_json = json.dumps(
        {
            "sessionId": session_id,
            "startedAt": started_at,
            "endedAt": ended_at,
            "totalWords": total_words,
            "totalDurationMs": total_ms,
            "utteranceCount": len(utterances),
            "vadCount": len(vad_events),
            "eventCount": len(pipeline_events),
            "utterances": utterances,
            "vadEvents": vad_events,
            "pipelineEvents": pipeline_events,
            "queueItems": queue_items,
            "configSnapshot": config_snapshot,
        },
        indent=2,
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Debug Report — {session_id}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'JetBrains Mono',ui-monospace,'SFMono-Regular',Menlo,monospace;background:#0d0c0b;color:#e8e6df;font-size:13px;line-height:1.6}}
a{{color:#f54e00}}
h1{{font-size:18px;font-weight:700;letter-spacing:-0.01em}}
h2{{font-size:15px;font-weight:600;margin:24px 0 12px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.08)}}
h3{{font-size:13px;font-weight:600;color:rgba(232,230,223,0.6);text-transform:uppercase;letter-spacing:0.06em;margin:16px 0 8px}}
nav{{position:sticky;top:0;z-index:10;background:rgba(13,12,11,0.92);backdrop-filter:blur(12px);border-bottom:1px solid rgba(255,255,255,0.06);padding:8px 24px;display:flex;gap:12px;flex-wrap:wrap}}
nav a{{color:rgba(232,230,223,0.55);text-decoration:none;font-size:11px;padding:4px 10px;border-radius:4px;border:1px solid transparent}}
nav a:hover{{color:#f54e00;border-color:rgba(245,78,0,0.25)}}
.container{{max-width:1260px;margin:0 auto;padding:20px 24px}}
.card{{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:16px 20px;margin-bottom:12px}}
.card-summary{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}
.stat{{background:rgba(255,255,255,0.02);border-radius:6px;padding:10px 14px}}
.stat-label{{font-size:10px;color:rgba(232,230,223,0.4);text-transform:uppercase;letter-spacing:0.08em}}
.stat-value{{font-size:20px;font-weight:700;color:#e8e6df;margin-top:4px}}
.timeline{{position:relative;height:32px;background:rgba(255,255,255,0.04);border-radius:4px;overflow:hidden;margin:8px 0}}
.timeline-bar{{position:absolute;top:0;height:100%;border-radius:2px;cursor:pointer;transition:opacity 0.1s}}
.timeline-bar:hover{{opacity:0.8}}
.utt-row{{display:grid;grid-template-columns:24px 60px 1fr;gap:12px;align-items:start;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.04)}}
.utt-idx{{color:rgba(232,230,223,0.25);font-size:11px;text-align:right}}
.utt-time{{color:rgba(232,230,223,0.4);font-size:11px;text-align:right;font-variant-numeric:tabular-nums}}
.utt-text{{color:#e8e6df;font-size:13px;word-break:break-word}}
.utt-source{{display:inline-block;font-size:9px;padding:1px 5px;border-radius:3px;margin-right:4px;text-transform:uppercase;letter-spacing:0.06em;font-weight:600}}
.source-mic{{background:rgba(245,78,0,0.15);color:#f54e00}}
.source-system{{background:rgba(66,133,244,0.15);color:#4285f4}}
.lang-tag{{display:inline-block;font-size:9px;padding:1px 5px;border-radius:3px;background:rgba(255,255,255,0.06);color:rgba(232,230,223,0.4);margin-right:4px;font-weight:600}}
.seg-table{{width:100%;border-collapse:collapse;font-size:11px}}
.seg-table th,.seg-table td{{text-align:left;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.04)}}
.seg-table th{{color:rgba(232,230,223,0.4);font-weight:500;text-transform:uppercase;letter-spacing:0.06em;font-size:10px}}
.event-row{{display:flex;gap:8px;padding:3px 0;font-size:11px;align-items:baseline}}
.event-ms{{color:rgba(232,230,223,0.3);min-width:70px;text-align:right;font-variant-numeric:tabular-nums}}
.event-kind{{min-width:60px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em}}
.event-msg{{color:rgba(232,230,223,0.7);word-break:break-word}}
.kind-VAD{{color:#dfa88f}}
.kind-ASR{{color:#9fc9a2}}
.kind-DIAR{{color:#9fbbe0}}
.kind-EMBED{{color:#c0a8dd}}
.kind-ERROR{{color:#cf2d56}}
.kind-FLUSH{{color:#f54e00}}
summary{{cursor:pointer;user-select:none;color:rgba(232,230,223,0.5);font-size:12px;padding:8px 0}}
summary:hover{{color:#e8e6df}}
details[open] summary{{margin-bottom:8px}}
.waveform-container{{margin:8px 0;height:48px}}
.chart-bar-container{{display:flex;align-items:end;gap:4px;height:100px;padding:4px 0}}
.chart-bar{{flex:1;border-radius:2px 2px 0 0;min-width:8px;position:relative}}
.chart-bar-label{{position:absolute;bottom:-18px;left:50%;transform:translateX(-50%);font-size:9px;color:rgba(232,230,223,0.4);white-space:nowrap}}
.collapsed-detail{{display:none}}
details[open] .collapsed-detail{{display:block}}
.embed-toggle{{font-size:10px;color:rgba(232,230,223,0.3);cursor:pointer;background:none;border:1px solid rgba(255,255,255,0.08);border-radius:3px;padding:2px 8px}}
.embed-toggle:hover{{color:#f54e00;border-color:rgba(245,78,0,0.3)}}
.config-table{{width:100%;border-collapse:collapse;font-size:11px}}
.config-table td{{padding:4px 8px;border-bottom:1px solid rgba(255,255,255,0.04)}}
.config-table td:first-child{{color:rgba(232,230,223,0.4);width:220px}}
.config-table td:last-child{{color:#e8e6df;font-variant-numeric:tabular-nums}}
.spk-color{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle}}
.filter-active{{color:#f54e00!important;border-color:rgba(245,78,0,0.4)!important}}
</style>
</head>
<body>
<nav>
<a href="#summary">Summary</a>
<a href="#timeline">Timeline</a>
<a href="#utterances">Utterances</a>
<a href="#segments">Segments</a>
<a href="#events">Events</a>
<a href="#vad">VAD</a>
<a href="#config">Config</a>
</nav>
<div class="container">
<h1>Debug Report</h1>
<div id="summary" class="card card-summary"></div>

<h2 id="timeline">Timeline</h2>
<div class="card"><div id="timeline-viz"></div></div>

<h2 id="vad">VAD Timeline</h2>
<div class="card"><div id="vad-viz"></div></div>

<h2 id="utterances">Utterances</h2>
<div id="utt-list" class="card"></div>

<h2 id="segments">Speaker Segments</h2>
<div id="seg-list" class="card"></div>

<h2 id="events">Pipeline Events</h2>
<div class="card">
<div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap">
<button class="event-filter" data-kind="all" style="font-size:10px;padding:2px 8px;border-radius:3px;border:1px solid rgba(255,255,255,0.08);background:none;color:rgba(232,230,223,0.5);cursor:pointer">All</button>
<button class="event-filter filter-active" data-kind="VAD" style="font-size:10px;padding:2px 8px;border-radius:3px;border:1px solid rgba(255,255,255,0.08);background:none;color:rgba(232,230,223,0.5);cursor:pointer">VAD</button>
<button class="event-filter filter-active" data-kind="ASR" style="font-size:10px;padding:2px 8px;border-radius:3px;border:1px solid rgba(255,255,255,0.08);background:none;color:rgba(232,230,223,0.5);cursor:pointer">ASR</button>
<button class="event-filter filter-active" data-kind="DIAR" style="font-size:10px;padding:2px 8px;border-radius:3px;border:1px solid rgba(255,255,255,0.08);background:none;color:rgba(232,230,223,0.5);cursor:pointer">DIAR</button>
<button class="event-filter filter-active" data-kind="EMBED" style="font-size:10px;padding:2px 8px;border-radius:3px;border:1px solid rgba(255,255,255,0.08);background:none;color:rgba(232,230,223,0.5);cursor:pointer">EMBED</button>
<button class="event-filter filter-active" data-kind="ERROR" style="font-size:10px;padding:2px 8px;border-radius:3px;border:1px solid rgba(255,255,255,0.08);background:none;color:rgba(232,230,223,0.5);cursor:pointer">ERROR</button>
</div>
<div id="event-list"></div>
</div>

<h2 id="config">Configuration</h2>
<div class="card" id="config-table"></div>
</div>

<script>
const COLORS = ['#f54e00','#4285f4','#1f8a65','#c08532','#ec4899','#8b5cf6','#06b6d4','#84cc16'];
const DATA = {data_json};

let activeKinds = new Set(['VAD','ASR','DIAR','EMBED','ERROR']);

function fmtMs(ms){{const s=Math.floor(ms/1000);const m=Math.floor(s/60);const h=Math.floor(m/60);return h?`${{h}}:${{String(m%60).padStart(2,'0')}}:${{String(s%60).padStart(2,'0')}}`:`${{m}}:${{String(s%60).padStart(2,'0')}}`;}}
function fmtDuration(ms){{const s=Math.round(ms/1000);return s<60?`${{s}}s`:`${{Math.floor(s/60)}}m ${{s%60}}s`;}}
function audioSrc(u){{if(u.waveform_base64)return 'data:audio/wav;base64,'+u.waveform_base64;return u.waveform_file||'';}}

// Summary
let summary=document.getElementById('summary');
summary.innerHTML=`
<div class="stat"><div class="stat-label">Session</div><div class="stat-value" style="font-size:14px;word-break:break-all">${{DATA.sessionId.slice(0,18)}}&hellip;</div></div>
<div class="stat"><div class="stat-label">Started</div><div class="stat-value" style="font-size:14px">${{DATA.startedAt}}</div></div>
<div class="stat"><div class="stat-label">Ended</div><div class="stat-value" style="font-size:14px">${{DATA.endedAt||'—'}}</div></div>
<div class="stat"><div class="stat-label">Duration</div><div class="stat-value">${{fmtDuration(DATA.totalDurationMs)}}</div></div>
<div class="stat"><div class="stat-label">Utterances</div><div class="stat-value">${{DATA.utteranceCount}}</div></div>
<div class="stat"><div class="stat-label">Words</div><div class="stat-value">${{DATA.totalWords}}</div></div>
<div class="stat"><div class="stat-label">VAD Events</div><div class="stat-value">${{DATA.vadCount}}</div></div>
<div class="stat"><div class="stat-label">Pipeline Events</div><div class="stat-value">${{DATA.eventCount}}</div></div>
`;

// Timeline
let timelines='';
DATA.utterances.forEach((u,i)=>{{
let spkId=u.speaker_segments&&u.speaker_segments[0]?u.speaker_segments[0].contact_id||u.speaker_segments[0].speaker||0:0;
let colorIdx=typeof spkId==='string'?spkId.length%8:parseInt(spkId||0)%8;
let left=(u.started_ms/DATA.totalDurationMs*100).toFixed(2);
let width=Math.max(0.2,(u.duration_ms/DATA.totalDurationMs*100)).toFixed(2);
timelines+=`<div class="timeline-bar" style="left:${{left}}%;width:${{width}}%;background:${{COLORS[colorIdx]}}" title="#${{i+1}} ${{fmtMs(u.started_ms)}}&ndash;${{fmtMs(u.ended_ms)}} ${{u.transcript.slice(0,60)}}" onclick="document.getElementById('utt-${{i}}').scrollIntoView({{behavior:'smooth'}})" onmouseover="document.getElementById('utt-${{i}}').style.background='rgba(255,255,255,0.03)'" onmouseout="document.getElementById('utt-${{i}}').style.background=''"></div>`;
}});
document.getElementById('timeline-viz').innerHTML=`<div class="timeline">${{timelines}}</div>`;

// VAD visualization
let vadHtml='<div style="height:24px;position:relative;background:rgba(255,255,255,0.02);border-radius:3px;overflow:hidden">';
let maxVadMs=DATA.vadEvents.length?DATA.vadEvents[DATA.vadEvents.length-1].ms:DATA.totalDurationMs||1;
DATA.vadEvents.forEach(v=>{{
let left=(v.ms/maxVadMs*100).toFixed(2);
vadHtml+=`<div style="position:absolute;top:0;left:${{left}}%;width:3px;height:100%;background:${{v.is_speech?'#f54e00':'rgba(255,255,255,0.1)'}}" title="${{fmtMs(v.ms)}} ${{v.is_speech?'speech':'silence'}}"></div>`;
}});
vadHtml+='</div>';
document.getElementById('vad-viz').innerHTML=vadHtml;

// Utterances
let uttList=document.getElementById('utt-list');
DATA.utterances.forEach((u,i)=>{{
let spkSegs=u.speaker_segments||[];
let segHtml='';
spkSegs.forEach((seg,j)=>{{
let cid=seg.contact_id||seg.speaker||'?';
let color=COLORS[(typeof cid==='string'?cid.length:parseInt(cid||0))%8];
segHtml+=`<tr><td><span class="spk-color" style="background:${{color}}"></span>${{seg.segment_id||seg.id||'?'}}</td><td>${{seg.contact_id||'—'}}</td><td>${{seg.speaker||'—'}}</td><td>${{seg.diarization_model_id||'—'}}</td></tr>`;
}});
let wavB64=u.waveform_base64||'';
let wavSrc=audioSrc(u);
let srcLabel=u.source==='system'?'<span class="utt-source source-system">SYS</span>':u.source==='mic'?'<span class="utt-source source-mic">MIC</span>':'';
let langLabel=u.language?`<span class="lang-tag">${{u.language}}</span>`:'';
uttList.innerHTML+=`
<div id="utt-${{i}}" class="utt-row" style="">
<div class="utt-idx">#${{i+1}}</div>
<div class="utt-time">${{fmtMs(u.started_ms)}}<br>${{u.duration_ms}}ms</div>
<div>
${{srcLabel}}${{langLabel}}
${{wavSrc?`<details><summary>waveform</summary><div class="waveform-container"><svg id="wav-${{i}}" width="100%" height="44" style="display:block;border-radius:3px"></svg></div><audio controls style="width:100%;height:28px;margin-top:4px" src="${{wavSrc}}"></audio></details>`:''}}
<div class="utt-text">${{u.transcript||'(silence)'}}</div>
${{segHtml?`<details style="margin-top:6px"><summary>${{spkSegs.length}} speaker segment${{spkSegs.length!==1?'s':''}}</summary><table class="seg-table"><tr><th>ID</th><th>Contact</th><th>Speaker</th><th>Model</th></tr>${{segHtml}}</table></details>`:''}}
</div></div>`;
}});

// Segments index
let segTable='<table class="seg-table"><tr><th>#</th><th>Segment ID</th><th>Utterance</th><th>Contact</th><th>Speaker</th><th>Model</th></tr>';
DATA.utterances.forEach((u,i)=>{{
(u.speaker_segments||[]).forEach(seg=>{{
let cid=seg.contact_id||seg.speaker||'?';
let color=COLORS[(typeof cid==='string'?cid.length:parseInt(cid||0))%8];
segTable+=`<tr><td>${{i+1}}</td><td><span class="spk-color" style="background:${{color}}"></span>${{(seg.segment_id||seg.id||'?').slice(0,12)}}</td><td><a href="#utt-${{i}}">#${{i+1}}</a></td><td>${{seg.contact_id||'—'}}</td><td>${{seg.speaker||'—'}}</td><td>${{seg.diarization_model_id||'—'}}</td></tr>`;
}});
}});
segTable+='</table>';
document.getElementById('seg-list').innerHTML=segTable;

// Events
function renderEvents(){{
let html='',shown=0;
DATA.pipelineEvents.forEach(e=>{{
if(!activeKinds.has(e.kind))return;
shown++;
html+=`<div class="event-row" data-kind="${{e.kind}}"><span class="event-ms">${{fmtMs(e.ms)}}</span><span class="event-kind kind-${{e.kind}}">${{e.kind}}</span><span class="event-msg">${{e.message}}</span></div>`;
}});
if(!shown)html='<div style="color:rgba(232,230,223,0.3);font-size:12px;padding:16px">No events match filter</div>';
document.getElementById('event-list').innerHTML=html;
}}
document.querySelectorAll('.event-filter').forEach(btn=>{{
btn.addEventListener('click',()=>{{
let kind=btn.dataset.kind;
if(kind==='all'){{activeKinds=new Set(['VAD','ASR','DIAR','EMBED','ERROR']);document.querySelectorAll('.event-filter').forEach(b=>b.classList.add('filter-active'));btn.classList.add('filter-active');}}
else{{if(activeKinds.has(kind)){{activeKinds.delete(kind);btn.classList.remove('filter-active')}}else{{activeKinds.add(kind);btn.classList.add('filter-active')}}document.querySelector('.event-filter[data-kind="all"]').classList.remove('filter-active')}}
renderEvents();
}});
}});
renderEvents();

// Config
let cfgTr='';
function walk(obj,prefix){{
if(typeof obj!=='object'||!obj){{cfgTr+=`<tr><td>${{prefix}}</td><td>${{obj}}</td></tr>`;return}}
Object.entries(obj).forEach(([k,v])=>{{
let key=prefix?`${{prefix}}.${{k}}`:k;
if(typeof v==='object'&&v&&!Array.isArray(v))walk(v,key);
else cfgTr+=`<tr><td>${{key}}</td><td>${{typeof v==='object'?JSON.stringify(v):v}}</td></tr>`;
}});
}}
walk(DATA.configSnapshot||{{}},'');
document.getElementById('config-table').innerHTML=`<table class="config-table">${{cfgTr}}</table>`;

// Draw waveforms for utterances with audio
DATA.utterances.forEach((u,i)=>{{
let src=audioSrc(u);
if(!src)return;
let svg=document.getElementById('wav-'+i);
if(!svg)return;
let audio=new Audio(src);
audio.addEventListener('loadedmetadata',()=>{{
let ctx=new OfflineAudioContext(1,4096,16000);
let src=ctx.createBufferSource();
src.buffer=null;
fetch(audio.src).then(r=>r.arrayBuffer()).then(buf=>ctx.decodeAudioData(buf)).then(audioBuf=>{{
let data=audioBuf.getChannelData(0);
let w=svg.clientWidth||800,h=40;
let step=Math.max(1,Math.floor(data.length/w));
let points='';
for(let x=0;x<w;x++){{let start=Math.floor(x*step);let end=Math.min(start+step,data.length);let sum=0;for(let j=start;j<end;j++)sum+=Math.abs(data[j]);let avg=sum/(end-start||1);let y=h/2-avg*h/2;points+=`${{x}},${{y.toFixed(1)}} `;}}
svg.innerHTML=`<polyline points="${{points.trim()}}" fill="none" stroke="#f54e00" stroke-width="1" stroke-opacity="0.7"/>`;
}}).catch(()=>{{}});
}});
audio.load();
}});
</script>
</body>
</html>"""

