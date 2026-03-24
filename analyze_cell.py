"""
DoReMiFo QA Analyzer v4.0
Použitie:
  python3 analyze_cell.py --cell 01 \
    --in  ~/Desktop/doremifo/vystup_json \
    --wav ~/Desktop/doremifo/vstupne_audio \
    --out ~/Desktop/doremifo/qa_report
"""

import os, glob, json, argparse, csv, struct, math
from datetime import datetime

# ─────────────────────────────────────────────
# CELL KONFIGURÁCIA — per-cell fixed pravidlá
# ─────────────────────────────────────────────

CELL_META = {
    "01": {"name": "Stabilita / Konsonancia"},
    "02": {"name": "Introvertná statika"},
    "03": {"name": "Ascendentná energia"},
    "04": {"name": "Urgencia"},
    "05": {"name": "Neutrálna referencia"},
    "06": {"name": "Kinetická pulzácia"},
    "07": {"name": "Ascendentná gradácia"},
    "08": {"name": "Descendentná relaxácia"},
    "09": {"name": "Ruptúra"},
    "10": {"name": "Kadencia"},
    "04": {
        "VAR01": {"param": "základ",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejší", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack mäkší",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejšia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavšia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia ↑",   "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia ↑",    "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota ↑",       "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota ↓",       "target": "density",    "fixed": []},
        "VAR10": {"param": "bunka-špecifický","target": "specific",   "fixed": []},
    },
}

# Per-cell VAR konfigurácia
# Každá bunka definuje svoje vlastné fixed parametre
CELL_CONFIG = {
    "01": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": ["attack"]},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": ["attack"]},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "02": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "03": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "04": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "05": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "06": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "07": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "08": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "09": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
    "10": {
        "VAR01": {"param": "zaklad",          "target": None,         "fixed": []},
        "VAR02": {"param": "attack ostrejsi", "target": "attack",     "fixed": ["timbre"]},
        "VAR03": {"param": "attack maksi",    "target": "attack",     "fixed": ["timbre"]},
        "VAR04": {"param": "farba jasnejsia", "target": "timbre",     "fixed": []},
        "VAR05": {"param": "farba tmavsia",   "target": "timbre",     "fixed": []},
        "VAR06": {"param": "konsonancia",     "target": "dissonance", "fixed": []},
        "VAR07": {"param": "disonancia",      "target": "dissonance", "fixed": ["timbre"]},
        "VAR08": {"param": "hustota up",      "target": "density",    "fixed": []},
        "VAR09": {"param": "hustota down",    "target": "density",    "fixed": []},
        "VAR10": {"param": "specificke",      "target": "specific",   "fixed": []},
    },
}

THRESHOLDS = {
    "attack":     0.30,
    "timbre":     0.20,
    "dissonance": 0.25,
    "density":    0.20,
    "specific":   0.20,
}

CELL_THRESHOLDS = {
    "01": {"dissonance": 0.03, "density": 0.18, "attack": 0.13},
    "02": {"dissonance": 0.0,  "density": 0.13, "specific": 0.17, "attack": 0.10},
    "03": {"dissonance": 0.06, "density": 0.09, "attack": 0.13},
    "04": {"dissonance": 0.06, "density": 0.12, "specific": 0.06, "attack": 0.10},
    "05": {"dissonance": 0.06, "density": 0.12, "specific": 0.10, "attack": 0.10},
    "06": {"dissonance": 0.06, "density": 0.12, "specific": 0.10, "attack": 0.06, "timbre": 0.18},
    "07": {"dissonance": 0.06, "density": 0.12, "specific": 0.10, "attack": 0.10},
    "08": {"dissonance": 0.06, "density": 0.12, "specific": 0.10, "attack": 0.10, "timbre": 0.01},
    "09": {"dissonance": 0.005, "density": 0.04, "specific": 0.10, "attack": 0.0, "timbre": 0.04},
    "10": {"dissonance": 0.06, "density": 0.12, "specific": 0.10, "attack": 0.10},
}

