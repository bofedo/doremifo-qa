"""
Sonic Atoms — CAWI Analytický Pipeline v1.0
Spustenie: python3 analyze_cawi.py --db /app/data/doremifo.db --out /app/data/analysis
Alebo cez Railway endpoint: POST /analysis/run
"""

import os, json, sqlite3, argparse
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.decomposition import FactorAnalysis
from sklearn.manifold import MDS
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import LeaveOneGroupOut
from scipy import stats
from scipy.spatial.distance import pdist, squareform

try:
    import pingouin as pg
    HAS_PINGOUIN = True
except ImportError:
    HAS_PINGOUIN = False

try:
    import statsmodels.formula.api as smf
    import statsmodels.api as sm
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

# ─────────────────────────────────────────────
# 1. DATA LOADING & QUALITY FILTERING
# ─────────────────────────────────────────────

PRIMARY_SCALES = ['valence', 'arousal', 'trustworthiness', 'action_urge', 'distinctiveness']
SEM_DIFF_KEYS  = ['soft_hard', 'dark_bright', 'smooth_rough', 'simple_complex']

def load_data(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT
            r.prolific_pid, r.source, r.sensitivity,
            r.headphone_flag, r.attention_flag, r.hard_flag,
            r.completed_at,
            a.atom_index, a.cell, a.var, a.is_duplicate,
            a.valence, a.arousal, a.trustworthiness,
            a.action_urge, a.distinctiveness,
            a.attribute, a.confidence, a.ux_affordance,
            a.sem_diff
        FROM cawi_atoms a
        JOIN cawi_responses r ON r.id = a.response_id
    """, conn)
    conn.close()

    # Parse sem_diff JSON
    def parse_sem(s):
        try: return json.loads(s) if s else {}
        except: return {}
    sem_parsed = df['sem_diff'].apply(parse_sem)
    for k in SEM_DIFF_KEYS:
        df[k] = sem_parsed.apply(lambda d: d.get(k))

    df['cell_var'] = df['cell'].astype(str) + '_' + df['var'].astype(str)
    return df


def simulate_data(n_respondents: int = 150) -> pd.DataFrame:
    """Generuje simulované dáta pre testovanie pipeline."""
    np.random.seed(42)
    cells = [f"{i:02d}" for i in range(1, 11)]
    varss = [f"{i:02d}" for i in range(1, 11)]
    rows = []
    for pid in range(n_respondents):
        picked_cells = np.random.choice(cells, 3, replace=False)
        for idx, cell in enumerate(picked_cells):
            var = np.random.choice(varss)
            # Simuluj korelácie: cell 09 (Ruptúra) → vysoký arousal, nízka valence
            base_valence  = 5 - (2 if cell == '09' else 0) + np.random.normal(0, 1.5)
            base_arousal  = 4 + (3 if cell == '09' else 0) + np.random.normal(0, 1.5)
            base_trust    = 4 + (1 if cell in ['01','05'] else -1 if cell=='09' else 0) + np.random.normal(0, 1)
            base_action   = 4 + (2 if cell in ['03','04'] else -1 if cell=='09' else 0) + np.random.normal(0, 1)
            base_distinct = 3 + np.random.normal(0, 1.5)
            soft_hard     = 4 + (2 if var in ['02','03'] else 0) + np.random.normal(0, 1)
            dark_bright   = 4 + (2 if var in ['04'] else -1 if var=='05' else 0) + np.random.normal(0, 1)
            sensitivity   = np.random.randint(1, 11)
            rows.append({
                'prolific_pid': f'SIM_{pid:04d}', 'source': 'prolific',
                'sensitivity': sensitivity, 'headphone_flag': 0,
                'attention_flag': int(np.random.random() < 0.05),
                'hard_flag': int(np.random.random() < 0.03),
                'completed_at': datetime.now().isoformat(),
                'atom_index': idx, 'cell': cell, 'var': var,
                'is_duplicate': 0,
                'valence':         int(np.clip(round(base_valence), 1, 9)),
                'arousal':         int(np.clip(round(base_arousal), 1, 9)),
                'trustworthiness': int(np.clip(round(base_trust), 1, 7)),
                'action_urge':     int(np.clip(round(base_action), 1, 7)),
                'distinctiveness': int(np.clip(round(base_distinct), 1, 7)),
                'attribute': np.random.choice(['premium','trustworthy','dynamic','fresh','generic','functional','cheap','irritating']),
                'confidence': np.random.randint(1, 6),
                'ux_affordance': np.random.choice(['Success','Error','Warning','Message','Loading']),
                'soft_hard':       float(np.clip(round(soft_hard), 1, 7)),
                'dark_bright':     float(np.clip(round(dark_bright), 1, 7)),
                'smooth_rough':    float(np.clip(np.random.normal(4, 1.5), 1, 7)),
                'simple_complex':  float(np.clip(np.random.normal(4, 1.5), 1, 7)),
                'cell_var': f'{cell}_{var}',
                'headphones': np.random.choice(['over_ear','in_ear_wired','in_ear_wireless']),
                'music_training': np.random.choice(['none','amateur','some_formal','advanced']),
            })
        # Duplikát
        dup_cell = picked_cells[0]
        dup_var  = rows[-3]['var']
        base_v2  = rows[-3]['valence'] + np.random.normal(0, 0.8)
        base_a2  = rows[-3]['arousal'] + np.random.normal(0, 0.8)
        rows.append({**rows[-3], 'is_duplicate': 1, 'atom_index': 3,
                     'valence': int(np.clip(round(base_v2), 1, 9)),
                     'arousal': int(np.clip(round(base_a2), 1, 9))})
    return pd.DataFrame(rows)


def filter_quality(df: pd.DataFrame) -> tuple:
    n_raw = len(df['prolific_pid'].unique())
    # Vylúč hard flags
    excluded_pids = set(df[df['hard_flag']==1]['prolific_pid'].unique())
    df_clean = df[~df['prolific_pid'].isin(excluded_pids)].copy()
    # Vylúč duplikáty z hlavnej analýzy (ponechaj pre ICC)
    df_main = df_clean[df_clean['is_duplicate']==0].copy()
    n_clean = len(df_main['prolific_pid'].unique())
    print(f"  Raw respondents: {n_raw}")
    print(f"  After quality filter: {n_clean} (excluded {n_raw-n_clean})")
    print(f"  Attention flags (kovariát): {df_main['attention_flag'].sum()}")
    return df_main, df_clean, {'n_raw': n_raw, 'n_clean': n_clean, 'n_excluded': n_raw-n_clean}


# ─────────────────────────────────────────────
# 2. DESKRIPTÍVNA ŠTATISTIKA
# ─────────────────────────────────────────────

def descriptive_stats(df: pd.DataFrame) -> dict:
    stats_out = {}
    # Per-cell means
    cell_means = df.groupby('cell')[PRIMARY_SCALES].mean().round(3)
    cell_std   = df.groupby('cell')[PRIMARY_SCALES].std().round(3)
    stats_out['cell_means'] = cell_means.to_dict()
    stats_out['cell_std']   = cell_std.to_dict()
    # Coverage
    coverage = df.groupby('cell_var').size()
    stats_out['coverage_min'] = int(coverage.min())
    stats_out['coverage_max'] = int(coverage.max())
    stats_out['coverage_mean'] = round(float(coverage.mean()), 1)
    stats_out['variants_ge30'] = int((coverage >= 30).sum())
    # Source breakdown
    stats_out['source_counts'] = df.groupby('source')['prolific_pid'].nunique().to_dict()
    print(f"  Coverage: {stats_out['coverage_mean']} ratings/variant (min {stats_out['coverage_min']}, max {stats_out['coverage_max']})")
    print(f"  Variants ≥30 ratings: {stats_out['variants_ge30']}/100")
    return stats_out


# ─────────────────────────────────────────────
# 3. ICC — RELIABILITA DUPLIKÁTOV
# ─────────────────────────────────────────────

def icc_reliability(df_full: pd.DataFrame) -> dict:
    results = {}
    dups = df_full[df_full['is_duplicate']==1].copy()
    origs = df_full[df_full['is_duplicate']==0].copy()

    for scale in PRIMARY_SCALES:
        merged = dups[['prolific_pid', scale]].merge(
            origs[['prolific_pid', scale]], on='prolific_pid', suffixes=('_dup','_orig')
        )
        if len(merged) < 5:
            results[scale] = {'icc': None, 'n': len(merged)}
            continue
        if HAS_PINGOUIN:
            long = pd.DataFrame({
                'pid': list(merged['prolific_pid'])*2,
                'rater': ['orig']*len(merged) + ['dup']*len(merged),
                'score': list(merged[f'{scale}_orig']) + list(merged[f'{scale}_dup'])
            })
            try:
                icc_res = pg.intraclass_corr(data=long, targets='pid', raters='rater', ratings='score')
                icc2 = icc_res[icc_res['Type']=='ICC2']['ICC'].values[0]
                results[scale] = {'icc': round(float(icc2), 3), 'n': len(merged)}
            except:
                r, _ = stats.pearsonr(merged[f'{scale}_orig'], merged[f'{scale}_dup'])
                results[scale] = {'icc': round(float(r), 3), 'n': len(merged), 'method': 'pearsonr'}
        else:
            r, _ = stats.pearsonr(merged[f'{scale}_orig'], merged[f'{scale}_dup'])
            results[scale] = {'icc': round(float(r), 3), 'n': len(merged), 'method': 'pearsonr'}
        print(f"  ICC {scale}: {results[scale]['icc']} (n={results[scale]['n']})")
    return results


# ─────────────────────────────────────────────
# 4. FAKTOROVÁ ANALÝZA
# ─────────────────────────────────────────────

def factor_analysis(df: pd.DataFrame) -> dict:
    scales = PRIMARY_SCALES + [k for k in SEM_DIFF_KEYS if df[k].notna().sum() > 50]
    fa_df  = df[scales].dropna()
    if len(fa_df) < 30:
        return {'error': 'Insufficient data for FA'}

    scaler = StandardScaler()
    X = scaler.fit_transform(fa_df)

    results = {}
    for n_factors in [2, 3, 4]:
        fa = FactorAnalysis(n_components=n_factors, random_state=42)
        fa.fit(X)
        loadings = pd.DataFrame(fa.components_.T, index=scales,
                                columns=[f'F{i+1}' for i in range(n_factors)])
        # Variance explained (approximate)
        var_exp = np.var(fa.transform(X), axis=0)
        var_pct = (var_exp / var_exp.sum() * 100).round(1)
        results[f'fa_{n_factors}'] = {
            'loadings': loadings.round(3).to_dict(),
            'variance_explained_pct': var_pct.tolist(),
        }
        print(f"  FA {n_factors} factors — variance explained: {var_pct.tolist()}")

    # Odporúčaný model (3 faktory: Affect, Behaviour, Timbre)
    results['recommended'] = 'fa_3'
    return results


# ─────────────────────────────────────────────
# 5. MULTIDIMENZIONÁLNA ŠKÁLA (MDS)
# ─────────────────────────────────────────────

def mds_analysis(df: pd.DataFrame) -> dict:
    # Agreguj na úrovni cell_var
    agg = df.groupby('cell_var')[PRIMARY_SCALES].mean()
    if len(agg) < 5:
        return {'error': 'Insufficient variants for MDS'}

    scaler = StandardScaler()
    X = scaler.fit_transform(agg)

    # Euklidovská dissimilarity matica
    dist_matrix = squareform(pdist(X, metric='euclidean'))

    # MDS 2D
    mds2 = MDS(n_components=2, dissimilarity='precomputed', random_state=42)
    coords2 = mds2.fit_transform(dist_matrix)

    # MDS 3D
    mds3 = MDS(n_components=3, dissimilarity='precomputed', random_state=42)
    coords3 = mds3.fit_transform(dist_matrix)

    results = {
        'variants': list(agg.index),
        'mds_2d': coords2.round(4).tolist(),
        'mds_3d': coords3.round(4).tolist(),
        'stress_2d': round(float(mds2.stress_), 4),
        'stress_3d': round(float(mds3.stress_), 4),
        'dist_matrix': dist_matrix.round(4).tolist(),
    }
    print(f"  MDS stress 2D: {results['stress_2d']}, 3D: {results['stress_3d']}")
    return results


# ─────────────────────────────────────────────
# 6. REGRESNÝ MODEL H1–H3, H8–H9
# ─────────────────────────────────────────────

def regression_models(df: pd.DataFrame) -> dict:
    """
    H1–H3: Fyzikálne parametre → percepčné škály
    Proxy: VAR číslo ako akustický parameter (reálne Essentia features sa pridajú po zbere)
    H8: Pitch contour (VAR07–09 = hustota proxy) → Arousal + Action Urge
    H9: Model stabilita pri leave-one-cell-out
    """
    results = {}
    df = df.copy()
    df['var_num'] = pd.to_numeric(df['var'], errors='coerce')

    # Dummy kódovanie bunky
    cell_dummies = pd.get_dummies(df['cell'], prefix='cell', drop_first=True)
    df = pd.concat([df, cell_dummies], axis=1)
    cell_cols = [c for c in df.columns if c.startswith('cell_')]

    # H1–H3: var_num → sémantické diferenciály + Valence + Arousal
    targets_h1h3 = {
        'dark_bright': 'Timbre contour → Bright/Dark (H1)',
        'soft_hard':   'Attack → Soft/Hard (H2)',
        'smooth_rough':'Dissonance → Smooth/Rough (H3)',
        'simple_complex': 'Density → Simple/Complex (H3)',
    }

    h1h3_results = {}
    for target, label in targets_h1h3.items():
        sub = df[['var_num', 'sensitivity', target] + cell_cols].dropna()
        if len(sub) < 20:
            continue
        X = sub[['var_num', 'sensitivity'] + cell_cols]
        y = sub[target]
        X_c = sm.add_constant(X) if HAS_STATSMODELS else X
        if HAS_STATSMODELS:
            try:
                model = sm.OLS(y, X_c).fit()
                h1h3_results[target] = {
                    'label': label, 'r2': round(float(model.rsquared), 3),
                    'r2_adj': round(float(model.rsquared_adj), 3),
                    'f_pvalue': round(float(model.f_pvalue), 4),
                    'coef_var_num': round(float(model.params.get('var_num', 0)), 4),
                    'pval_var_num': round(float(model.pvalues.get('var_num', 1)), 4),
                    'n': len(sub),
                }
                print(f"  {label}: R²={h1h3_results[target]['r2']}, p(var_num)={h1h3_results[target]['pval_var_num']}")
            except Exception as e:
                h1h3_results[target] = {'error': str(e)}
        else:
            reg = LinearRegression().fit(X, y)
            h1h3_results[target] = {'label': label, 'r2': round(float(reg.score(X, y)), 3), 'n': len(sub)}

    results['h1h3'] = h1h3_results

    # H8: pitch contour proxy → Arousal + Action Urge
    h8_results = {}
    for target in ['arousal', 'action_urge']:
        sub = df[['var_num', 'sensitivity', target] + cell_cols].dropna()
        if len(sub) < 20:
            continue
        X = sub[['var_num', 'sensitivity'] + cell_cols]
        y = sub[target]
        if HAS_STATSMODELS:
            try:
                model = sm.OLS(y, sm.add_constant(X)).fit()
                h8_results[target] = {
                    'r2': round(float(model.rsquared), 3),
                    'coef_var_num': round(float(model.params.get('var_num', 0)), 4),
                    'pval_var_num': round(float(model.pvalues.get('var_num', 1)), 4),
                    'n': len(sub),
                }
            except Exception as e:
                h8_results[target] = {'error': str(e)}
        else:
            reg = LinearRegression().fit(X, y)
            h8_results[target] = {'r2': round(float(reg.score(X, y)), 3), 'n': len(sub)}
    results['h8'] = h8_results

    # H9: Leave-one-cell-out cross-validácia
    logo = LeaveOneGroupOut()
    groups = df['cell'].values
    r2_scores = []
    for target in ['valence', 'arousal']:
        sub = df[['var_num', 'sensitivity', target, 'cell']].dropna()
        if len(sub) < 30:
            continue
        X = sub[['var_num', 'sensitivity']].values
        y = sub[target].values
        g = sub['cell'].values
        fold_r2 = []
        for train_idx, test_idx in logo.split(X, y, g):
            reg = LinearRegression().fit(X[train_idx], y[train_idx])
            pred = reg.predict(X[test_idx])
            ss_res = np.sum((y[test_idx]-pred)**2)
            ss_tot = np.sum((y[test_idx]-np.mean(y[test_idx]))**2)
            fold_r2.append(1 - ss_res/ss_tot if ss_tot > 0 else 0)
        r2_scores.append({'target': target, 'mean_r2': round(float(np.mean(fold_r2)), 3), 'std_r2': round(float(np.std(fold_r2)), 3)})
        print(f"  H9 LOCO {target}: mean R²={round(np.mean(fold_r2),3)} ± {round(np.std(fold_r2),3)}")
    results['h9_loco'] = r2_scores
    return results


# ─────────────────────────────────────────────
# 7. MODERAČNÁ ANALÝZA H11–H12
# ─────────────────────────────────────────────

def moderation_analysis(df: pd.DataFrame) -> dict:
    """
    H11: Sensitivity moderuje vzťah dissonance → Valence
    H12: Headphone type moderuje effect sizes X→Y
    """
    results = {}

    # H11: Sensitivity × dissonance proxy (smooth_rough) → Valence
    sub = df[['smooth_rough', 'sensitivity', 'valence']].dropna()
    if len(sub) >= 30 and HAS_STATSMODELS:
        sub = sub.copy()
        # Centrovanie
        sub['smooth_rough_c'] = sub['smooth_rough'] - sub['smooth_rough'].mean()
        sub['sensitivity_c']  = sub['sensitivity']  - sub['sensitivity'].mean()
        sub['interaction']    = sub['smooth_rough_c'] * sub['sensitivity_c']
        try:
            model = sm.OLS(sub['valence'], sm.add_constant(sub[['smooth_rough_c','sensitivity_c','interaction']])).fit()
            results['h11'] = {
                'coef_interaction': round(float(model.params.get('interaction', 0)), 4),
                'pval_interaction': round(float(model.pvalues.get('interaction', 1)), 4),
                'r2': round(float(model.rsquared), 3),
                'n': len(sub),
                'significant': model.pvalues.get('interaction', 1) < 0.05,
            }
            print(f"  H11 moderation: β(interaction)={results['h11']['coef_interaction']}, p={results['h11']['pval_interaction']}")
        except Exception as e:
            results['h11'] = {'error': str(e)}

    # H12: Headphone type → effect sizes (exploratórne)
    if 'headphones' in df.columns:
        hp_groups = df.groupby('headphones')[PRIMARY_SCALES].agg(['mean','std'])
        results['h12_headphone_means'] = hp_groups.round(3).to_dict()
        # Cohen's d medzi over_ear a in_ear_wireless
        for scale in ['valence', 'arousal']:
            g1 = df[df['headphones']=='over_ear'][scale].dropna()
            g2 = df[df['headphones']=='in_ear_wireless'][scale].dropna()
            if len(g1) >= 5 and len(g2) >= 5:
                pooled_std = np.sqrt(((len(g1)-1)*g1.std()**2 + (len(g2)-1)*g2.std()**2) / (len(g1)+len(g2)-2))
                d = (g1.mean() - g2.mean()) / pooled_std if pooled_std > 0 else 0
                results[f'h12_cohens_d_{scale}'] = round(float(d), 3)
                print(f"  H12 Cohen's d {scale} (over_ear vs in_ear): {round(d,3)}")

    return results


# ─────────────────────────────────────────────
# 8. BRAND IDENTITY — H7
# ─────────────────────────────────────────────

def brand_identity(df: pd.DataFrame) -> dict:
    agg = df.groupby('cell_var').agg(
        distinctiveness_mean=('distinctiveness','mean'),
        trustworthiness_mean=('trustworthiness','mean'),
        action_urge_mean=('action_urge','mean'),
        n=('valence','count')
    ).reset_index()

    # H7: top kvantil v oboch dimenziách + action_urge >= 4
    d_q75 = agg['distinctiveness_mean'].quantile(0.75)
    t_q75 = agg['trustworthiness_mean'].quantile(0.75)
    candidates = agg[
        (agg['distinctiveness_mean'] >= d_q75) &
        (agg['trustworthiness_mean'] >= t_q75) &
        (agg['action_urge_mean'] >= 4)
    ].sort_values('distinctiveness_mean', ascending=False)

    print(f"  H7 brand identity candidates: {len(candidates)}")
    return {
        'candidates': candidates.round(3).to_dict('records'),
        'thresholds': {'distinctiveness_q75': round(float(d_q75),3), 'trustworthiness_q75': round(float(t_q75),3)},
    }


# ─────────────────────────────────────────────
# 9. HTML REPORT
# ─────────────────────────────────────────────

def build_html_report(results: dict) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    qf  = results.get('quality', {})
    icc = results.get('icc', {})
    fa  = results.get('fa', {})
    mds = results.get('mds', {})
    reg = results.get('regression', {})
    mod = results.get('moderation', {})
    brand = results.get('brand', {})

    def icc_badge(v):
        if v is None: return '<span style="color:#64748b">N/A</span>'
        color = '#22c55e' if v >= 0.7 else '#f59e0b' if v >= 0.5 else '#ef4444'
        label = 'Good' if v >= 0.7 else 'Acceptable' if v >= 0.5 else 'Poor'
        return f'<span style="color:{color}">{v} ({label})</span>'

    def p_badge(p):
        if p is None: return ''
        color = '#22c55e' if p < 0.05 else '#f59e0b' if p < 0.1 else '#64748b'
        return f'<span style="color:{color}">p={p}</span>'

    icc_rows = ''.join(f'<tr><td><code>{s}</code></td><td>{icc_badge(icc.get(s,{}).get("icc"))}</td><td>{icc.get(s,{}).get("n","—")}</td></tr>' for s in PRIMARY_SCALES)

    fa_rec = fa.get('fa_3', {})
    fa_loadings = fa_rec.get('loadings', {})
    fa_var = fa_rec.get('variance_explained_pct', [])
    fa_scales = list(fa_loadings.get('F1', {}).keys()) if fa_loadings else []
    fa_header = ''.join(f'<th>F{i+1} ({fa_var[i]}%)</th>' for i in range(len(fa_var))) if fa_var else ''
    fa_rows = ''
    for s in fa_scales:
        vals = ''.join(f'<td style="color:{"#a5b4fc" if abs(fa_loadings.get(f"F{i+1}",{}).get(s,0))>0.4 else "#64748b"}">{fa_loadings.get(f"F{i+1}",{}).get(s,"—")}</td>' for i in range(len(fa_var)))
        fa_rows += f'<tr><td><code>{s}</code></td>{vals}</tr>'

    mds_points = ''
    if mds.get('mds_2d') and mds.get('variants'):
        for i,(v,c) in enumerate(zip(mds['variants'], mds['mds_2d'])):
            x = round((c[0]+3)*60+80, 1)
            y = round((c[1]+3)*40+60, 1)
            cell_num = v.split('_')[0]
            mds_points += f'<circle cx="{x}" cy="{y}" r="5" fill="#6366f1" opacity=".7"/><text x="{x+7}" y="{y+4}" font-size="9" fill="#94a3b8">{v}</text>'

    h1h3_rows = ''
    for k,v in reg.get('h1h3',{}).items():
        if isinstance(v, dict) and 'r2' in v:
            h1h3_rows += f'<tr><td>{v.get("label","")}</td><td>{v.get("r2","—")}</td><td>{p_badge(v.get("pval_var_num"))}</td><td>{v.get("n","—")}</td></tr>'

    h9_rows = ''.join(f'<tr><td><code>{r.get("target")}</code></td><td>{r.get("mean_r2","—")} ± {r.get("std_r2","—")}</td></tr>' for r in reg.get('h9_loco',[]))

    h11 = mod.get('h11', {})
    h11_html = f'<p>β(interaction) = {h11.get("coef_interaction","—")} &nbsp; {p_badge(h11.get("pval_interaction"))} &nbsp; R² = {h11.get("r2","—")} &nbsp; n = {h11.get("n","—")}</p>' if h11 else '<p style="color:#64748b">Insufficient data</p>'

    brand_candidates = brand.get('candidates', [])
    brand_rows = ''.join(f'<tr><td><code>{c.get("cell_var")}</code></td><td>{c.get("distinctiveness_mean","—")}</td><td>{c.get("trustworthiness_mean","—")}</td><td>{c.get("action_urge_mean","—")}</td></tr>' for c in brand_candidates[:10])

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Sonic Atoms — Analysis Report</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem}}
  h1{{font-size:1.6rem;color:#f1f5f9;margin-bottom:.3rem}}
  h2{{font-size:1.1rem;color:#a5b4fc;margin:2rem 0 .8rem;border-left:3px solid #6366f1;padding-left:.8rem}}
  .meta{{color:#64748b;font-size:.82rem;margin-bottom:2rem}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem;margin-bottom:2rem}}
  .stat{{background:#1e293b;border-radius:10px;padding:1rem 1.2rem}}
  .stat .num{{font-size:1.8rem;font-weight:800;color:#e2e8f0}}
  .stat .lbl{{font-size:.78rem;color:#64748b;margin-top:.2rem}}
  table{{width:100%;border-collapse:collapse;font-size:.85rem;margin-bottom:1.5rem}}
  th{{background:#1e293b;color:#94a3b8;text-align:left;padding:.55rem .8rem;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em}}
  td{{padding:.55rem .8rem;border-bottom:1px solid #1e293b;vertical-align:top}}
  tr:hover td{{background:#1e293b55}}
  code{{background:#0f172a;padding:.15rem .4rem;border-radius:4px;font-size:.82rem;color:#7dd3fc}}
  .section{{background:#1e293b;border-radius:12px;padding:1.5rem;margin-bottom:1.5rem}}
  svg text{{font-family:-apple-system,sans-serif}}
</style></head><body>
<h1>🎵 Sonic Atoms — Analysis Report</h1>
<div class="meta">Generated: {now} · Pipeline v1.0</div>

<div class="grid">
  <div class="stat"><div class="num">{qf.get('n_clean','—')}</div><div class="lbl">Respondents (clean)</div></div>
  <div class="stat"><div class="num">{qf.get('n_excluded','—')}</div><div class="lbl">Excluded (hard flag)</div></div>
  <div class="stat"><div class="num">{results.get('desc',{}).get('variants_ge30','—')}</div><div class="lbl">Variants ≥30 ratings</div></div>
  <div class="stat"><div class="num">{results.get('desc',{}).get('coverage_mean','—')}</div><div class="lbl">Avg ratings/variant</div></div>
</div>

<h2>ICC — Duplicate Reliability</h2>
<div class="section">
<table><thead><tr><th>Scale</th><th>ICC(2,1)</th><th>n pairs</th></tr></thead>
<tbody>{icc_rows}</tbody></table>
<p style="font-size:.8rem;color:#64748b">ICC &gt; 0.7 = Good · ICC &gt; 0.5 = Acceptable · ICC &lt; 0.5 = Poor</p>
</div>

<h2>Factor Analysis (3-factor model)</h2>
<div class="section">
<table><thead><tr><th>Scale</th>{fa_header}</tr></thead>
<tbody>{fa_rows}</tbody></table>
<p style="font-size:.8rem;color:#a5b4fc">Highlighted loadings |λ| &gt; 0.4</p>
</div>

<h2>MDS — Perceptual Space (2D)</h2>
<div class="section">
<svg width="100%" viewBox="0 0 500 300" style="background:#0f172a;border-radius:8px">
  <line x1="250" y1="20" x2="250" y2="280" stroke="#334155" stroke-width=".5"/>
  <line x1="40" y1="150" x2="460" y2="150" stroke="#334155" stroke-width=".5"/>
  {mds_points}
</svg>
<p style="font-size:.78rem;color:#64748b;margin-top:.5rem">Stress 2D: {mds.get('stress_2d','—')} · Stress 3D: {mds.get('stress_3d','—')} (lower = better fit)</p>
</div>

<h2>Regression — H1–H3 (Physics → Perception)</h2>
<div class="section">
<table><thead><tr><th>Hypothesis</th><th>R²</th><th>p(var)</th><th>n</th></tr></thead>
<tbody>{h1h3_rows if h1h3_rows else '<tr><td colspan="4" style="color:#475569">Insufficient data</td></tr>'}</tbody></table>
</div>

<h2>H9 — Leave-One-Cell-Out Cross-Validation</h2>
<div class="section">
<table><thead><tr><th>Target</th><th>Mean R² ± SD</th></tr></thead>
<tbody>{h9_rows if h9_rows else '<tr><td colspan="2" style="color:#475569">Insufficient data</td></tr>'}</tbody></table>
<p style="font-size:.8rem;color:#64748b">Target: mean R² ≥ 0.5 across cells (H9)</p>
</div>

<h2>H11 — Moderation: Sensitivity × Dissonance → Valence</h2>
<div class="section">{h11_html}</div>

<h2>H7 — Brand Identity Candidates</h2>
<div class="section">
<p style="font-size:.82rem;color:#64748b;margin-bottom:.8rem">Top quartile Distinctiveness + Trustworthiness, Action Urge ≥ 4</p>
<table><thead><tr><th>Variant</th><th>Distinctiveness</th><th>Trustworthiness</th><th>Action Urge</th></tr></thead>
<tbody>{brand_rows if brand_rows else '<tr><td colspan="4" style="color:#475569">No candidates found</td></tr>'}</tbody></table>
</div>

</body></html>"""


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run_pipeline(db_path: str = None, out_dir: str = '/tmp', simulate: bool = False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    print("\n🔬 Sonic Atoms Analysis Pipeline v1.0")
    print("─" * 45)

    print("\n📂 Loading data...")
    if simulate or not db_path or not os.path.exists(db_path):
        print("  Using simulated data (150 respondents)")
        df = simulate_data(150)
    else:
        df = load_data(db_path)

    print("\n🧹 Quality filtering...")
    df_main, df_full, quality = filter_quality(df)

    print("\n📊 Descriptive stats...")
    desc = descriptive_stats(df_main)

    print("\n🔁 ICC reliability...")
    icc = icc_reliability(df_full)

    print("\n🧩 Factor analysis...")
    fa = factor_analysis(df_main)

    print("\n🗺️  MDS...")
    mds = mds_analysis(df_main)

    print("\n📈 Regression models...")
    regression = regression_models(df_main)

    print("\n🔀 Moderation analysis...")
    moderation = moderation_analysis(df_main)

    print("\n🏷️  Brand identity...")
    brand = brand_identity(df_main)

    results = {
        'generated_at': datetime.now().isoformat(),
        'quality': quality, 'desc': desc, 'icc': icc,
        'fa': fa, 'mds': mds, 'regression': regression,
        'moderation': moderation, 'brand': brand,
    }

    # Ulož JSON
    json_path = os.path.join(out_dir, 'sonic_atoms_analysis.json')
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    # Ulož HTML
    html_path = os.path.join(out_dir, 'sonic_atoms_report.html')
    with open(html_path, 'w') as f:
        f.write(build_html_report(results))

    print(f"\n✅ Done!")
    print(f"   JSON: {json_path}")
    print(f"   HTML: {html_path}")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sonic Atoms Analysis Pipeline")
    ap.add_argument("--db",  default=None, help="SQLite DB path")
    ap.add_argument("--out", default="/tmp/sonic_analysis", help="Output dir")
    ap.add_argument("--simulate", action="store_true", help="Use simulated data")
    args = ap.parse_args()
    run_pipeline(db_path=args.db, out_dir=args.out, simulate=args.simulate)
