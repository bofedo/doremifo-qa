"""
DoReMiFo QA — FastAPI backend v1.4
- Composer tokeny + unikátne upload linky
- Progress tracking per skladateľ per bunka
- Slack notifikácia pri 100% sade
- WAV archív per skladateľ
- Admin dashboard
"""

import os, shutil, subprocess, tempfile, json, sqlite3, secrets, re
from datetime import datetime
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from typing import List

app = FastAPI(title="DoReMiFo QA")

DATA_DIR = "/app/data"
REFS_DIR = os.path.join(DATA_DIR, "references")
ARCH_DIR = os.path.join(DATA_DIR, "archive")
DB_PATH  = os.path.join(DATA_DIR, "doremifo.db")
os.makedirs(REFS_DIR, exist_ok=True)
os.makedirs(ARCH_DIR, exist_ok=True)

SLACK_WEBHOOK = "https://hooks.slack.com/services/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"
ADMIN_SECRET  = os.environ.get("ADMIN_SECRET", "doremifo-admin")

VARS_ALL = [f"VAR{i:02d}" for i in range(1, 11)]

# ── Databáza ──────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS composers (
                token TEXT PRIMARY KEY,
                name  TEXT NOT NULL,
                cell  TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                token      TEXT NOT NULL,
                var_id     TEXT NOT NULL,
                filename   TEXT,
                source     TEXT,
                uploaded_at TEXT DEFAULT (datetime('now')),
                UNIQUE(token, var_id)
            )""")

init_db()

# ── Slack ─────────────────────────────────────────────────

def slack_notify(msg: str):
    try:
        subprocess.run([
            "python3", "-c",
            f"""
import urllib.request, json
data = json.dumps({{"text": {json.dumps(msg)}}}).encode()
req = urllib.request.Request("{SLACK_WEBHOOK}",
    data=data, headers={{"Content-Type":"application/json"}})
