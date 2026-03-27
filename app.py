"""
DoReMiFo QA — FastAPI backend v2.1
+ CAWI response storage
+ HTTP Basic Auth (heslo v Railway Variables)
"""

import os, shutil, subprocess, tempfile, json, sqlite3, secrets, re, zipfile, io, csv, threading
from fastapi import FastAPI, File, UploadFile, Form, Request, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import List

app = FastAPI(title="DoReMiFo QA")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://study.doremifo.com", "http://localhost"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

DATA_DIR = "/app/data"
REFS_DIR = os.path.join(DATA_DIR, "references")
ARCH_DIR = os.path.join(DATA_DIR, "archive")
DB_PATH  = os.path.join(DATA_DIR, "doremifo.db")
os.makedirs(REFS_DIR, exist_ok=True)
os.makedirs(ARCH_DIR, exist_ok=True)

SLACK_WEBHOOK = "https://hooks.slack.com/services/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"

# ── HTTP Basic Auth ───────────────────────────────────────
security   = HTTPBasic()
ADMIN_USER = os.environ.get("DRF_ADMIN_USER", "")
ADMIN_PASS = os.environ.get("DRF_ADMIN_PASSWORD", "")

def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not ADMIN_USER or not ADMIN_PASS:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Admin credentials not configured")
    ok_user = secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), ADMIN_PASS.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Prístup zamietnutý",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

VARS_ALL  = [f"VAR{i:02d}" for i in range(1, 11)]
CELLS_ALL = [f"{i:02d}" for i in range(1, 11)]

CELL_NAMES = {
    "sk": {
        "01":"Stabilita / Konsonancia","02":"Introvertná statika","03":"Ascendentná energia",
        "04":"Urgencia","05":"Neutrálna referencia","06":"Kinetická pulzácia",
        "07":"Ascendentná gradácia","08":"Descendentná relaxácia","09":"Ruptúra","10":"Kadencia"
    },
    "en": {
        "01":"Stability / Consonance","02":"Introverted Stasis","03":"Ascendant Energy",
        "04":"Urgency","05":"Neutral Reference","06":"Kinetic Pulsation",
        "07":"Ascendant Gradation","08":"Descendent Relaxation","09":"Rupture","10":"Cadence"
    }
}

