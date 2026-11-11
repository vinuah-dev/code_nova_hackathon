"""Feedback learning: a small model trained on this organisation's own accept/reject decisions.

Every time a reviewer accepts a finding (it was a real issue) or rejects it (false positive),
that is one labelled example. We train an L2-regularised logistic regression (pure NumPy,
Newton/IRLS) that predicts P(finding is a real issue) from interpretable features: category,
severity, engine, grounding, the engine's own confidence, target, and which rule family fired.

Safety gate: the model is always evaluated with grouped cross-validation (folds split by
submission, so it never sees the content it is scored on) and compared with the baseline,
which is the engine's own confidence. It only changes scores ("active") when
  * there are enough labels (MIN_SAMPLES, both classes, several submissions), and
  * it beats the baseline on out-of-fold Brier score by at least MIN_GAIN, without lower accuracy, and
  * an admin has not pinned it to shadow mode.
Otherwise it runs in shadow mode: predictions are shown next to findings but never change a score.
Gemini / rule findings are never removed by the model; at most their confidence is recalibrated.
"""
import threading

import numpy as np

from . import db

SEED_NOTE = "Seeded demo feedback"
MIN_SAMPLES = 30
MIN_PER_CLASS = 5
MIN_GROUPS = 4
MIN_GAIN = 0.10  # model Brier must be ≥10% lower than the baseline's
L2 = 1.0
SEVS = ["critical", "high", "medium", "low"]
CATS = ["claims", "facts", "terminology", "tone", "visual", "accessibility"]
FAMILY_MIN = 2  # a rule family needs this many labels before it gets its own weight

_lock = threading.Lock()
_cache: dict = {"id": None, "model": None}


# ------------------------------------------------------------------ features
def family(f: dict) -> str:
    sig = f.get("signature") or ""
    parts = sig.split(":")
    if f.get("engine") == "ai":
        return f"ai:{f.get('category')}"
    if parts[0] in ("a11y", "tone", "logo") or sig == "fact:expired-date":
        return ":".join(parts[:2])
    return parts[0] or "other"


def raw_conf(f: dict) -> float:
    return float(f.get("confidence_raw", f.get("confidence")) or 0.7)


def base_features(f: dict) -> dict:
    x = {"bias": 1.0, f"cat:{f.get('category')}": 1.0, f"sev:{f.get('severity')}": 1.0,
         "conf": raw_conf(f) - 0.75}
    if f.get("engine") == "ai":
        x["engine:ai"] = 1.0
        if not f.get("grounded"):
            x["ai:ungrounded"] = 1.0
    if (f.get("suggestion") or {}).get("replacement"):
        x["has_fix"] = 1.0
    t = (f.get("target") or "body").split(":")[0]
    if t != "body":
        x[f"target:{t}"] = 1.0
    x[f"rule:{family(f)}"] = 1.0
    return x


def _matrix(rows: list[dict], vocab: list[str]) -> np.ndarray:
    idx = {k: i for i, k in enumerate(vocab)}
    X = np.zeros((len(rows), len(vocab)))
    for r, f in enumerate(rows):
        for k, v in base_features(f).items():
            if k in idx:
                X[r, idx[k]] = v
    return X