urllib.request.urlopen(req, timeout=5)
"""
        ], timeout=8)
    except Exception:
        pass

# ── Detekcia zdroja ───────────────────────────────────────

def detect_source(json_path: str):
    try:
        with open(json_path) as f:
            j = json.load(f)
        ll = j.get("lowlevel", {})
        def mean(key):
            v = ll.get(key)
            return v.get("mean") if isinstance(v, dict) else (v or 0)
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

# ── Upload UI ─────────────────────────────────────────────

def build_upload_ui(composer_name: str, cell: str, uploaded: list, lang: str = "sk") -> str:
    progress = len(uploaded)
    pct = round(progress / 10 * 100)
    var_status = {v: (v in uploaded) for v in VARS_ALL}

    CELLS = {
        "sk": ["01 — Stabilita / Konsonancia","02 — Introvertná statika","03 — Ascendentná energia",
               "04 — Urgencia","05 — Neutrálna referencia","06 — Kinetická pulzácia",
               "07 — Ascendentná gradácia","08 — Descendentná relaxácia","09 — Ruptúra","10 — Kadencia"],
        "en": ["01 — Stability / Consonance","02 — Introverted Stasis","03 — Ascendant Energy",
               "04 — Urgency","05 — Neutral Reference","06 — Kinetic Pulsation",
               "07 — Ascendant Gradation","08 — Descendent Relaxation","09 — Rupture","10 — Cadence"]
    }
    cell_idx  = int(cell) - 1
    cell_name = CELLS[lang][cell_idx]

    chips = ""
    for v in VARS_ALL:
        done = var_status[v]
        chips += f"""<div class="chip {'done' if done else ''}">
            <div class="vnum">{v.replace('VAR','V')}</div>
            <div class="vico">{'✓' if done else '○'}</div>
        </div>"""

    t = {
        "sk": {
            "greeting": f"Ahoj, {composer_name}",
            "sub": f"Bunka {cell_name}",
            "progress": f"Nahraté: {progress} / 10",
            "drop": "Pretiahni WAV súbory sem alebo klikni",
            "hint": f"CELL{cell}_VAR01.wav … CELL{cell}_VAR10.wav",
            "btn": "Nahrať",
            "processing": "Spracovávam...",
            "done_all": "✅ Sada kompletná! Výskumný tím bol notifikovaný.",
            "done_part": "✅ Súbory nahrané.",
            "error": "Chyba",
        },
        "en": {
            "greeting": f"Hello, {composer_name}",
            "sub": f"Cell {cell_name}",
            "progress": f"Uploaded: {progress} / 10",
            "drop": "Drag WAV files here or click",
            "hint": f"CELL{cell}_VAR01.wav … CELL{cell}_VAR10.wav",
            "btn": "Upload",
            "processing": "Processing...",
            "done_all": "✅ Set complete! The research team has been notified.",
            "done_part": "✅ Files uploaded.",
            "error": "Error",
        }
    }[lang]

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DoReMiFo QA</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0f172a;color:#e2e8f0;min-height:100vh;
       display:flex;align-items:flex-start;justify-content:center;padding:2rem}}
  .card{{background:#1e293b;border-radius:16px;padding:2.5rem;width:100%;max-width:520px;position:relative}}
  .lang{{position:absolute;top:1.5rem;right:1.5rem;display:flex;border-radius:8px;overflow:hidden;border:1px solid #334155}}
  .lang button{{padding:.3rem .7rem;background:transparent;color:#64748b;border:none;
               font-size:.78rem;font-weight:600;cursor:pointer}}
  .lang button.active{{background:#6366f1;color:white}}
  h1{{font-size:1.3rem;color:#f1f5f9;margin-bottom:.2rem;padding-right:5rem}}
  .sub{{color:#64748b;font-size:.82rem;margin-bottom:1.5rem}}
  .progress-wrap{{margin-bottom:1.5rem}}
  .progress-top{{display:flex;justify-content:space-between;font-size:.8rem;
                color:#94a3b8;margin-bottom:.4rem}}
  .progress-bg{{background:#0f172a;border-radius:99px;height:8px}}
  .progress-bar{{background:#6366f1;height:8px;border-radius:99px;
                width:{pct}%;transition:width .4s}}
  .chips{{display:grid;grid-template-columns:repeat(5,1fr);gap:.4rem;margin-bottom:1.5rem}}
  .chip{{background:#0f172a;border-radius:8px;padding:.4rem;text-align:center;
         border:1px solid #1e293b}}
  .chip.done{{background:#052e16;border-color:#14532d;color:#4ade80}}
  .vnum{{font-size:.75rem;font-weight:600}}
  .vico{{font-size:.7rem;margin-top:.1rem;opacity:.8}}
  .drop{{border:2px dashed #334155;border-radius:12px;padding:1.8rem;
         text-align:center;color:#475569;font-size:.85rem;cursor:pointer;
         transition:border-color .2s,background .2s;margin-bottom:1rem}}
  .drop:hover,.drop.drag{{border-color:#6366f1;background:#1e2a4a;color:#a5b4fc}}
  .drop .icon{{font-size:1.6rem;margin-bottom:.4rem}}
  .drop .hint{{font-size:.72rem;color:#334155;margin-top:.3rem}}
  button.run{{width:100%;padding:.7rem;background:#6366f1;color:white;
              border:none;border-radius:8px;font-size:.92rem;font-weight:600;
              cursor:pointer;transition:background .2s}}
  button.run:hover:not(:disabled){{background:#4f46e5}}
  button.run:disabled{{background:#1e293b;color:#475569;cursor:not-allowed}}
  .status{{margin-top:1rem;padding:.65rem 1rem;border-radius:8px;
           font-size:.85rem;display:none}}
  .status.info{{background:#1e3a5f;color:#7dd3fc;display:block}}
  .status.ok{{background:#052e16;color:#86efac;display:block}}
  .status.err{{background:#450a0a;color:#fca5a5;display:block}}
</style>
</head>
<body>
<div class="card">
  <div class="lang">
    <button class="{'active' if lang=='sk' else ''}" onclick="reload('sk')">SK</button>
    <button class="{'active' if lang=='en' else ''}" onclick="reload('en')">EN</button>
  </div>
  <h1>🎵 {t['greeting']}</h1>
  <p class="sub">{t['sub']}</p>

  <div class="progress-wrap">
    <div class="progress-top">
      <span>{t['progress']}</span>
      <span>{pct}%</span>
    </div>
    <div class="progress-bg"><div class="progress-bar" id="pbar"></div></div>
  </div>

  <div class="chips">{chips}</div>

  <div class="drop" id="drop"
    ondragover="ev(event,true)" ondragleave="ev(event,false)" ondrop="onDrop(event)"
    onclick="document.getElementById('fi').click()">
    <div class="icon">🎵</div>
    <div>{t['drop']}</div>
    <div class="hint">{t['hint']}</div>
    <input type="file" id="fi" accept=".wav" multiple style="display:none" onchange="onFiles(this.files)">
  </div>

  <button class="run" id="btn" disabled onclick="upload()">{t['btn']}</button>
  <div class="status" id="status"></div>
</div>

<script>
const T = {{
  processing: "{t['processing']}",
  done_all:   "{t['done_all']}",
  done_part:  "{t['done_part']}",
  error:      "{t['error']}",
}};
let files = {{}};

function reload(l) {{ window.location.href = window.location.pathname + '?lang=' + l; }}
function ev(e, on) {{ e.preventDefault(); document.getElementById('drop').classList.toggle('drag', on); }}
function onDrop(e) {{ e.preventDefault(); document.getElementById('drop').classList.remove('drag'); onFiles(e.dataTransfer.files); }}

function onFiles(f) {{
  files = {{}};
  Array.from(f).forEach(file => {{
    const m = file.name.toUpperCase().match(/(VAR\d+)/);
    if (m) files[m[1]] = file;
  }});
  document.getElementById('btn').disabled = Object.keys(files).length === 0;
}}

async function upload() {{
  const btn = document.getElementById('btn');
  const st  = document.getElementById('status');
  btn.disabled = true;
  st.className = 'status info';
  st.textContent = T.processing;

  const fd = new FormData();
  Object.values(files).forEach(f => fd.append('wavs', f));

  try {{
    const res = await fetch(window.location.pathname + '/upload', {{method:'POST', body:fd}});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Error');
    st.className = 'status ok';
    st.textContent = data.complete ? T.done_all : T.done_part;
    setTimeout(() => window.location.reload(), 2000);
  }} catch(e) {{
    st.className = 'status err';
    st.textContent = T.error + ': ' + e.message;
    btn.disabled = false;
  }}
}}
</script>
</body>
</html>"""