# ── Databáza ──────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS composers (
                token      TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                token       TEXT NOT NULL,
                cell        TEXT NOT NULL,
                var_id      TEXT NOT NULL,
                filename    TEXT,
                source      TEXT,
                uploaded_at TEXT DEFAULT (datetime('now')),
                UNIQUE(token, cell, var_id)
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS cawi_responses (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                prolific_pid TEXT,
                study_id     TEXT,
                session_id   TEXT,
                source       TEXT DEFAULT 'prolific',
                sensitivity  INTEGER,
                headphone_flag INTEGER DEFAULT 0,
                attention_flag INTEGER DEFAULT 0,
                hard_flag    INTEGER DEFAULT 0,
                duplicate_delta_valence REAL,
                duplicate_delta_arousal REAL,
                completed_at TEXT,
                raw_json     TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS cawi_atoms (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                response_id     INTEGER NOT NULL,
                prolific_pid    TEXT,
                source          TEXT,
                atom_index      INTEGER,
                cell            TEXT,
                var             TEXT,
                is_duplicate    INTEGER DEFAULT 0,
                valence         INTEGER,
                arousal         INTEGER,
                trustworthiness INTEGER,
                action_urge     INTEGER,
                distinctiveness INTEGER,
                attribute       TEXT,
                confidence      INTEGER,
                ux_affordance   TEXT,
                sem_diff        TEXT,
                timestamp       INTEGER,
                FOREIGN KEY (response_id) REFERENCES cawi_responses(id)
            )""")

init_db()

# ── Slack ─────────────────────────────────────────────────

def slack_notify(msg: str):
    try:
        import urllib.request
        data = json.dumps({"text": msg}).encode()
        req  = urllib.request.Request(
            SLACK_WEBHOOK, data=data,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

# ── Detekcia zdroja ───────────────────────────────────────

def detect_source(json_path: str):
    try:
        with open(json_path) as f:
            j = json.load(f)
        ll = j.get("lowlevel", {})
        def mean(k):
            v = ll.get(k)
            return v.get("mean") if isinstance(v, dict) else (v or 0)
        flatness       = mean("spectral_flatness_db") or mean("spectral_flatness") or 0
        inharmonic     = mean("inharmonicity") or 0
        complexity     = mean("spectral_complexity") or 0
        onset_rate     = j.get("rhythm", {}).get("onset_rate") or 0
        pitch_salience = mean("pitch_salience") or 0
        if onset_rate > 8 and complexity < 5:
            return "Sample / perkusívny", "Sample / percussive"
        if inharmonic > 0.15 and pitch_salience < 0.6:
            return "FM syntéza", "FM synthesis"
        if inharmonic > 0.25 or complexity > 18:
            return "Akustická nahrávka", "Acoustic recording"
        if flatness > -6 and pitch_salience < 0.5:
            return "Zmiešaný / hybridný", "Mixed / hybrid"
        return "Subtraktívna syntéza", "Subtractive synthesis"
    except Exception:
        return "Neznámy", "Unknown"

# ── Upload UI ─────────────────────────────────────────────

def build_upload_ui(composer_name: str, progress: dict, lang: str = "sk") -> str:
    t = {
        "sk": {
            "greeting": f"Ahoj, {composer_name}",
            "sub": "Vyber bunku a nahraj WAV súbory",
            "cell_label": "Bunka", "drop": "Pretiahni WAV súbory sem alebo klikni",
            "hint": "CELL01_VAR01.wav … CELL01_VAR10.wav", "btn": "Nahrať",
            "processing": "Spracovávam...",
            "done_all": "✅ Bunka kompletná! Výskumný tím bol notifikovaný.",
            "done_part": "✅ Súbory nahrané.", "error": "Chyba",
            "progress_label": "Celkový progress",
        },
        "en": {
            "greeting": f"Hello, {composer_name}",
            "sub": "Select a cell and upload WAV files",
            "cell_label": "Cell", "drop": "Drag WAV files here or click",
            "hint": "CELL01_VAR01.wav … CELL01_VAR10.wav", "btn": "Upload",
            "processing": "Processing...",
            "done_all": "✅ Cell complete! The research team has been notified.",
            "done_part": "✅ Files uploaded.", "error": "Error",
            "progress_label": "Overall progress",
        }
    }[lang]

    total_uploaded = sum(progress.values())
    total_pct      = round(total_uploaded / 100 * 100)

    cell_chips = ""
    for c in CELLS_ALL:
        cnt   = progress.get(c, 0)
        pct   = round(cnt / 10 * 100)
        color = "#22c55e" if cnt == 10 else "#6366f1" if cnt > 0 else "#334155"
        cell_chips += f"""<div class="cell-chip" onclick="selectCell('{c}')" id="cc{c}">
            <div class="cn">C{c}</div>
            <div class="cpct" style="color:{'#4ade80' if cnt==10 else '#a5b4fc' if cnt>0 else '#475569'}">{cnt}/10</div>
            <div class="cbar-bg"><div class="cbar" style="width:{pct}%;background:{color}"></div></div>
        </div>"""

    var_chips = "".join(f"""<div class="var-chip" id="vc{v}">
        <div class="vn">{v.replace('VAR','V')}</div><div class="vi">○</div>
    </div>""" for v in VARS_ALL)

    return f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DoReMiFo QA</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;
       color:#e2e8f0;min-height:100vh;display:flex;align-items:flex-start;
       justify-content:center;padding:2rem}}
  .card{{background:#1e293b;border-radius:16px;padding:2.5rem;width:100%;
         max-width:560px;position:relative}}
  .lang{{position:absolute;top:1.5rem;right:1.5rem;display:flex;border-radius:8px;
         overflow:hidden;border:1px solid #334155}}
  .lang button{{padding:.3rem .7rem;background:transparent;color:#64748b;border:none;
               font-size:.78rem;font-weight:600;cursor:pointer}}
  .lang button.active{{background:#6366f1;color:white}}
  h1{{font-size:1.3rem;color:#f1f5f9;margin-bottom:.2rem;padding-right:5rem}}
  .sub{{color:#64748b;font-size:.82rem;margin-bottom:1.5rem}}
  .section-label{{font-size:.75rem;color:#475569;text-transform:uppercase;
                  letter-spacing:.05em;margin-bottom:.5rem}}
  .total-progress{{margin-bottom:1.5rem}}
  .prog-top{{display:flex;justify-content:space-between;font-size:.8rem;
             color:#94a3b8;margin-bottom:.4rem}}
  .prog-bg{{background:#0f172a;border-radius:99px;height:6px}}
  .prog-bar{{background:#6366f1;height:6px;border-radius:99px;transition:width .4s}}
  .cell-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:.4rem;margin-bottom:1.5rem}}
  .cell-chip{{background:#0f172a;border-radius:8px;padding:.5rem .3rem;text-align:center;
              cursor:pointer;border:1px solid #1e293b;transition:border-color .15s}}
  .cell-chip:hover{{border-color:#6366f1}}
  .cell-chip.selected{{border-color:#6366f1;background:#1e2a4a}}
  .cn{{font-size:.78rem;font-weight:600}}
  .cpct{{font-size:.68rem;margin:.1rem 0}}
  .cbar-bg{{background:#1e293b;border-radius:99px;height:3px;margin-top:.2rem}}
  .cbar{{height:3px;border-radius:99px;transition:width .3s}}
  .upload-section{{display:none}}
  .upload-section.visible{{display:block}}
  .selected-cell-title{{font-size:.9rem;color:#a5b4fc;font-weight:600;margin-bottom:1rem}}
  .var-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:.4rem;margin-bottom:1rem}}
  .var-chip{{background:#0f172a;border-radius:8px;padding:.4rem .3rem;
             text-align:center;border:1px solid #1e293b}}
  .var-chip.done{{background:#052e16;border-color:#14532d;color:#4ade80}}
  .vn{{font-size:.75rem;font-weight:600}}
  .vi{{font-size:.7rem;margin-top:.1rem;opacity:.8}}
  .drop{{border:2px dashed #334155;border-radius:12px;padding:1.8rem;text-align:center;
         color:#475569;font-size:.85rem;cursor:pointer;
         transition:border-color .2s,background .2s;margin-bottom:1rem}}
  .drop:hover,.drop.drag{{border-color:#6366f1;background:#1e2a4a;color:#a5b4fc}}
  .drop .icon{{font-size:1.6rem;margin-bottom:.4rem}}
  .drop .hint{{font-size:.72rem;color:#334155;margin-top:.3rem}}
  button.run{{width:100%;padding:.7rem;background:#6366f1;color:white;border:none;
              border-radius:8px;font-size:.92rem;font-weight:600;
              cursor:pointer;transition:background .2s}}
  button.run:hover:not(:disabled){{background:#4f46e5}}
  button.run:disabled{{background:#1e293b;color:#475569;cursor:not-allowed}}
  .status{{margin-top:1rem;padding:.65rem 1rem;border-radius:8px;
           font-size:.85rem;display:none}}
  .status.info{{background:#1e3a5f;color:#7dd3fc;display:block}}
  .status.ok{{background:#052e16;color:#86efac;display:block}}
  .status.err{{background:#450a0a;color:#fca5a5;display:block}}
</style></head><body>
<div class="card">
  <div class="lang">
    <button class="{'active' if lang=='sk' else ''}" onclick="reload('sk')">SK</button>
    <button class="{'active' if lang=='en' else ''}" onclick="reload('en')">EN</button>
  </div>
  <h1>🎵 {t['greeting']}</h1>
  <p class="sub">{t['sub']}</p>
  <div class="total-progress">
    <div class="prog-top">
      <span>{t['progress_label']}</span>
      <span>{total_uploaded} / 100</span>
    </div>
    <div class="prog-bg"><div class="prog-bar" style="width:{total_pct}%"></div></div>
  </div>
  <div class="section-label">{t['cell_label']}</div>
  <div class="cell-grid">{cell_chips}</div>
  <div class="upload-section" id="upload-section">
    <div class="selected-cell-title" id="cell-title"></div>
    <div class="var-grid">{var_chips}</div>
    <div class="drop" id="drop"
      ondragover="ev(event,true)" ondragleave="ev(event,false)" ondrop="onDrop(event)"
      onclick="document.getElementById('fi').click()">
      <div class="icon">🎵</div>
      <div>{t['drop']}</div>
      <div class="hint">{t['hint']}</div>
      <input type="file" id="fi" accept=".wav" multiple style="display:none"
             onchange="onFiles(this.files)">
    </div>
    <button class="run" id="btn" disabled onclick="upload()">{t['btn']}</button>
    <div class="status" id="status"></div>
  </div>
</div>
<script>
const PROGRESS   = {json.dumps(progress)};
const CELL_NAMES = {json.dumps(CELL_NAMES[lang])};
const T = {{
  processing:"{t['processing']}",done_all:"{t['done_all']}",
  done_part:"{t['done_part']}",error:"{t['error']}",
}};
const VARS = {json.dumps(VARS_ALL)};
let selectedCell=null, files={{}};
function reload(l){{window.location.href=window.location.pathname+'?lang='+l}}
function ev(e,on){{e.preventDefault();document.getElementById('drop').classList.toggle('drag',on)}}
function onDrop(e){{e.preventDefault();document.getElementById('drop').classList.remove('drag');onFiles(e.dataTransfer.files)}}
function selectCell(cell){{
  selectedCell=cell;
  document.querySelectorAll('.cell-chip').forEach(c=>c.classList.remove('selected'));
  document.getElementById('cc'+cell).classList.add('selected');
  document.getElementById('upload-section').classList.add('visible');
  document.getElementById('cell-title').textContent='CELL'+cell+' — '+CELL_NAMES[cell];
  files={{}};document.getElementById('btn').disabled=true;
  const uploaded=PROGRESS[cell]||{{}};
  VARS.forEach(v=>{{
    const chip=document.getElementById('vc'+v);
    const done=uploaded[v]||false;
    chip.className='var-chip'+(done?' done':'');
    chip.querySelector('.vi').textContent=done?'✓':'○';
  }});
}}
function onFiles(f){{
  files={{}};
  Array.from(f).forEach(file=>{{
    const m=file.name.toUpperCase().match(/(VAR\d+)/);
    if(m) files[m[1]]=file;
  }});
  document.getElementById('btn').disabled=Object.keys(files).length===0;
}}
async function upload(){{
  const btn=document.getElementById('btn'),st=document.getElementById('status');
  btn.disabled=true;st.className='status info';st.textContent=T.processing;
  const fd=new FormData();
  fd.append('cell',selectedCell);
  Object.values(files).forEach(f=>fd.append('wavs',f));
  try{{
    const res=await fetch(window.location.pathname+'/upload',{{method:'POST',body:fd}});
    const data=await res.json();
    if(!res.ok) throw new Error(data.error||'Error');
    st.className='status ok';
    st.textContent=data.complete?T.done_all:T.done_part;
    if(data.report_html){{
      const w=window.open('','_blank');
      w.document.write(data.report_html);
      w.document.close();
    }}
    setTimeout(()=>window.location.reload(),2000);
  }}catch(e){{
    st.className='status err';st.textContent=T.error+': '+e.message;btn.disabled=false;
  }}
}}
</script></body></html>"""

# ── Admin UI ──────────────────────────────────────────────

def build_admin_ui(composers: list, progress_map: dict) -> str:
    rows = ""
    for c in composers:
        token = c["token"]
        cells_html = ""
        total = 0
        for cell in CELLS_ALL:
            cnt = progress_map.get(token, {}).get(cell, 0)
            total += cnt
            if cnt == 10:
                cells_html += '<td style="color:#4ade80;text-align:center;font-size:.8rem">✓</td>'
            elif cnt > 0:
                cells_html += f'<td style="color:#a5b4fc;text-align:center;font-size:.8rem">{cnt}</td>'
            else:
                cells_html += '<td style="color:#334155;text-align:center;font-size:.8rem">—</td>'
        pct = round(total / 100 * 100)
        cell_options = "".join(f'<option value="{c}">{c}</option>' for c in CELLS_ALL)
        rows += f"""<tr>
          <td><strong>{c['name']}</strong><br>
            <span style="font-size:.72rem;color:#475569">{c['created_at'][:10]}</span></td>
          {cells_html}
          <td style="font-size:.8rem;color:#94a3b8">{total}/100<br>
            <div style="background:#0f172a;border-radius:99px;height:4px;margin-top:.3rem;width:80px">
              <div style="width:{pct}%;background:#6366f1;height:4px;border-radius:99px"></div>
            </div></td>
          <td>
            <code style="font-size:.72rem;color:#7dd3fc">/upload/{token}</code><br>
            <a href="/download/{token}"
               style="font-size:.72rem;color:#4ade80;text-decoration:none">⬇ Všetko</a>
            &nbsp;
            <select onchange="if(this.value) window.location='/download/{token}?cell='+this.value.padStart(2,'0')"
              style="font-size:.72rem;background:#0f172a;color:#94a3b8;border:1px solid #334155;border-radius:4px;padding:.1rem .3rem;cursor:pointer">
              <option value="">⬇ Bunka...</option>
              {cell_options}
            </select>
          </td>
        </tr>"""

    cell_headers = "".join(f'<th style="text-align:center">C{c}</th>' for c in CELLS_ALL)
    empty = '<tr><td colspan="14" style="color:#475569;text-align:center;padding:2rem">Zatiaľ žiadni skladatelia</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="sk"><head><meta charset="UTF-8"><title>DoReMiFo Admin</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem}}
  h1{{font-size:1.4rem;color:#f1f5f9;margin-bottom:.3rem}}
  .meta{{color:#64748b;font-size:.82rem;margin-bottom:2rem}}
  .new-form{{background:#1e293b;border-radius:12px;padding:1.5rem;margin-bottom:2rem;
             display:flex;gap:.8rem;flex-wrap:wrap;align-items:flex-end}}
  .new-form label{{font-size:.8rem;color:#94a3b8;display:block;margin-bottom:.3rem}}
  .new-form input{{padding:.55rem .8rem;background:#0f172a;color:#e2e8f0;
    border:1px solid #334155;border-radius:8px;font-size:.9rem}}
  .new-form button{{padding:.55rem 1.2rem;background:#6366f1;color:white;border:none;
    border-radius:8px;font-size:.9rem;font-weight:600;cursor:pointer}}
  .new-form button:hover{{background:#4f46e5}}
  .result{{background:#052e16;color:#86efac;padding:.65rem 1rem;border-radius:8px;
           font-size:.82rem;margin-bottom:1.5rem;display:none;word-break:break-all}}
  .tbl-wrap{{overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;font-size:.85rem}}
  th{{background:#1e293b;color:#94a3b8;text-align:left;padding:.6rem .8rem;
      font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}}
  td{{padding:.6rem .8rem;border-bottom:1px solid #1e293b;vertical-align:middle}}
  tr:hover td{{background:#1e293b55}}
</style></head><body>
<h1>🎵 DoReMiFo Admin</h1>
<div class="meta">Správa skladateľov ·
  <a href="/admin" style="color:#6366f1">Obnoviť</a> ·
  <a href="/responses/stats" style="color:#a5b4fc">📊 CAWI stats</a> ·
  <a href="/responses/export" style="color:#4ade80">⬇ Export CSV</a>
</div>
<div class="new-form">
  <div><label>Meno skladateľa</label>
    <input type="text" id="nm" placeholder="Jan Novak"></div>
  <button onclick="newComposer()">Vygenerovať link</button>
</div>
<div class="result" id="result"></div>
<div class="tbl-wrap">
<table><thead><tr>
  <th>Skladateľ</th>{cell_headers}<th>Celkom</th><th>Link</th>
</tr></thead>
<tbody>{rows if rows else empty}</tbody>
</table></div>
<script>
async function newComposer(){{
  const name=document.getElementById('nm').value.trim();
  if(!name) return;
  const res=await fetch('/admin/new-composer',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name}})}});
  const data=await res.json();
  const el=document.getElementById('result');
  el.style.display='block';
  el.textContent='✅ Link: '+window.location.origin+'/upload/'+data.token;
  setTimeout(()=>window.location.reload(),3000);
}}
</script></body></html>"""

# ── Routes ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html lang="sk"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DoReMiFo QA</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0f172a;color:#e2e8f0;min-height:100vh;
       display:flex;align-items:center;justify-content:center;padding:2rem}
  .card{background:#1e293b;border-radius:16px;padding:3rem 2.5rem;
        width:100%;max-width:480px;text-align:center}
  h1{font-size:1.6rem;color:#f1f5f9;margin-bottom:.5rem}
  p{color:#64748b;font-size:.9rem;line-height:1.6;margin-bottom:1rem}
  .note{font-size:.8rem;color:#334155;margin-top:2rem}
</style></head><body>
<div class="card">
  <h1>🎵 DoReMiFo QA</h1>
  <p>Platforma pre akustickú analýzu a QA<br>výskumného projektu DoReMiFo.</p>
  <p>Ak si skladateľ, použi osobný link<br>ktorý si dostal od výskumného tímu.</p>
  <div class="note">doremifo.com · app.doremifo.com</div>
</div>
</body></html>"""


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
async def admin_ui(admin=Depends(require_admin)):
    with get_db() as db:
        composers = [dict(r) for r in db.execute(
            "SELECT * FROM composers ORDER BY created_at DESC").fetchall()]
        uploads = db.execute("SELECT token, cell, var_id FROM uploads").fetchall()
    progress_map = {}
    for u in uploads:
        progress_map.setdefault(u["token"], {}).setdefault(u["cell"], 0)
        progress_map[u["token"]][u["cell"]] += 1
    return build_admin_ui(composers, progress_map)


@app.post("/admin/new-composer")
async def new_composer(req: Request):
    body = await req.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Chýba meno"})
    token = secrets.token_urlsafe(16)
    with get_db() as db:
        db.execute("INSERT INTO composers (token, name) VALUES (?,?)", (token, name))
    return {"token": token}


@app.get("/upload/{token}", response_class=HTMLResponse)
async def upload_ui(token: str, lang: str = "sk"):
    with get_db() as db:
        c = db.execute("SELECT * FROM composers WHERE token=?", (token,)).fetchone()
        if not c:
            return HTMLResponse(
                "<h3 style='font-family:sans-serif;padding:2rem'>🔒 Neplatný link</h3>",
                status_code=404)
        rows = db.execute(
            "SELECT cell, var_id FROM uploads WHERE token=?", (token,)).fetchall()
    progress = {}
    for r in rows:
        progress.setdefault(r["cell"], {})[r["var_id"]] = True
    progress_counts = {cell: len(vars_) for cell, vars_ in progress.items()}
    return build_upload_ui(c["name"], progress_counts, lang)


@app.post("/upload/{token}/upload")
async def do_upload(
    token: str,
    cell: str              = Form(...),
    wavs: List[UploadFile] = File(...)
):
    with get_db() as db:
        c = db.execute("SELECT * FROM composers WHERE token=?", (token,)).fetchone()
        if not c:
            return JSONResponse(status_code=404, content={"error": "Neplatný token"})
    name = c["name"]

    composer_dir = os.path.join(ARCH_DIR, token, f"cell{cell}")
    os.makedirs(composer_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        wav_dir  = os.path.join(tmp, "wav")
        json_dir = os.path.join(tmp, "json")
        os.makedirs(wav_dir)
        os.makedirs(json_dir)

        uploaded_now = []
        for wav in wavs:
            m = re.search(r'(VAR\d+)', (wav.filename or "").upper())
            if not m:
                continue
            var_id   = m.group(1)
            wav_name = f"CELL{cell}_{var_id}.wav"
            wav_path = os.path.join(wav_dir, wav_name)
            with open(wav_path, "wb") as f:
                shutil.copyfileobj(wav.file, f)

            norm = wav_path.replace(".wav", "_norm.wav")
            try:
                subprocess.run(
                    ["sox", wav_path, "-r", "44100", "-c", "1", "-b", "24", norm],
                    check=True, capture_output=True)
                os.replace(norm, wav_path)
            except Exception:
                pass

            json_path = os.path.join(json_dir, f"CELL{cell}_{var_id}.json")
            subprocess.run(
                ["essentia_streaming_extractor_music", wav_path, json_path],
                capture_output=True)

            shutil.copy(wav_path, os.path.join(composer_dir, wav_name))
            if os.path.exists(json_path):
                shutil.copy(json_path, os.path.join(
                    composer_dir, f"CELL{cell}_{var_id}.json"))

            if var_id == "VAR01":
                shutil.copy(wav_path, os.path.join(
                    REFS_DIR, f"CELL{cell}_VAR01_{token}.wav"))
                if os.path.exists(json_path):
                    shutil.copy(json_path, os.path.join(
                        REFS_DIR, f"CELL{cell}_VAR01_{token}.json"))

            source_sk = "Neznámy"
            if os.path.exists(json_path):
                source_sk, _ = detect_source(json_path)

            with get_db() as db:
                db.execute("""INSERT OR REPLACE INTO uploads
                    (token, cell, var_id, filename, source) VALUES (?,?,?,?,?)""",
                    (token, cell, var_id, wav_name, source_sk))

            uploaded_now.append(var_id)

    with get_db() as db:
        total_cell = db.execute(
            "SELECT COUNT(*) as n FROM uploads WHERE token=? AND cell=?",
            (token, cell)).fetchone()["n"]

    complete = total_cell >= 10
    if complete:
        slack_notify(
            f"🎵 *DoReMiFo QA* — bunka kompletná!\n"
            f"*Skladateľ:* {name}\n"
            f"*Bunka:* CELL{cell} — {CELL_NAMES['sk'][cell]}\n"
            f"*Varianty:* 10/10 ✅"
        )

    report_html = None
    ref_wav  = os.path.join(REFS_DIR, f"CELL{cell}_VAR01_{token}.wav")
    ref_json = os.path.join(REFS_DIR, f"CELL{cell}_VAR01_{token}.json")

    if os.path.exists(ref_wav) and os.path.exists(ref_json) and uploaded_now:
        with tempfile.TemporaryDirectory() as tmp2:
            w2 = os.path.join(tmp2, "wav")
            j2 = os.path.join(tmp2, "json")
            o2 = os.path.join(tmp2, "out")
            os.makedirs(w2); os.makedirs(j2); os.makedirs(o2)
            src_dir = os.path.join(ARCH_DIR, token, f"cell{cell}")
            if os.path.exists(src_dir):
                for fname in os.listdir(src_dir):
                    if fname.endswith(".wav"):
                        shutil.copy(os.path.join(src_dir, fname), os.path.join(w2, fname))
                    elif fname.endswith(".json"):
                        shutil.copy(os.path.join(src_dir, fname), os.path.join(j2, fname))
            proc = subprocess.run([
                "python3", "/app/analyze_cell.py",
                "--cell", cell, "--in", j2, "--wav", w2, "--out", o2,
            ], capture_output=True, text=True)
            report_path = os.path.join(o2, f"cell{cell}_qa_report.html")
            if os.path.exists(report_path):
                with open(report_path) as f:
                    report_html = f.read()

    return {"ok": True, "complete": complete,
            "uploaded": uploaded_now, "total_cell": total_cell,
            "report_html": report_html}


@app.get("/download/{token}")
async def download_composer(token: str, cell: str = "", admin=Depends(require_admin)):
    with get_db() as db:
        c = db.execute("SELECT * FROM composers WHERE token=?", (token,)).fetchone()
        if not c:
            return JSONResponse(status_code=404, content={"error": "Skladateľ nenájdený"})
    composer_dir = os.path.join(ARCH_DIR, token)
    if not os.path.exists(composer_dir):
        return JSONResponse(status_code=404, content={"error": "Žiadne súbory"})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if cell:
            cell_dir = os.path.join(composer_dir, f"cell{cell.zfill(2)}")
            if os.path.exists(cell_dir):
                for fname in sorted(os.listdir(cell_dir)):
                    zf.write(os.path.join(cell_dir, fname), f"cell{cell.zfill(2)}/{fname}")
        else:
            for cd in sorted(os.listdir(composer_dir)):
                full = os.path.join(composer_dir, cd)
                if os.path.isdir(full):
                    for fname in sorted(os.listdir(full)):
                        zf.write(os.path.join(full, fname), f"{cd}/{fname}")

    buf.seek(0)
    name = c["name"].replace(" ", "_")
    suffix = f"_cell{cell.zfill(2)}" if cell else ""
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=doremifo_{name}{suffix}.zip"})


# ── CAWI Response Storage ─────────────────────────────────

@app.post("/responses")
async def save_response(req: Request):
    try:
        data = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    pid        = data.get("prolific_pid", "")
    study_id   = data.get("study_id", "")
    session_id = data.get("session_id", "")
    source     = data.get("source", "prolific")

    with get_db() as db:
        cur = db.execute("""
            INSERT INTO cawi_responses
            (prolific_pid, study_id, session_id, source, sensitivity,
             headphone_flag, attention_flag, hard_flag,
             duplicate_delta_valence, duplicate_delta_arousal,
             completed_at, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
            pid, study_id, session_id, source,
            data.get("sensitivity"),
            int(data.get("headphone_flag", False)),
            int(data.get("attention_flag", False)),
            int(data.get("hard_flag", False)),
            data.get("duplicate_delta_valence"),
            data.get("duplicate_delta_arousal"),
            data.get("completed_at"),
            json.dumps(data),
        ))
        response_id = cur.lastrowid

        for atom in data.get("responses", []):
            sem = atom.get("sem_diff", {})
            db.execute("""
                INSERT INTO cawi_atoms
                (response_id, prolific_pid, source, atom_index, cell, var,
                 is_duplicate, valence, arousal, trustworthiness,
                 action_urge, distinctiveness, attribute, confidence,
                 ux_affordance, sem_diff, timestamp)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                response_id, pid, source,
                atom.get("atom_index"),
                atom.get("cell"),
                atom.get("var"),
                int(atom.get("is_duplicate", False)),
                atom.get("valence"),
                atom.get("arousal"),
                atom.get("trustworthiness"),
                atom.get("action_urge"),
                atom.get("distinctiveness"),
                atom.get("attribute"),
                atom.get("confidence"),
                atom.get("ux_affordance"),
                json.dumps(sem),
                atom.get("timestamp"),
            ))

    slack_notify(
        f"🎵 *Sonic Atoms* — nová odpoveď!\n"
        f"*PID:* {pid}\n"
        f"*Zdroj:* {source}\n"
        f"*Atómov:* {len(data.get('responses', []))}"
    )

    return {"ok": True, "response_id": response_id}


@app.get("/responses/export")
async def export_responses(fmt: str = "csv", admin=Depends(require_admin)):

    with get_db() as db:
        atoms = db.execute("""
            SELECT
                r.prolific_pid, r.study_id, r.session_id, r.source,
                r.sensitivity, r.headphone_flag, r.attention_flag,
                r.hard_flag, r.duplicate_delta_valence,
                r.duplicate_delta_arousal, r.completed_at,
                a.atom_index, a.cell, a.var, a.is_duplicate,
                a.valence, a.arousal, a.trustworthiness,
                a.action_urge, a.distinctiveness,
                a.attribute, a.confidence, a.ux_affordance, a.sem_diff
            FROM cawi_atoms a
            JOIN cawi_responses r ON r.id = a.response_id
            ORDER BY r.id, a.atom_index
        """).fetchall()

    if fmt == "json":
        return JSONResponse([dict(a) for a in atoms])

    buf = io.StringIO()
    if atoms:
        w = csv.DictWriter(buf, fieldnames=atoms[0].keys())
        w.writeheader()
        w.writerows([dict(a) for a in atoms])

    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sonic_atoms_responses.csv"}
    )


@app.get("/responses/stats")
async def response_stats(admin=Depends(require_admin)):

    with get_db() as db:
        total    = db.execute("SELECT COUNT(*) FROM cawi_responses").fetchone()[0]
        prolific = db.execute("SELECT COUNT(*) FROM cawi_responses WHERE source='prolific'").fetchone()[0]
        social   = db.execute("SELECT COUNT(*) FROM cawi_responses WHERE source='social'").fetchone()[0]
        atoms    = db.execute("SELECT COUNT(*) FROM cawi_atoms WHERE is_duplicate=0").fetchone()[0]
        flagged  = db.execute("SELECT COUNT(*) FROM cawi_responses WHERE hard_flag=1").fetchone()[0]
        coverage = db.execute("""
            SELECT COUNT(*) FROM (
                SELECT cell, var, COUNT(*) as n
                FROM cawi_atoms
                WHERE is_duplicate=0
                GROUP BY cell, var
                HAVING n >= 30
            )
        """).fetchone()[0]

    return {
        "total_responses":    total,
        "prolific":           prolific,
        "social":             social,
        "total_atom_ratings": atoms,
        "hard_flagged":       flagged,
        "variants_coverage":  f"{coverage}/100",
    }


# ── Analysis Pipeline ─────────────────────────────────────

analysis_status = {"running": False, "last_run": None, "error": None}

def _run_pipeline_bg(simulate: bool):
    global analysis_status
    analysis_status["running"] = True
    analysis_status["error"] = None
    try:
        import sys, importlib
        sys.path.insert(0, '/app')
        mod = importlib.import_module("analyze_cawi")
        out_dir = os.path.join(DATA_DIR, "analysis")
        db = None if simulate else DB_PATH
        results = mod.run_pipeline(db_path=db, out_dir=out_dir, simulate=simulate)
        analysis_status["last_run"] = results.get("generated_at")
    except Exception as e:
        import traceback
        analysis_status["error"] = traceback.format_exc()
    finally:
        analysis_status["running"] = False


@app.post("/analysis/run")
async def run_analysis(simulate: bool = False, admin=Depends(require_admin)):
    if analysis_status["running"]:
        return {"ok": False, "message": "Pipeline already running"}
    t = threading.Thread(target=_run_pipeline_bg, args=(simulate,), daemon=True)
    t.start()
    return {"ok": True, "message": "Pipeline started in background. Check /analysis/status for progress."}


@app.get("/analysis/status")
async def analysis_status_endpoint(admin=Depends(require_admin)):
    return {
        "running": analysis_status["running"],
        "last_run": analysis_status["last_run"],
        "error": analysis_status["error"],
        "report_ready": os.path.exists(os.path.join(DATA_DIR, "analysis", "sonic_atoms_report.html")),
    }


@app.get("/analysis/report")
async def analysis_report(admin=Depends(require_admin)):
    report_path = os.path.join(DATA_DIR, "analysis", "sonic_atoms_report.html")
    if not os.path.exists(report_path):
        return HTMLResponse("<h3 style='font-family:sans-serif;padding:2rem'>⚠️ Report nenájdený. Spusti /analysis/run najprv.</h3>")
    with open(report_path) as f:
        return HTMLResponse(f.read())


@app.get("/analysis/json")
async def analysis_json(admin=Depends(require_admin)):
    json_path = os.path.join(DATA_DIR, "analysis", "sonic_atoms_analysis.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="JSON nenájdený.")
    with open(json_path) as f:
        return JSONResponse(json.load(f))


@app.get("/debug")
async def debug():
    return {
        "admin_user_set": bool(ADMIN_USER),
        "admin_pass_set": bool(ADMIN_PASS),
        "db_exists": os.path.exists(DB_PATH),
    }


@app.get("/refs")
async def list_refs():
    return []
