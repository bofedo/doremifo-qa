"""
DoReMiFo QA — FastAPI backend v1.3
- Multi-upload 1–10 WAV súborov pre jednu bunku
- Automatická detekcia typu zdroja
- Bilingválne UI (SK / EN)
- VAR01 referencia: použije uloženú ak chýba v uploade
"""

import os, shutil, subprocess, tempfile, json
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from typing import List

app = FastAPI(title="DoReMiFo QA")

REFS_DIR = "/app/references"
os.makedirs(REFS_DIR, exist_ok=True)

# ── Detekcia zdroja ───────────────────────────────────────

def detect_source(json_path: str) -> tuple[str, str, float]:
    """Vráti (label_sk, label_en, thresholds_scale)"""
    try:
        with open(json_path) as f:
            j = json.load(f)
        ll = j.get("lowlevel", {})

        def mean(key):
            v = ll.get(key)
            return v.get("mean") if isinstance(v, dict) else v or 0

        flatness   = mean("spectral_flatness_db") or mean("spectral_flatness") or 0
        inharmonic = mean("inharmonicity") or 0
        complexity = mean("spectral_complexity") or 0
        onset_rate = j.get("rhythm", {}).get("onset_rate") or 0

        if onset_rate > 8 and complexity < 5:
            return "Sample / perkusívny", "Sample / percussive", 1.6
        if flatness > -12 and inharmonic > 0.15:
            return "FM syntéza", "FM synthesis", 1.4
        if flatness > -6:
            return "Zmiešaný / hybridný", "Mixed / hybrid", 2.0
        if inharmonic > 0.25 or complexity > 18:
            return "Akustická nahrávka", "Acoustic recording", 2.0
        return "Subtraktívna syntéza", "Subtractive synthesis", 1.0
    except Exception:
        return "Neznámy", "Unknown", 1.5


# ── UI ────────────────────────────────────────────────────