# ── Admin UI ──────────────────────────────────────────────

def build_admin_ui(composers: list) -> str:
    rows = ""
    for c in composers:
        pct = round(c["count"] / 10 * 100)
        bar_color = "#22c55e" if pct == 100 else "#6366f1"
        rows += f"""<tr>
          <td><strong>{c['name']}</strong></td>
          <td>CELL{c['cell']}</td>
          <td>
            <div style="display:flex;align-items:center;gap:.6rem">
              <div style="flex:1;background:#0f172a;border-radius:99px;height:6px">
                <div style="width:{pct}%;background:{bar_color};height:6px;border-radius:99px"></div>
              </div>
              <span style="font-size:.8rem;color:#94a3b8;white-space:nowrap">{c['count']}/10</span>
            </div>
          </td>
          <td><code style="font-size:.75rem;color:#7dd3fc">/upload/{c['token']}</code></td>
          <td style="font-size:.78rem;color:#64748b">{c['created_at'][:10]}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="sk"><head><meta charset="UTF-8">
<title>DoReMiFo Admin</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem}}
  h1{{font-size:1.4rem;color:#f1f5f9;margin-bottom:.3rem}}
  .meta{{color:#64748b;font-size:.82rem;margin-bottom:2rem}}
  .new-form{{background:#1e293b;border-radius:12px;padding:1.5rem;margin-bottom:2rem;display:flex;gap:.8rem;flex-wrap:wrap;align-items:flex-end}}
  .new-form label{{font-size:.8rem;color:#94a3b8;display:block;margin-bottom:.3rem}}
  .new-form input,.new-form select{{padding:.55rem .8rem;background:#0f172a;color:#e2e8f0;
    border:1px solid #334155;border-radius:8px;font-size:.9rem}}
  .new-form button{{padding:.55rem 1.2rem;background:#6366f1;color:white;border:none;
    border-radius:8px;font-size:.9rem;font-weight:600;cursor:pointer}}
  .new-form button:hover{{background:#4f46e5}}
  .result{{background:#052e16;color:#86efac;padding:.65rem 1rem;border-radius:8px;
           font-size:.82rem;margin-bottom:1.5rem;display:none;word-break:break-all}}
  table{{width:100%;border-collapse:collapse;font-size:.88rem}}
  th{{background:#1e293b;color:#94a3b8;text-align:left;padding:.6rem .8rem;
      font-size:.75rem;text-transform:uppercase;letter-spacing:.05em}}
  td{{padding:.6rem .8rem;border-bottom:1px solid #1e293b;vertical-align:middle}}
  tr:hover td{{background:#1e293b55}}
</style></head><body>
<h1>🎵 DoReMiFo Admin</h1>
<div class="meta">Správa skladateľov a upload linkov</div>

<div class="new-form">
  <div>
    <label>Meno skladateľa</label>
    <input type="text" id="nm" placeholder="Jan Novak">
  </div>
  <div>
    <label>Bunka</label>
    <select id="cl">
      {''.join(f'<option value="{i:02d}">{i:02d}</option>' for i in range(1,11))}
    </select>
  </div>
  <button onclick="newComposer()">Vygenerovať link</button>
</div>
<div class="result" id="result"></div>

<table>
  <thead><tr>
    <th>Skladateľ</th><th>Bunka</th><th>Progress</th><th>Link</th><th>Vytvorený</th>
  </tr></thead>
  <tbody>{rows if rows else '<tr><td colspan="5" style="color:#475569;text-align:center;padding:2rem">Zatiaľ žiadni skladatelia</td></tr>'}</tbody>
</table>

<script>
async function newComposer() {{
  const name = document.getElementById('nm').value.trim();
  const cell = document.getElementById('cl').value;
  if (!name) return;
  const res  = await fetch('/admin/new-composer', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{name, cell}})
  }});
  const data = await res.json();
  const el   = document.getElementById('result');
  el.style.display = 'block';
  el.textContent = '✅ Link: ' + window.location.origin + '/upload/' + data.token;
  setTimeout(() => window.location.reload(), 3000);
}}
</script>
</body></html>"""