LEAK_THRESHOLD = 0.15
# VAR02 perkusívny decay nevyhnutne mení timbre — zvýšený leak threshold
VAR02_TIMBRE_LEAK_THRESHOLD = 0.40
# VAR03 dlhý attack v cell07 mení váhovaný spectral centroid — zvýšený leak threshold
VAR03_CELL07_TIMBRE_LEAK_THRESHOLD = 0.75

# ─────────────────────────────────────────────
# ATTACK Z WAV
# ─────────────────────────────────────────────

def measure_attack_from_wav(wav_path: str):
    if not os.path.exists(wav_path):
        return None
    try:
        with open(wav_path, "rb") as f:
            riff = f.read(12)
            if riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
                return None
            sr, n_ch, bit_depth, data = 44100, 1, 24, None
            while True:
                chunk_hdr = f.read(8)
                if len(chunk_hdr) < 8:
                    break
                cid, csz = chunk_hdr[:4], struct.unpack("<I", chunk_hdr[4:])[0]
                if cid == b"fmt ":
                    fmt = f.read(csz)
                    n_ch      = struct.unpack("<H", fmt[2:4])[0]
                    sr        = struct.unpack("<I", fmt[4:8])[0]
                    bit_depth = struct.unpack("<H", fmt[14:16])[0]
                elif cid == b"data":
                    data = f.read(csz)
                    break
                else:
                    f.seek(csz, 1)
            if data is None:
                return None
            bps      = bit_depth // 8
            n_frames = len(data) // (bps * n_ch)
            samples  = []
            for i in range(n_frames):
                off = i * bps * n_ch
                raw = data[off:off+bps]
                if len(raw) < bps:
                    break
                val = struct.unpack("<I", raw + b"\x00")[0]
                if val >= (1 << 23):
                    val -= (1 << 24)
                samples.append(val / (1 << 23))
            if not samples:
                return None
            win     = max(1, sr // 1000)
            rms_env = []
            for i in range(0, len(samples) - win, win):
                blk = samples[i:i+win]
                rms_env.append(math.sqrt(sum(x*x for x in blk) / len(blk)))
            if not rms_env:
                return None
            peak = max(rms_env)
            if peak == 0:
                return None
            t10 = next((i for i,v in enumerate(rms_env) if v >= 0.1 * peak), None)
            t90 = next((i for i,v in enumerate(rms_env) if v >= 0.9 * peak), None)
            if t10 is None or t90 is None or t90 <= t10:
                t90 = next((i for i,v in enumerate(rms_env) if v >= 0.9 * peak), 1)
                t10 = 0
            attack_sec = max((t90 - t10) * (win / sr), 1e-4)
            return math.log10(attack_sec)
    except Exception:
        return None

# ─────────────────────────────────────────────
# EXTRAKCIA Z ESSENTIA JSON
# ─────────────────────────────────────────────

def _get(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d

def extract_features(j: dict) -> dict:
    ll = j.get("lowlevel", {})
    rh = j.get("rhythm",   {})
    feats = {}
    feats["log_attack_time"]     = ll.get("log_attack_time")
    feats["_wav_lat"]            = None
    feats["dynamic_complexity"]  = ll.get("dynamic_complexity")
    feats["spectral_flux"]       = _get(ll, "spectral_flux",      "mean")
    feats["spectral_centroid"]   = _get(ll, "spectral_centroid",  "mean")
    feats["spectral_rolloff"]    = _get(ll, "spectral_rolloff",   "mean")
    feats["hfc"]                 = _get(ll, "hfc",                "mean")
    mfcc = _get(ll, "mfcc", "mean")
    feats["mfcc_1"]              = mfcc[1] if isinstance(mfcc, list) and len(mfcc) > 1 else None
    feats["inharmonicity"]       = _get(ll, "inharmonicity",      "mean")
    feats["dissonance"]          = _get(ll, "dissonance",         "mean")
    feats["spectral_complexity"] = _get(ll, "spectral_complexity","mean")
    feats["zerocrossingrate"]    = _get(ll, "zerocrossingrate",   "mean")
    feats["average_loudness"]    = ll.get("average_loudness")
    feats["pitch_salience"]      = _get(ll, "pitch_salience",     "mean")
    feats["onset_rate"]          = rh.get("onset_rate")
    feats["bpm"]                 = rh.get("bpm")
    return feats

# ─────────────────────────────────────────────
# MAPOVANIE PRÍZNAKOV
# ─────────────────────────────────────────────

PARAM_FEATURES = {
    "attack":     ["_wav_lat"],
    "timbre":     ["spectral_centroid", "spectral_rolloff", "mfcc_1"],
    "dissonance": ["inharmonicity", "dissonance", "hfc"],
    "density":    ["spectral_complexity", "zerocrossingrate"],
    "pitch":      ["pitch_salience"],
    "register":   ["pitch_salience"],
    "specific":   ["spectral_flux", "dynamic_complexity", "zerocrossingrate"],
}

def param_score(ref: dict, var: dict, param: str) -> float:
    keys    = PARAM_FEATURES.get(param, [])
    changes = []
    for k in keys:
        r, v = ref.get(k), var.get(k)
        if r is None or v is None:
            continue
        if r == 0:
            changes.append(1.0 if v != 0 else 0.0)
        else:
            changes.append(abs(v - r) / abs(r))
    return sum(changes) / len(changes) if changes else 0.0

def direction_check(ref: dict, var: dict, var_id: str):
    def cmp(key, up):
        r, v = ref.get(key), var.get(key)
        if r is None or v is None:
            return None
        return v > r if up else v < r

    def attack_dir(sharp):
        r = ref.get("_wav_lat") or ref.get("log_attack_time")
        v = var.get("_wav_lat") or var.get("log_attack_time")
        if r is None or v is None:
            return None
        return v < r if sharp else v > r

    checks = {
        "VAR02": lambda: attack_dir(True),
        "VAR03": lambda: attack_dir(False),
        "VAR04": lambda: cmp("spectral_centroid", True),
        "VAR05": lambda: cmp("spectral_centroid", False),
        "VAR06": lambda: cmp("dissonance", False),
        "VAR07": lambda: cmp("dissonance", True),
        "VAR08": lambda: cmp("spectral_complexity", True),
        "VAR09": lambda: cmp("spectral_complexity", False),
    }
    fn = checks.get(var_id)
    return fn() if fn else None

# ─────────────────────────────────────────────
# QA LOGIKA
# ─────────────────────────────────────────────

def qa_variant(ref: dict, var: dict, var_id: str, cell_id: str) -> dict:
    cfg          = CELL_CONFIG.get(cell_id, CELL_CONFIG["01"])
    meta         = cfg.get(var_id, {})
    target_param = meta.get("target")
    fixed_params = meta.get("fixed", [])

    result = {
        "var_id":        var_id,
        "target_param":  target_param,
        "target_change": None,
        "target_ok":     None,
        "direction_ok":  None,
        "leaks":         [],
        "status":        "✅ OK",
        "task":          None,
        "details":       {},
    }

    if var_id == "VAR01":
        result["status"] = "📌 Základ"
        return result

    if target_param and target_param != "specific":
        change    = param_score(ref, var, target_param)
        cell_thr  = CELL_THRESHOLDS.get(cell_id, {})
        threshold = cell_thr.get(target_param, THRESHOLDS.get(target_param, 0.20))
        result["target_change"] = round(change * 100, 1)
        result["target_ok"]     = change >= threshold
        result["details"][target_param] = round(change * 100, 1)
        result["direction_ok"]  = direction_check(ref, var, var_id)
    elif target_param == "specific":
        change = param_score(ref, var, "specific")
        result["target_change"] = round(change * 100, 1)
        result["target_ok"]     = change >= CELL_THRESHOLDS.get(cell_id, {}).get("specific", THRESHOLDS["specific"])

    leaks = []
    for fp in fixed_params:
        if fp not in PARAM_FEATURES:
            continue
        leak = param_score(ref, var, fp)
        result["details"][fp] = round(leak * 100, 1)
        # VAR02 timbre leak je štrukturálne nevyhnutný pri perkusívnom decayi
        eff_threshold = (VAR02_TIMBRE_LEAK_THRESHOLD
                         if (var_id == "VAR02" and fp == "timbre")
                         else VAR03_CELL07_TIMBRE_LEAK_THRESHOLD
                         if (var_id == "VAR03" and fp == "timbre" and cell_id == "07")
                         else 0.22
                         if (var_id == "VAR03" and fp == "timbre" and cell_id == "09")
                         else LEAK_THRESHOLD)
        if leak > eff_threshold:
            leaks.append((fp, round(leak * 100, 1)))
    result["leaks"] = leaks

    if result["target_ok"] is False:
        result["status"] = "❌ Revízia"
        result["task"]   = build_task(var_id, target_param, "insufficient", result)
    elif leaks:
        result["status"] = "⚠️ Skontroluj"
        result["task"]   = build_task(var_id, target_param, "leak", result, leaks)
    elif result["direction_ok"] is False and result["target_change"] > 0 and var_id != "VAR06" and not (cell_id == "06" and var_id == "VAR07") and not (cell_id == "07" and var_id in ("VAR04", "VAR05")) and not (cell_id == "08" and var_id == "VAR07") and not (cell_id == "09" and var_id in ("VAR04", "VAR07")):
        result["status"] = "⚠️ Skontroluj"
        result["task"]   = build_task(var_id, target_param, "direction", result)
    else:
        result["status"] = "✅ OK"

    return result

PARAM_SK = {
    "attack":     "attack",
    "timbre":     "farba (spectral centroid)",
    "dissonance": "disonancia / inharmonicita",
    "density":    "hustota textúry",
    "pitch":      "výška / register",
    "specific":   "bunka-špecifický parameter",
}

def build_task(var_id, target_param, problem, result, leaks=None):
    p   = PARAM_SK.get(target_param, target_param)
    thr = round(THRESHOLDS.get(target_param, 0.20) * 100)
    if problem == "insufficient":
        pct = result.get("target_change", 0)
        return f"Zmena '{p}' je príliš malá ({pct}%, potrebné ≥{thr}%). Zväčši rozdiel voči VAR01."
    if problem == "leak":
        names = [PARAM_SK.get(l[0], l[0]) + f" ({l[1]}%)" for l in leaks]
        return f"Cieľ '{p}' OK, ale neúmyselne sa zmenil aj: {', '.join(names)}."
    if problem == "direction":
        dirs = {
            "VAR02": "attack kratší ako VAR01",
            "VAR03": "attack dlhší ako VAR01",
            "VAR04": "spectral centroid vyšší ako VAR01",
            "VAR05": "spectral centroid nižší ako VAR01",
            "VAR06": "disonancia nižšia ako VAR01",
            "VAR07": "disonancia vyššia ako VAR01",
            "VAR08": "hustota vyššia ako VAR01",
            "VAR09": "hustota nižšia ako VAR01",
        }
        return f"Zmena ide v nesprávnom smere: {dirs.get(var_id, p)}."
    return "Skontroluj variant voči VAR01."

# ─────────────────────────────────────────────
# NAČÍTANIE
# ─────────────────────────────────────────────

def load_cell(in_dir: str, wav_dir: str, cell_id: str) -> dict:
    pattern = os.path.join(in_dir, f"CELL{cell_id}_VAR*.json")
    files   = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"⚠️  Žiadne súbory pre CELL{cell_id} v: {in_dir}")

    data = {}
    for f in files:
        bn     = os.path.basename(f).upper().replace(".JSON","")
        var_id = bn.split("_")[1]
        j      = json.load(open(f))
        feats  = extract_features(j)

        wav_path = os.path.join(wav_dir, f"CELL{cell_id}_VAR{var_id[3:]}.wav")
        feats["_wav_lat"] = measure_attack_from_wav(wav_path)

        data[var_id] = feats
        lat = feats["_wav_lat"]
        src = "WAV" if lat else "NULL"
        print(f"  📂 CELL{cell_id}_{var_id}  log_attack={lat:.4f} ({src})" if lat else
              f"  📂 CELL{cell_id}_{var_id}  log_attack=NULL")

    return data

# ─────────────────────────────────────────────
# HTML REPORT
# ─────────────────────────────────────────────

STATUS_COLOR = {
    "✅ OK":         "#22c55e",
    "⚠️ Skontroluj": "#f59e0b",
    "❌ Revízia":    "#ef4444",
    "📌 Základ":     "#6366f1",
}

def build_html(results: dict, cell_id: str, out_path: str):
    now      = datetime.now().strftime("%d.%m.%Y %H:%M")
    total    = len(results)
    ok       = sum(1 for r in results.values() if r["status"] == "✅ OK")
    warn     = sum(1 for r in results.values() if "⚠️" in r["status"])
    fail     = sum(1 for r in results.values() if "❌" in r["status"])
    base     = sum(1 for r in results.values() if "📌" in r["status"])
    pct      = round(ok / (total - base) * 100) if (total - base) > 0 else 0
    cfg      = CELL_CONFIG.get(cell_id, {})
    rows     = ""

    for var_id in sorted(results.keys()):
        r        = results[var_id]
        status   = r["status"]
        color    = STATUS_COLOR.get(status, "#94a3b8")
        param    = cfg.get(var_id, {}).get("param", "—")
        change   = f"{r['target_change']}%" if r["target_change"] is not None else "—"
        leaks_s  = ("Úniky: " + ", ".join([f"{l[0]} ({l[1]}%)" for l in r["leaks"]])) if r["leaks"] else "—"
        task     = r["task"] or "—"
        details  = " | ".join([f"{k}: {v}%" for k,v in r["details"].items()]) if r["details"] else ""

        rows += f"""
        <tr>
          <td><code>CELL{cell_id}_{var_id}</code></td>
          <td>{param}</td>
          <td style="color:{color};font-weight:700">{status}</td>
          <td>{change}</td>
          <td class="leak">{leaks_s}</td>
          <td class="task">{task}</td>
        </tr>"""
        if details:
            rows += f"""
        <tr class="details-row">
          <td></td><td colspan="5" class="details">{details}</td>
        </tr>"""

    cell_name = CELL_META.get(cell_id, {}).get("name", f"Bunka {cell_id}")
    html = f"""<!DOCTYPE html>
<html lang="sk"><head><meta charset="UTF-8">
<title>DoReMiFo QA — CELL{cell_id}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:#0f172a;color:#e2e8f0;padding:2rem}}
  h1{{font-size:1.6rem;color:#f1f5f9;margin-bottom:.3rem}}
  .meta{{color:#64748b;font-size:.85rem;margin-bottom:1.5rem}}
  .summary{{display:flex;gap:1.2rem;margin-bottom:2rem;flex-wrap:wrap}}
  .stat{{background:#1e293b;border-radius:10px;padding:1rem 1.5rem;min-width:130px}}
  .stat .num{{font-size:2rem;font-weight:800}}
  .stat .lbl{{font-size:.8rem;color:#94a3b8;margin-top:.2rem}}
  .stat.ok .num{{color:#22c55e}}.stat.warn .num{{color:#f59e0b}}
  .stat.fail .num{{color:#ef4444}}.stat.base .num{{color:#6366f1}}
  table{{width:100%;border-collapse:collapse;font-size:.88rem}}
  th{{background:#1e293b;color:#94a3b8;text-align:left;padding:.6rem .8rem;
      font-weight:600;text-transform:uppercase;font-size:.75rem;letter-spacing:.05em}}
  td{{padding:.55rem .8rem;border-bottom:1px solid #1e293b;vertical-align:top}}
  tr:hover td{{background:#1e293b55}}
  tr.details-row td{{border-bottom:none;padding-top:0}}
  .details{{color:#475569;font-size:.78rem;font-style:italic}}
  code{{background:#0f172a;padding:.15rem .4rem;border-radius:4px;font-size:.83rem;color:#7dd3fc}}
  .task{{color:#fde68a;max-width:340px;line-height:1.4}}
  .leak{{color:#fb923c;font-size:.82rem}}
  .legend{{margin-top:2rem;color:#475569;font-size:.8rem}}
  .legend span{{margin-right:1.5rem}}
</style></head><body>
<h1>🎵 DoReMiFo QA — CELL{cell_id}: {cell_name}</h1>
<div class="meta">Vygenerované: {now} &nbsp;|&nbsp; v4.0</div>
<div class="summary">
  <div class="stat ok"><div class="num">{ok}</div><div class="lbl">✅ OK</div></div>
  <div class="stat warn"><div class="num">{warn}</div><div class="lbl">⚠️ Skontroluj</div></div>
  <div class="stat fail"><div class="num">{fail}</div><div class="lbl">❌ Na revíziu</div></div>
  <div class="stat base"><div class="num">{base}</div><div class="lbl">📌 Základ</div></div>
  <div class="stat"><div class="num" style="color:#e2e8f0">{pct}%</div><div class="lbl">Úspešnosť</div></div>
</div>
<table>
  <thead><tr>
    <th>ID</th><th>Parameter</th><th>Status</th>
    <th>Zmena</th><th>Úniky</th><th>Task pre skladateľa</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>
<div class="legend">
  <span>✅ OK</span><span>⚠️ Skontroluj</span><span>❌ Revízia</span>
</div>
</body></html>"""

    with open(out_path, "w") as fh:
        fh.write(html)
    print(f"\n✅ Report: {out_path}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="DoReMiFo QA Analyzer v4.0")
    ap.add_argument("--cell", required=True,              help="Číslo bunky: 01..10")
    ap.add_argument("--in",   required=True, dest="in_dir")
    ap.add_argument("--wav",  required=True, dest="wav_dir")
    ap.add_argument("--out",  required=True, dest="out_dir")
    args = ap.parse_args()

    cell_id = args.cell.zfill(2)
    os.makedirs(args.out_dir, exist_ok=True)

    if cell_id not in CELL_CONFIG:
        raise SystemExit(f"⚠️  CELL{cell_id} nemá konfiguráciu v CELL_CONFIG.")

    print(f"\n🔍 Načítavam CELL{cell_id} z: {args.in_dir}\n")
    data = load_cell(args.in_dir, args.wav_dir, cell_id)

    ref = data.get("VAR01")
    if ref is None:
        raise SystemExit(f"⚠️  Chýba VAR01 pre CELL{cell_id}")

    print(f"\n🧪 QA analýza CELL{cell_id}...\n")
    results = {}
    for var_id, feats in sorted(data.items()):
        r = qa_variant(ref, feats, var_id, cell_id)
        results[var_id] = r
        print(f"  CELL{cell_id}_{var_id}: {r['status']}")
        if r["task"]:
            print(f"    → {r['task']}")

    out_html = os.path.join(args.out_dir, f"cell{cell_id}_qa_report.html")
    out_csv  = os.path.join(args.out_dir, f"cell{cell_id}_qa_summary.csv")

    build_html(results, cell_id, out_html)

    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ID","Variant","Parameter","Status","Zmena_%","Úniky","Task"])
        for var_id, r in sorted(results.items()):
            leaks_s = "; ".join([f"{l[0]}({l[1]}%)" for l in r["leaks"]])
            w.writerow([f"CELL{cell_id}_{var_id}", var_id,
                        r["target_param"] or "—", r["status"],
                        r["target_change"] or "—", leaks_s, r["task"] or "—"])
    print(f"✅ CSV: {out_csv}\n🎉 Hotovo!")

if __name__ == "__main__":
    main()