HTML_UI = r"""<!DOCTYPE html>
<html lang="sk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DoReMiFo QA</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f172a; color: #e2e8f0;
    min-height: 100vh;
    display: flex; align-items: flex-start; justify-content: center;
    padding: 2rem;
  }
  .card {
    background: #1e293b; border-radius: 16px;
    padding: 2.5rem; width: 100%; max-width: 560px;
    position: relative;
  }
  .lang-switch {
    position: absolute; top: 1.5rem; right: 1.5rem;
    display: flex; border-radius: 8px; overflow: hidden;
    border: 1px solid #334155;
  }
  .lang-switch button {
    width: auto; padding: .35rem .75rem;
    background: transparent; color: #64748b;
    border: none; font-size: .8rem; font-weight: 600;
    cursor: pointer; transition: background .15s, color .15s;
  }
  .lang-switch button.active { background: #6366f1; color: white; }
  .lang-switch button:hover:not(.active) { background: #0f172a; color: #e2e8f0; }
  h1 { font-size: 1.4rem; color: #f1f5f9; margin-bottom: .25rem; padding-right: 6rem; }
  .sub { color: #64748b; font-size: .82rem; margin-bottom: 2rem; }
  label { display: block; font-size: .82rem; color: #94a3b8; margin-bottom: .4rem; }
  select {
    width: 100%; padding: .6rem .85rem;
    background: #0f172a; color: #e2e8f0;
    border: 1px solid #334155; border-radius: 8px;
    font-size: .92rem; margin-bottom: 1.4rem;
  }
  .drop-zone {
    border: 2px dashed #334155; border-radius: 12px;
    padding: 2rem; text-align: center; color: #475569;
    font-size: .88rem; cursor: pointer;
    transition: border-color .2s, background .2s; margin-bottom: 1.2rem;
  }
  .drop-zone:hover, .drop-zone.drag { border-color: #6366f1; background: #1e2a4a; color: #a5b4fc; }
  .drop-zone .icon { font-size: 1.8rem; margin-bottom: .5rem; }
  .drop-zone .hint { font-size: .75rem; color: #334155; margin-top: .4rem; }
  .file-list { margin-bottom: 1.2rem; display: none; }
  .file-list h3 { font-size: .78rem; color: #475569; text-transform: uppercase; letter-spacing: .05em; margin-bottom: .6rem; }
  .file-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: .4rem; }
  .file-chip {
    background: #0f172a; border-radius: 8px; padding: .4rem .3rem;
    text-align: center; font-size: .75rem; color: #475569; border: 1px solid #1e293b;
  }
  .file-chip.matched { color: #4ade80; border-color: #052e16; background: #052e16; }
  .file-chip .var  { font-weight: 600; font-size: .8rem; }
  .file-chip .name { font-size: .65rem; opacity: .7; margin-top: .1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .notice {
    border-radius: 8px; padding: .65rem .9rem;
    font-size: .8rem; margin-bottom: 1.2rem; display: none; line-height: 1.5;
  }
  .notice.warn { background: #1c1a00; border: 1px solid #854d0e; color: #fde68a; }
  .notice.info { background: #1e3a5f; border: 1px solid #1d4ed8; color: #7dd3fc; }
  .run-btn {
    width: 100%; padding: .75rem; background: #6366f1; color: white;
    border: none; border-radius: 8px; font-size: .95rem; font-weight: 600;
    cursor: pointer; transition: background .2s;
  }
  .run-btn:hover:not(:disabled) { background: #4f46e5; }
  .run-btn:disabled { background: #1e293b; color: #475569; cursor: not-allowed; }
  .progress { margin-top: 1.2rem; display: none; }
  .progress-bar-bg { background: #0f172a; border-radius: 99px; height: 6px; margin-bottom: .5rem; }
  .progress-bar { background: #6366f1; height: 6px; border-radius: 99px; width: 0%; transition: width .3s; }
  .progress-label { font-size: .8rem; color: #64748b; text-align: center; }
  .refs { margin-top: 1.5rem; padding: .9rem 1rem; background: #0f172a; border-radius: 8px; }
  .refs h3 { font-size: .75rem; color: #475569; text-transform: uppercase; letter-spacing: .05em; margin-bottom: .5rem; }
  .ref-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: .35rem; }
  .ref-chip { font-size: .75rem; color: #475569; text-align: center; padding: .3rem; border-radius: 6px; background: #1e293b; }
  .ref-chip.ok { color: #4ade80; background: #052e16; }
</style>
</head>
<body>
<div class="card">
  <div class="lang-switch">
    <button class="active" onclick="setLang('sk')">SK</button>
    <button onclick="setLang('en')">EN</button>
  </div>

  <h1>🎵 DoReMiFo QA</h1>
  <p class="sub" id="t-sub"></p>

  <label id="t-cell-label"></label>
  <select id="cell" onchange="onCellChange()"></select>

  <div class="drop-zone" id="drop"
    ondragover="ev(event,'drag',true)"
    ondragleave="ev(event,'drag',false)"
    ondrop="onDrop(event)"
    onclick="document.getElementById('fi').click()">
    <div class="icon">🎵</div>
    <div id="t-drop-main"></div>
    <div class="hint" id="t-drop-hint"></div>
    <input type="file" id="fi" accept=".wav" multiple style="display:none" onchange="onFiles(this.files)">
  </div>

  <div class="file-list" id="file-list">
    <h3 id="t-variants"></h3>
    <div class="file-grid" id="file-grid"></div>
  </div>

  <div class="notice" id="notice"></div>
  <button class="run-btn" id="btn" disabled onclick="runQA()"></button>

  <div class="progress" id="progress">
    <div class="progress-bar-bg"><div class="progress-bar" id="bar"></div></div>
    <div class="progress-label" id="prog-label"></div>
  </div>

  <div class="refs">
    <h3 id="t-refs"></h3>
    <div class="ref-grid" id="refs-list"></div>
  </div>
</div>

<script>
const CELLS = {
  sk: ['01 — Stabilita / Konsonancia','02 — Introvertná statika','03 — Ascendentná energia',
       '04 — Urgencia','05 — Neutrálna referencia','06 — Kinetická pulzácia',
       '07 — Ascendentná gradácia','08 — Descendentná relaxácia','09 — Ruptúra','10 — Kadencia'],
  en: ['01 — Stability / Consonance','02 — Introverted Stasis','03 — Ascendant Energy',
       '04 — Urgency','05 — Neutral Reference','06 — Kinetic Pulsation',
       '07 — Ascendant Gradation','08 — Descendent Relaxation','09 — Rupture','10 — Cadence']
};
const VAR_NAMES = {
  sk: {VAR01:'Základ',VAR02:'Attack ↑',VAR03:'Attack ↓',VAR04:'Farba ↑',VAR05:'Farba ↓',
       VAR06:'Konsonancia',VAR07:'Disonancia',VAR08:'Hustota ↑',VAR09:'Hustota ↓',VAR10:'Špecifický'},
  en: {VAR01:'Base',VAR02:'Attack ↑',VAR03:'Attack ↓',VAR04:'Timbre ↑',VAR05:'Timbre ↓',
       VAR06:'Consonance',VAR07:'Dissonance',VAR08:'Density ↑',VAR09:'Density ↓',VAR10:'Specific'}
};
const T = {
  sk: {
    sub:'Nahraj 1–10 WAV súborov pre jednu bunku — typ zdroja sa detekuje automaticky',
    cellLabel:'Bunka', dropMain:'Pretiahni WAV súbory sem alebo klikni',
    dropHint:'CELL01_VAR01.wav … CELL01_VAR10.wav · 1 až 10 súborov',
    variants:'Rozpoznané varianty', btn:'Spustiť QA', refs:'Uložené referencie VAR01',
    processing:'Spracovávam', done:'✅ Hotovo — report sa otvára...',
    unmatched:'Nerozpoznané súbory', missing:'Chýbajúce varianty — QA prebehne len pre nahrané',
    var01missing:'VAR01 nebola nahratá — použije sa uložená referencia zo servera',
    var01none:'VAR01 chýba aj na serveri — nahraj najprv VAR01 ako referenciu',
  },
  en: {
    sub:'Upload 1–10 WAV files for one cell — source type is detected automatically',
    cellLabel:'Cell', dropMain:'Drag WAV files here or click',
    dropHint:'CELL01_VAR01.wav … CELL01_VAR10.wav · 1 to 10 files',
    variants:'Recognised variants', btn:'Run QA', refs:'Saved VAR01 references',
    processing:'Processing', done:'✅ Done — opening report...',
    unmatched:'Unrecognised files', missing:'Missing variants — QA will run only for uploaded files',
    var01missing:'VAR01 not uploaded — using saved server reference',
    var01none:'VAR01 missing on server too — please upload VAR01 as reference first',
  }
};

const VARS = ['VAR01','VAR02','VAR03','VAR04','VAR05','VAR06','VAR07','VAR08','VAR09','VAR10'];
const REFS_IDS = ['01','02','03','04','05','06','07','08','09','10'];

let lang = 'sk';
let matched = {};
let savedRefs = [];
let fileObjects = {};

async function fetchRefs() {
  try {
    const r = await fetch('/refs');
    savedRefs = await r.json();
  } catch(e) { savedRefs = []; }
  renderRefs();
}

function setLang(l) {
  lang = l;
  document.querySelectorAll('.lang-switch button').forEach(b =>
    b.classList.toggle('active', b.textContent === l.toUpperCase()));
  const t = T[l];
  document.getElementById('t-sub').textContent       = t.sub;
  document.getElementById('t-cell-label').textContent = t.cellLabel;
  document.getElementById('t-drop-main').textContent  = t.dropMain;
  document.getElementById('t-drop-hint').textContent  = t.dropHint;
  document.getElementById('t-variants').textContent   = t.variants;
  document.getElementById('btn').textContent          = t.btn;
  document.getElementById('t-refs').textContent       = t.refs;

  const sel = document.getElementById('cell');
  const cur = sel.value;
  sel.innerHTML = CELLS[l].map((name,i) => {
    const v = String(i+1).padStart(2,'0');
    return `<option value="${v}" ${v===cur?'selected':''}>${name}</option>`;
  }).join('');

  renderGrid();
  updateNotice();
  renderRefs();
}

function ev(e, cls, add) { e.preventDefault(); document.getElementById('drop').classList.toggle(cls, add); }
function onDrop(e) { e.preventDefault(); document.getElementById('drop').classList.remove('drag'); onFiles(e.dataTransfer.files); }

function onFiles(files) {
  matched = {}; fileObjects = {};
  Array.from(files).forEach(f => {
    const m = f.name.toUpperCase().match(/CELL\d+_(VAR\d+)/);
    if (m && VARS.includes(m[1])) { matched[m[1]] = f.name; fileObjects[m[1]] = f; }
  });
  renderGrid();
  updateNotice();
  document.getElementById('btn').disabled = Object.keys(matched).length === 0;
}

function renderGrid() {
  const grid = document.getElementById('file-grid');
  const list = document.getElementById('file-list');
  if (!Object.keys(matched).length) { list.style.display = 'none'; return; }
  list.style.display = 'block';
  grid.innerHTML = VARS.map(v => {
    const has = matched[v];
    return `<div class="file-chip ${has?'matched':''}">
      <div class="var">${v.replace('VAR','V')}</div>
      <div class="name">${has ? '✓ '+VAR_NAMES[lang][v] : '—'}</div>
    </div>`;
  }).join('');
}

function updateNotice() {
  const el = document.getElementById('notice');
  const t = T[lang];
  const cell = document.getElementById('cell').value;
  const hasVar01Uploaded = !!matched['VAR01'];
  const hasVar01Saved    = savedRefs.includes(cell);
  const nonVars = [];

  // Zobraz upozornenie na VAR01
  if (!hasVar01Uploaded) {
    if (hasVar01Saved) {
      el.className = 'notice info';
      el.textContent = t.var01missing;
      el.style.display = 'block';
    } else if (Object.keys(matched).length > 0) {
      el.className = 'notice warn';
      el.textContent = t.var01none;
      el.style.display = 'block';
      document.getElementById('btn').disabled = true;
    } else {
      el.style.display = 'none';
    }
  } else {
    el.style.display = 'none';
  }
}

function renderRefs() {
  document.getElementById('refs-list').innerHTML = REFS_IDS.map(c =>
    `<div class="ref-chip ${savedRefs.includes(c)?'ok':''}">
      ${savedRefs.includes(c)?'✓':'○'} C${c}
    </div>`
  ).join('');
}

function onCellChange() {
  matched = {}; fileObjects = {};
  renderGrid();
  updateNotice();
  document.getElementById('btn').disabled = true;
}

async function runQA() {
  const btn   = document.getElementById('btn');
  const prog  = document.getElementById('progress');
  const bar   = document.getElementById('bar');
  const lbl   = document.getElementById('prog-label');
  const t     = T[lang];
  const cell  = document.getElementById('cell').value;
  const steps = Object.keys(fileObjects);

  btn.disabled = true;
  prog.style.display = 'block';

  const fd = new FormData();
  fd.append('cell', cell);
  fd.append('lang', lang);
  steps.forEach((varId, i) => {
    fd.append('wavs', fileObjects[varId]);
    lbl.textContent = `${t.processing} ${varId} (${i+1}/${steps.length})...`;
    bar.style.width = Math.round((i+1)/steps.length*80) + '%';
  });

  lbl.textContent = t.processing + '...';
  bar.style.width = '90%';

  try {
    const res = await fetch('/qa', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Server error');
    }
    bar.style.width = '100%';
    lbl.textContent = t.done;
    const html = await res.text();
    const w = window.open('', '_blank');
    w.document.write(html);
    w.document.close();
    await fetchRefs();
  } catch(err) {
    lbl.textContent = '❌ ' + err.message;
  } finally {
    setTimeout(() => { prog.style.display='none'; bar.style.width='0%'; btn.disabled=false; }, 2500);
  }
}

// Init
setLang('sk');
fetchRefs();
</script>
</body>
</html>"""