# ── Routes ────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_ui(secret: str = ""):
    if secret != ADMIN_SECRET:
        return HTMLResponse("<h3 style='font-family:sans-serif;padding:2rem'>🔒 Prístup zamietnutý</h3>", status_code=403)
    with get_db() as db:
        rows = db.execute("""
            SELECT c.token, c.name, c.cell, c.created_at,
                   COUNT(u.id) as count
            FROM composers c
            LEFT JOIN uploads u ON u.token = c.token
            GROUP BY c.token ORDER BY c.created_at DESC
        """).fetchall()
    return build_admin_ui([dict(r) for r in rows])


@app.post("/admin/new-composer")
async def new_composer(req: Request):
    body  = await req.json()
    name  = body.get("name", "").strip()
    cell  = body.get("cell", "01")
    if not name:
        return JSONResponse(status_code=400, content={"error": "Chýba meno"})
    token = secrets.token_urlsafe(16)
    with get_db() as db:
        db.execute("INSERT INTO composers (token, name, cell) VALUES (?,?,?)", (token, name, cell))
    return {"token": token}


@app.get("/upload/{token}", response_class=HTMLResponse)
async def upload_ui(token: str, lang: str = "sk"):
    with get_db() as db:
        c = db.execute("SELECT * FROM composers WHERE token=?", (token,)).fetchone()
        if not c:
            return HTMLResponse("<h3 style='font-family:sans-serif;padding:2rem'>🔒 Neplatný link</h3>", status_code=404)
        uploaded = [r["var_id"] for r in db.execute(
            "SELECT var_id FROM uploads WHERE token=?", (token,)).fetchall()]
    return build_upload_ui(c["name"], c["cell"], uploaded, lang)