def _vocab(rows: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for f in rows:
        for k in base_features(f):
            counts[k] = counts.get(k, 0) + 1
    fixed = ["bias", "conf"]
    return fixed + sorted(k for k, n in counts.items() if k not in fixed and n >= FAMILY_MIN)


# ------------------------------------------------------------------ model
def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """L2 logistic regression via Newton's method (bias is not penalised)."""
    w = np.zeros(X.shape[1])
    reg = np.full(X.shape[1], L2)
    reg[0] = 1e-6
    for _ in range(50):
        p = _sigmoid(X @ w)
        g = X.T @ (p - y) + reg * w
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(reg)
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-6:
            break
    return w


def _metrics(p: np.ndarray, y: np.ndarray) -> dict:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    pos, neg = p[y == 1], p[y == 0]
    auc = None
    if len(pos) and len(neg):
        auc = float(((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()) / (len(pos) * len(neg)))
    return {"brier": round(float(np.mean((p - y) ** 2)), 4),
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
            "accuracy": round(float(np.mean((p >= 0.5) == (y == 1))), 4),
            "auc": round(auc, 4) if auc is not None else None}


def labelled() -> list[dict]:
    """Every finding a human accepted or rejected, with its label and submission id."""
    rows = []
    for a in db.q("SELECT id, content_id, findings FROM analyses"):
        dec = {d["finding_id"]: d for d in db.q("SELECT finding_id, decision, note FROM decisions WHERE analysis_id=?", (a["id"],))}
        if not dec:
            continue
        for f in db.pj(a["findings"], []):
            d = dec.get(f.get("id"))
            if d and d["decision"] in ("accepted", "rejected"):
                rows.append({**f, "_y": 1.0 if d["decision"] == "accepted" else 0.0, "_group": a["content_id"],
                             "_seeded": d.get("note") == SEED_NOTE})
    return rows


def mode() -> str:
    r = db.one("SELECT value FROM kv WHERE key='learning_mode'")
    return r["value"] if r else "auto"


def set_mode(m: str) -> None:
    if m not in ("auto", "shadow"):
        raise ValueError("mode must be auto or shadow")
    db.ex("INSERT INTO kv(key, value) VALUES ('learning_mode', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (m,))
    _cache["id"] = None


def train() -> dict:
    """Retrain from all decisions, cross-validate against the baseline and store the result."""
    with _lock:
        rows = labelled()
        y = np.array([r["_y"] for r in rows])
        groups = sorted({r["_group"] for r in rows})
        n, npos = len(rows), int(y.sum()) if len(rows) else 0
        info = {"n": n, "positives": npos, "negatives": n - npos, "groups": len(groups),
                "seeded": sum(1 for r in rows if r["_seeded"]), "real": sum(1 for r in rows if not r["_seeded"])}
        reasons = []
        if n < MIN_SAMPLES:
            reasons.append(f"needs at least {MIN_SAMPLES} decisions (has {n})")
        if min(npos, n - npos) < MIN_PER_CLASS:
            reasons.append(f"needs at least {MIN_PER_CLASS} accepted and {MIN_PER_CLASS} rejected findings")
        if len(groups) < MIN_GROUPS:
            reasons.append(f"needs decisions on at least {MIN_GROUPS} different submissions")
        metrics, weights, vocab = None, None, None
        if n >= 8 and 0 < npos < n and len(groups) >= 2:
            vocab = _vocab(rows)
            X = _matrix(rows, vocab)
            # Grouped K-fold: a submission is never in both train and test.
            k = min(5, len(groups))
            fold_of = {g: i % k for i, g in enumerate(groups)}
            folds = np.array([fold_of[r["_group"]] for r in rows])
            oof = np.zeros(n)
            for i in range(k):
                tr, te = folds != i, folds == i
                if len(set(y[tr])) < 2:
                    oof[te] = y[tr].mean() if tr.any() else 0.5
                    continue
                oof[te] = _sigmoid(X[te] @ _fit(X[tr], y[tr]))
            base = np.array([raw_conf(r) for r in rows])
            m_model, m_base = _metrics(oof, y), _metrics(base, y)
            gain = (m_base["brier"] - m_model["brier"]) / m_base["brier"] if m_base["brier"] > 0 else 0.0
            metrics = {"model": m_model, "baseline": m_base, "brier_gain": round(gain, 4), "folds": k}
            if gain < MIN_GAIN:
                reasons.append(f"cross-validated Brier gain is {gain * 100:.0f}% (needs ≥ {MIN_GAIN * 100:.0f}%)")
            if m_model["accuracy"] < m_base["accuracy"]:
                reasons.append("cross-validated accuracy is below the baseline")
            weights = _fit(X, y).round(5).tolist()
        elif n:
            reasons.append("not enough variety to cross-validate yet")
        gate = not reasons
        status = "active" if gate and mode() == "auto" else ("shadow" if weights else "collecting")
        mid = db.ex("INSERT INTO ml_models(trained_at, status, gate_passed, info, metrics, vocab, weights, reasons) VALUES (?,?,?,?,?,?,?,?)",
                    (db.now(), status, int(gate), db.j(info), db.j(metrics), db.j(vocab), db.j(weights), db.j(reasons)))
        db.ex("DELETE FROM ml_models WHERE id < ?", (mid - 20,))
        _cache["id"] = None
        return current()


def current() -> dict | None:
    m = db.one("SELECT * FROM ml_models ORDER BY id DESC LIMIT 1")
    if not m:
        return None
    for k in ("info", "metrics", "vocab", "weights", "reasons"):
        m[k] = db.pj(m[k])
    # Mode can change after training; re-derive the effective status.
    if m["weights"]:
        m["status"] = "active" if m["gate_passed"] and mode() == "auto" else "shadow"
    m["mode"] = mode()
    return m


def _loaded():
    m = db.one("SELECT id FROM ml_models ORDER BY id DESC LIMIT 1")
    if not m:
        return None
    if _cache["id"] != m["id"]:
        _cache["model"], _cache["id"] = current(), m["id"]
    return _cache["model"]


def predict(f: dict) -> float | None:
    m = _loaded()
    if not m or not m.get("weights"):
        return None
    x = _matrix([f], m["vocab"])[0]
    return float(_sigmoid(x @ np.array(m["weights"])))


def annotate(findings: list[dict], apply: bool = True) -> None:
    """Attach the learned probability to each finding; recalibrate confidence only when active."""
    m = _loaded()
    if not m or not m.get("weights"):
        return
    active = apply and m["status"] == "active"
    for f in findings:
        p = predict(f)
        if p is None:
            continue
        f["learned"] = {"p": round(p, 3), "applied": active, "model_id": m["id"]}
        if active:
            f.setdefault("confidence_raw", f.get("confidence"))
            f["confidence"] = round(min(0.99, max(0.05, p)), 2)


def summary() -> dict:
    m = current()
    out = {"model": m, "thresholds": {"min_samples": MIN_SAMPLES, "min_per_class": MIN_PER_CLASS,
                                      "min_groups": MIN_GROUPS, "min_gain": MIN_GAIN}}
    if m and m.get("weights"):
        named = sorted(zip(m["vocab"], m["weights"]), key=lambda t: -abs(t[1]))
        out["signals"] = [{"feature": k, "label": _label(k), "weight": w} for k, w in named if k != "bias"][:10]
    return out


RULE_NAMES = {"term": "Product naming rule", "prohibited": "Prohibited phrase rule", "fact": "Fact sheet check",
              "claim": "Unsupported claim check", "fact:expired-date": "Expired offer date", "tone:exclamation": "Exclamation marks",
              "tone:all-caps": "All-caps emphasis", "a11y:long-sentence": "Long sentence", "a11y:hashtag-case": "Hashtag casing",
              "a11y:click-here": "'Click here' link text", "a11y:alt-missing": "Missing alt text", "a11y:alt-vague": "Vague alt text",
              "a11y:contrast": "Colour contrast", "visual": "Off-palette colour", "logo:unofficial": "Unofficial logo",
              "logo:distorted": "Distorted logo", "logo:recoloured": "Recoloured logo"}


def _label(k: str) -> str:
    names = {"conf": "Engine confidence", "engine:ai": "Found by AI", "ai:ungrounded": "AI finding without a cited source",
             "has_fix": "Has a suggested fix"}
    if k in names:
        return names[k]
    kind, _, v = k.partition(":")
    if kind == "rule":
        if v.startswith("ai:"):
            return f"AI finding ({v[3:]})"
        return RULE_NAMES.get(v, v)
    return {"cat": "Category", "sev": "Severity", "target": "Location"}.get(kind, kind) + f": {v}"