# ── Endpointy ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def ui():
    return HTML_UI


@app.get("/refs")
async def list_refs():
    saved = []
    for cell in [f"{i:02d}" for i in range(1, 11)]:
        if (os.path.exists(os.path.join(REFS_DIR, f"CELL{cell}_VAR01.wav")) and
            os.path.exists(os.path.join(REFS_DIR, f"CELL{cell}_VAR01.json"))):
            saved.append(cell)
    return saved


@app.post("/qa", response_class=HTMLResponse)
async def run_qa(
    wavs: List[UploadFile] = File(...),
    cell: str              = Form(...),
    lang: str              = Form("sk"),
):
    with tempfile.TemporaryDirectory() as tmp:
        wav_dir  = os.path.join(tmp, "wav")
        json_dir = os.path.join(tmp, "json")
        out_dir  = os.path.join(tmp, "out")
        os.makedirs(wav_dir); os.makedirs(json_dir); os.makedirs(out_dir)

        uploaded_vars = []
        source_label_sk = source_label_en = "Neznámy"
        thr_scale = 1.5

        # Ulož a normalizuj nahrané WAV
        for wav in wavs:
            m = (wav.filename or "").upper().replace(".WAV","")
            m = __import__('re').search(r'(VAR\d+)', m)
            if not m:
                continue
            var_id   = m.group(1)
            wav_name = f"CELL{cell}_{var_id}.wav"
            wav_path = os.path.join(wav_dir, wav_name)
            with open(wav_path, "wb") as f:
                shutil.copyfileobj(wav.file, f)

            norm = wav_path.replace(".wav", "_norm.wav")
            subprocess.run(["sox", wav_path, "-r", "44100", "-c", "1", "-b", "24", norm], check=True)
            os.replace(norm, wav_path)
            uploaded_vars.append(var_id)

        if not uploaded_vars:
            return JSONResponse(status_code=400, content={"error": "Žiadne platné WAV súbory" if lang=="sk" else "No valid WAV files"})

        # Essentia extrakcia pre nahrané varianty
        for var_id in uploaded_vars:
            wav_path  = os.path.join(wav_dir, f"CELL{cell}_{var_id}.wav")
            json_path = os.path.join(json_dir, f"CELL{cell}_{var_id}.json")
            result = subprocess.run([
                "essentia_streaming_extractor_music", wav_path, json_path
            ], capture_output=True)
            if result.returncode != 0:
                continue
            # Detekcia zdroja z prvého úspešného JSON
            if source_label_sk == "Neznámy":
                source_label_sk, source_label_en, thr_scale = detect_source(json_path)

        # VAR01 — ulož referenciu ak bola nahratá
        if "VAR01" in uploaded_vars:
            shutil.copy(
                os.path.join(wav_dir,  f"CELL{cell}_VAR01.wav"),
                os.path.join(REFS_DIR, f"CELL{cell}_VAR01.wav")
            )
            shutil.copy(
                os.path.join(json_dir, f"CELL{cell}_VAR01.json"),
                os.path.join(REFS_DIR, f"CELL{cell}_VAR01.json")
            )
        else:
            # VAR01 nebola nahratá — skús načítať zo servera
            ref_wav  = os.path.join(REFS_DIR, f"CELL{cell}_VAR01.wav")
            ref_json = os.path.join(REFS_DIR, f"CELL{cell}_VAR01.json")
            if not os.path.exists(ref_wav):
                msg = (f"Chýba VAR01 referencia pre CELL{cell}. Nahraj najprv VAR01."
                       if lang == "sk" else
                       f"Missing VAR01 reference for CELL{cell}. Please upload VAR01 first.")
                return JSONResponse(status_code=400, content={"error": msg})
            shutil.copy(ref_wav,  os.path.join(wav_dir,  f"CELL{cell}_VAR01.wav"))
            shutil.copy(ref_json, os.path.join(json_dir, f"CELL{cell}_VAR01.json"))

        # QA analýza
        env = os.environ.copy()
        env["DOREMIFO_THR_SCALE"] = str(thr_scale)
        env["DOREMIFO_SOURCE"]    = source_label_sk

        proc = subprocess.run([
            "python3", "/app/analyze_cell.py",
            "--cell", cell,
            "--in",   json_dir,
            "--wav",  wav_dir,
            "--out",  out_dir,
        ], capture_output=True, text=True, env=env)

        report = os.path.join(out_dir, f"cell{cell}_qa_report.html")
        if not os.path.exists(report):
            return JSONResponse(status_code=500, content={
                "error": "Report nebol vygenerovaný" if lang=="sk" else "Report not generated",
                "detail": proc.stderr
            })

        with open(report) as f:
            html = f.read()

        # Badge — detekovaný zdroj + nahrané varianty
        source_label = source_label_sk if lang == "sk" else source_label_en
        detected_txt = ("Detekovaný zdroj" if lang=="sk" else "Detected source")
        uploaded_txt = ("Nahrané varianty" if lang=="sk" else "Uploaded variants")
        var01_txt    = (("⚠ VAR01 zo servera" if "VAR01" not in uploaded_vars else "")
                        if lang=="sk" else
                        ("⚠ VAR01 from server" if "VAR01" not in uploaded_vars else ""))

        badge = f'''<div style="margin-bottom:1rem;padding:.75rem 1rem;
            background:#1e293b;border-radius:10px;font-size:.85rem;
            display:flex;gap:1.5rem;flex-wrap:wrap">
          <span style="color:#7dd3fc">🔍 {detected_txt}: <strong>{source_label}</strong></span>
          <span style="color:#86efac">📂 {uploaded_txt}: {", ".join(sorted(uploaded_vars))}</span>
          {"<span style='color:#fde68a'>"+var01_txt+"</span>" if var01_txt else ""}
        </div>'''

        html = html.replace('<div class="summary">', badge + '<div class="summary">', 1)
        return HTMLResponse(content=html)