@app.post("/upload/{token}/upload")
async def do_upload(token: str, wavs: List[UploadFile] = File(...)):
    with get_db() as db:
        c = db.execute("SELECT * FROM composers WHERE token=?", (token,)).fetchone()
        if not c:
            return JSONResponse(status_code=404, content={"error": "Neplatný token"})

    cell = c["cell"]
    name = c["name"]
    composer_dir = os.path.join(ARCH_DIR, token)
    os.makedirs(composer_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        wav_dir  = os.path.join(tmp, "wav")
        json_dir = os.path.join(tmp, "json")
        os.makedirs(wav_dir); os.makedirs(json_dir)

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

            # Normalizácia
            norm = wav_path.replace(".wav", "_norm.wav")
            try:
                subprocess.run(["sox", wav_path, "-r", "44100", "-c", "1", "-b", "24", norm],
                               check=True, capture_output=True)
                os.replace(norm, wav_path)
            except Exception:
                pass

            # Essentia
            json_path = os.path.join(json_dir, f"CELL{cell}_{var_id}.json")
            subprocess.run(["essentia_streaming_extractor_music", wav_path, json_path],
                           capture_output=True)

            # Archív
            shutil.copy(wav_path, os.path.join(composer_dir, wav_name))

            # VAR01 → referencia
            if var_id == "VAR01":
                shutil.copy(wav_path,  os.path.join(REFS_DIR, f"CELL{cell}_VAR01_{token}.wav"))
                if os.path.exists(json_path):
                    shutil.copy(json_path, os.path.join(REFS_DIR, f"CELL{cell}_VAR01_{token}.json"))

            source_sk = "Neznámy"
            if os.path.exists(json_path):
                source_sk, _, _ = detect_source(json_path)

            with get_db() as db:
                db.execute("""INSERT OR REPLACE INTO uploads
                    (token, var_id, filename, source) VALUES (?,?,?,?)""",
                    (token, var_id, wav_name, source_sk))

            uploaded_now.append(var_id)

    # Skontroluj kompletnosť
    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) as n FROM uploads WHERE token=?", (token,)).fetchone()["n"]

    complete = total >= 10
    if complete:
        slack_notify(
            f"🎵 *DoReMiFo QA* — sada kompletná!\n"
            f"*Skladateľ:* {name}\n"
            f"*Bunka:* CELL{cell}\n"
            f"*Varianty:* 10/10 ✅\n"
            f"*Archív:* /data/archive/{token}/"
        )

    return {"ok": True, "complete": complete, "uploaded": uploaded_now, "total": total}


# ── Pôvodný verejný endpoint (bez tokenu) ─────────────────

@app.get("/refs")
async def list_refs():
    saved = []
    for cell in [f"{i:02d}" for i in range(1, 11)]:
        if os.path.exists(os.path.join(REFS_DIR, f"CELL{cell}_VAR01.wav")):
            saved.append(cell)
    return saved