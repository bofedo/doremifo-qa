"""
DoReMiFo QA — FastAPI backend
Endpoint: POST /qa
  - wav:    WAV súbor
  - cell:   číslo bunky (01–10)
  - source: typ zdroja (subtractive / fm / acoustic / sample)
Vráti: HTML report
"""

import os, shutil, subprocess, tempfile
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="DoReMiFo QA")

# ── Jednoduchá upload stránka ─────────────────────────────
HTML_UI = """<!DOCTYPE html>
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
    display: flex; align-items: center; justify-content: center;
    padding: 2rem;
  }
  .card {
    background: #1e293b;
    border-radius: 16px;
    padding: 2.5rem;
    width: 100%; max-width: 480px;
  }
  h1 { font-size: 1.5rem; color: #f1f5f9; margin-bottom: .3rem; }
  .sub { color: #64748b; font-size: .85rem; margin-bottom: 2rem; }
  label { display: block; font-size: .85rem; color: #94a3b8; margin-bottom: .4rem; }
  select, input[type=file] {
    width: 100%; padding: .65rem .9rem;
    background: #0f172a; color: #e2e8f0;
    border: 1px solid #334155; border-radius: 8px;
    font-size: .95rem; margin-bottom: 1.2rem;
  }
  button {
    width: 100%; padding: .75rem;
    background: #6366f1; color: white;
    border: none; border-radius: 8px;
    font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background .2s;
  }
  button:hover { background: #4f46e5; }
  button:disabled { background: #334155; cursor: not-allowed; }
  .status {
    margin-top: 1.2rem; padding: .75rem 1rem;
    border-radius: 8px; font-size: .9rem;
    display: none;
  }
  .status.loading { background: #1e3a5f; color: #7dd3fc; display: block; }
  .status.error   { background: #450a0a; color: #fca5a5; display: block; }
</style>
</head>
<body>
<div class="card">
  <h1>🎵 DoReMiFo QA</h1>
  <p class="sub">Nahraj WAV súbor a získaj QA report</p>

  <form id="form">
    <label>WAV súbor</label>
    <input type="file" id="wav" accept=".wav" required>

    <label>Bunka</label>
    <select id="cell">
      <option value="01">01 — Stabilita / Konsonancia</option>
      <option value="02">02 — Introvertná statika</option>
      <option value="03">03 — Ascendentná energia</option>
      <option value="04">04 — Urgencia</option>
      <option value="05">05 — Neutrálna referencia</option>
      <option value="06">06 — Kinetická pulzácia</option>
      <option value="07">07 — Ascendentná gradácia</option>
      <option value="08">08 — Descendentná relaxácia</option>
      <option value="09">09 — Ruptúra</option>
      <option value="10">10 — Kadencia</option>
    </select>

    <label>Variant</label>
    <select id="variant">
      <option value="VAR01">VAR01 — Základ</option>
      <option value="VAR02">VAR02 — Attack ostrejší</option>
      <option value="VAR03">VAR03 — Attack mäkší</option>
      <option value="VAR04">VAR04 — Farba jasnejšia</option>
      <option value="VAR05">VAR05 — Farba tmavšia</option>
      <option value="VAR06">VAR06 — Konsonancia MAX</option>
      <option value="VAR07">VAR07 — Disonancia ↑</option>
      <option value="VAR08">VAR08 — Hustota ↑</option>
      <option value="VAR09">VAR09 — Hustota ↓</option>
      <option value="VAR10">VAR10 — Špecifický</option>
    </select>

    <label>Typ zdroja</label>
    <select id="source">
      <option value="subtractive">Subtraktívna syntéza</option>
      <option value="fm">FM syntéza</option>
      <option value="acoustic">Akustická nahrávka</option>
      <option value="sample">Sample</option>
    </select>

    <button type="submit" id="btn">Spustiť QA</button>
  </form>

  <div class="status" id="status"></div>
</div>

<script>
document.getElementById('form').onsubmit = async e => {
  e.preventDefault();
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');
  const wav = document.getElementById('wav').files[0];
  if (!wav) return;

  btn.disabled = true;
  status.className = 'status loading';
  status.textContent = '⏳ Spracovávam... (môže trvať 30–60 sekúnd)';

  const fd = new FormData();
  fd.append('wav', wav);
  fd.append('cell', document.getElementById('cell').value);
  fd.append('variant', document.getElementById('variant').value);
  fd.append('source', document.getElementById('source').value);

  try {
    const res = await fetch('/qa', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    const html = await res.text();
    const w = window.open('', '_blank');
    w.document.write(html);
    w.document.close();
    status.style.display = 'none';
  } catch(err) {
    status.className = 'status error';
    status.textContent = '❌ Chyba: ' + err.message;
  } finally {
    btn.disabled = false;
  }
};
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def ui():
    return HTML_UI


@app.post("/qa", response_class=HTMLResponse)
async def run_qa(
    wav:     UploadFile = File(...),
    cell:    str        = Form(...),
    variant: str        = Form(...),
    source:  str        = Form("subtractive"),
):
    with tempfile.TemporaryDirectory() as tmp:
        wav_dir  = os.path.join(tmp, "wav")
        json_dir = os.path.join(tmp, "json")
        out_dir  = os.path.join(tmp, "out")
        os.makedirs(wav_dir);  os.makedirs(json_dir);  os.makedirs(out_dir)

        # Ulož WAV s DoReMiFo názvom
        wav_name = f"CELL{cell}_{variant}.wav"
        wav_path = os.path.join(wav_dir, wav_name)
        with open(wav_path, "wb") as f:
            shutil.copyfileobj(wav.file, f)

        # Normalizácia cez sox (stereo→mono, resample→44100)
        norm_path = wav_path.replace(".wav", "_norm.wav")
        subprocess.run([
            "sox", wav_path, "-r", "44100", "-c", "1", "-b", "24", norm_path
        ], check=True)
        os.replace(norm_path, wav_path)

        # Essentia extrakcia
        json_path = os.path.join(json_dir, f"CELL{cell}_{variant}.json")
        result = subprocess.run([
            "essentia_streaming_extractor_music",
            wav_path, json_path
        ], capture_output=True)

        if result.returncode != 0 or not os.path.exists(json_path):
            return JSONResponse(
                status_code=500,
                content={"error": "Essentia extrakcia zlyhala", "detail": result.stderr.decode()}
            )

        # QA analýza
        subprocess.run([
            "python3", "/app/analyze_cell.py",
            "--cell", cell,
            "--in",   json_dir,
            "--wav",  wav_dir,
            "--out",  out_dir,
        ], check=True)

        # Vráť HTML report
        report = os.path.join(out_dir, f"cell{cell}_qa_report.html")
        if not os.path.exists(report):
            return JSONResponse(status_code=500, content={"error": "Report nebol vygenerovaný"})

        with open(report) as f:
            return HTMLResponse(content=f.read())