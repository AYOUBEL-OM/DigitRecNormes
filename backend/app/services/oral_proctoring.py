"""
Proctoring entretien oral : agrégation d'événements navigateur / caméra
dans `tests_oraux` (colonnes existantes + JSONB `cheating_flags`).

Formulations neutres : indicateurs, scores estimatifs, pas de verdict « triche ».
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.oral_test_question import OralTestQuestion
from app.models.test_oral import TestOral

logger = logging.getLogger(__name__)

MAX_TIMELINE = 120
MAX_EVENTS = 200
PROC_VERSION = 2


def ensure_oral_detection_booleans(oral: TestOral) -> None:
    """
    Les colonnes de détection proctoring ne doivent jamais rester NULL : False tant qu’aucun signal
    ne les passe à True (compatibilité lignes historiques + ORM).
    """
    if oral.phone_detected is None:
        oral.phone_detected = False
    if oral.other_person_detected is None:
        oral.other_person_detected = False
    if oral.presence_anomaly_detected is None:
        oral.presence_anomaly_detected = False


def ensure_oral_proctoring_counts(oral: TestOral) -> None:
    """Compteurs entiers proctoring : jamais NULL (0 par défaut)."""
    if oral.suspicious_movements_count is None:
        oral.suspicious_movements_count = 0
    if oral.tab_switch_count is None:
        oral.tab_switch_count = 0
    if oral.fullscreen_exit_count is None:
        oral.fullscreen_exit_count = 0


def ensure_oral_proctoring_fields(oral: TestOral) -> None:
    """Booléens de détection + compteurs entiers — à appeler avant tout commit sur `tests_oraux`."""
    ensure_oral_detection_booleans(oral)
    ensure_oral_proctoring_counts(oral)


def refresh_suspicious_movements_count_from_flags(oral: TestOral) -> None:
    """
    Aligne `suspicious_movements_count` sur le JSON `cheating_flags` (gaze + compteurs),
    sans écraser les pics d’événements `suspicious_motion` déjà stockés (max des deux).
    À appeler avant scoring audio si aucun nouvel événement proctoring n’a été reçu.
    """
    ensure_oral_proctoring_counts(oral)
    flags = normalize_proctoring_flags(oral.cheating_flags)
    _recompute_gaze_ratios(flags["gaze"])
    oral.suspicious_movements_count = max(
        int(oral.suspicious_movements_count or 0),
        _aggregate_suspicious_movements_from_flags(flags),
    )


def _aggregate_suspicious_movements_from_flags(flags: dict[str, Any]) -> int:
    """
    Agrégat déterministe (idempotent) à partir du regard, du suivi instable, visage absent,
    mouvements rapides — complète les événements `suspicious_motion` déjà incrémentés sur la ligne.
    """
    ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
    fnv = int(ctr.get("face_not_visible_count") or 0)
    rapid = int(ctr.get("rapid_motion_heartbeat_count") or 0)
    head_sus = int(ctr.get("suspicious_head_movement_heartbeat_count") or 0)
    base = min(40, fnv * 2 + rapid + min(12, head_sus * 2))

    g = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    samples = max(0, int(g.get("samples") or 0))
    if samples < 10:
        return int(min(80, base))

    off = int(g.get("off_count") or 0)
    unk = int(g.get("unknown_count") or 0)
    off_r = off / max(samples, 1)
    unk_r = unk / max(samples, 1)
    w_off = min(24, int(off_r * 22))
    w_unk = min(18, int(unk_r * 18))
    return int(min(120, base + w_off + w_unk))


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_proctoring_metadata_objects(meta: dict[str, Any]) -> None:
    """
    Unifie `metadata.objects` en liste de chaînes minuscules (string[], [{label}], string unique).
    """
    raw = meta.get("objects")
    if raw is None:
        return
    out: list[str] = []
    if isinstance(raw, str):
        t = raw.lower().strip()
        if t:
            out.append(t)
    elif isinstance(raw, list):
        for o in raw:
            if isinstance(o, str):
                t = o.lower().strip()
                if t:
                    out.append(t)
            elif isinstance(o, dict):
                lab = str(o.get("label") or o.get("name") or o.get("class") or "").lower().strip()
                if lab:
                    out.append(lab)
    meta["objects"] = out


def normalize_proctoring_flags(raw: Any) -> dict[str, Any]:
    """Structure JSONB stable pour timeline + agrégats regard."""
    if raw is None:
        base: dict[str, Any] = {}
    elif isinstance(raw, dict):
        base = dict(raw)
    else:
        try:
            base = dict(json.loads(str(raw)))
        except Exception:
            base = {}

    base.setdefault("version", PROC_VERSION)
    base.setdefault("timeline", [])
    if not isinstance(base["timeline"], list):
        base["timeline"] = []
    base.setdefault(
        "gaze",
        {
            "samples": 0,
            "off_count": 0,
            "unknown_count": 0,
            "left": 0,
            "right": 0,
            "up": 0,
            "down": 0,
            "center": 0,
            "left_ratio": 0.0,
            "right_ratio": 0.0,
            "up_ratio": 0.0,
            "down_ratio": 0.0,
            "center_ratio": 0.0,
            "off_ratio": 0.0,
            "unknown_ratio": 0.0,
        },
    )
    if not isinstance(base["gaze"], dict):
        base["gaze"] = {
            "samples": 0,
            "off_count": 0,
            "unknown_count": 0,
            "left": 0,
            "right": 0,
            "up": 0,
            "down": 0,
            "center": 0,
            "left_ratio": 0.0,
            "right_ratio": 0.0,
            "up_ratio": 0.0,
            "down_ratio": 0.0,
            "center_ratio": 0.0,
            "off_ratio": 0.0,
            "unknown_ratio": 0.0,
        }
    for k in ("samples", "off_count", "unknown_count", "left", "right", "up", "down", "center"):
        base["gaze"].setdefault(k, 0)
    for rk in (
        "left_ratio",
        "right_ratio",
        "up_ratio",
        "down_ratio",
        "center_ratio",
        "off_ratio",
        "unknown_ratio",
    ):
        base["gaze"].setdefault(rk, 0.0)
    base.setdefault("events", [])
    if not isinstance(base["events"], list):
        base["events"] = []
    base.setdefault("estimates", {})
    base.setdefault("snapshots", [])
    if not isinstance(base["snapshots"], list):
        base["snapshots"] = []
    base.setdefault("counters", {})
    if not isinstance(base["counters"], dict):
        base["counters"] = {}
    for k in (
        "looking_left_count",
        "looking_right_count",
        "looking_up_count",
        "looking_down_count",
        "looking_center_count",
        "face_not_visible_count",
        "multiple_faces_count",
        "other_person_suspected_count",
        "tab_switch_count",
        "fullscreen_exit_count",
        "phone_suspected_count",
        "rapid_motion_heartbeat_count",
        "suspicious_head_movement_heartbeat_count",
        "suspicious_gaze_ratio_heartbeat_count",
        "forbidden_object_heartbeat_count",
        "phone_detected_events",
        "video_not_ready_hb_streak",
        "multi_face_hb_streak",
        "face_missing_hb_streak",
        "gaze_off_hb_streak",
        "face_detected_false_hb_streak",
        "presence_anomaly_events",
    ):
        base["counters"].setdefault(k, 0)
    base["counters"].setdefault("phone_evidence_sum", 0.0)
    base["counters"].setdefault("phone_confidence_peak", 0.0)
    base["counters"].setdefault("max_faces_count", 0)
    base["counters"].setdefault("phone_posture_streak", 0)
    base["counters"].setdefault("client_suspicious_gaze_heartbeats", 0)
    base.setdefault("proctoring_temporal", {})
    if not isinstance(base["proctoring_temporal"], dict):
        base["proctoring_temporal"] = {}
    pt = base["proctoring_temporal"]
    pt.setdefault("gaze_recent", [])
    if not isinstance(pt["gaze_recent"], list):
        pt["gaze_recent"] = []
    pt.setdefault("last_temporal_bonus", 0.0)
    pt.setdefault("last_event_ts", [])
    if not isinstance(pt["last_event_ts"], list):
        pt["last_event_ts"] = []
    base.setdefault("answer_insights", {})
    if not isinstance(base["answer_insights"], dict):
        base["answer_insights"] = {}
    base.setdefault("session_scores", {})
    if not isinstance(base["session_scores"], dict):
        base["session_scores"] = {}
    return base


def _append_timeline(flags: dict[str, Any], entry: dict[str, Any]) -> None:
    tl: list = flags["timeline"]
    entry = {**entry, "ts": entry.get("ts") or _utc_iso()}
    tl.append(entry)
    if len(tl) > MAX_TIMELINE:
        del tl[: len(tl) - MAX_TIMELINE]


def _phone_signal_weight(metadata: dict[str, Any]) -> float:
    """Poids 0.35–1.0 d’un signal « téléphone » (score / posture / confiance client)."""
    meta = metadata or {}
    for key in ("phone_confidence", "score", "phone_posture_score"):
        s = meta.get(key)
        if isinstance(s, (int, float)):
            return max(0.35, min(1.0, float(s)))
    return 0.48


def _accumulate_phone_evidence(
    ctr: dict[str, Any],
    weight: float,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    ctr["phone_suspected_count"] = int(ctr.get("phone_suspected_count") or 0) + 1
    prev = float(ctr.get("phone_evidence_sum") or 0.0)
    ctr["phone_evidence_sum"] = round(prev + weight, 3)
    meta = metadata or {}
    peak_c = 0.0
    for key in ("phone_confidence", "score", "phone_posture_score"):
        v = meta.get(key)
        if isinstance(v, (int, float)):
            peak_c = max(peak_c, float(v))
    if peak_c > 0:
        ctr["phone_confidence_peak"] = round(
            max(float(ctr.get("phone_confidence_peak") or 0.0), peak_c),
            3,
        )


def _heartbeat_phone_signal(meta: dict[str, Any]) -> bool:
    """Heartbeat : posture score, drapeau explicite, confiance ou liste d’objets."""
    if meta.get("phone_suspected") or meta.get("phone_detected") is True:
        return True
    pps = meta.get("phone_posture_score")
    if isinstance(pps, (int, float)) and float(pps) >= 0.25:
        return True
    pc = meta.get("phone_confidence")
    if isinstance(pc, (int, float)) and float(pc) >= 0.4:
        return True
    objs = meta.get("objects")
    if isinstance(objs, list):
        for o in objs:
            if isinstance(o, str) and o.lower() in ("phone", "mobile", "cell", "smartphone", "cell phone"):
                return True
            if isinstance(o, dict):
                lab = str(o.get("label") or o.get("name") or o.get("class") or "").lower().strip()
                if lab in ("phone", "mobile", "cell", "smartphone", "cell phone"):
                    return True
    return False


def _evaluate_phone_detected(oral: TestOral, ctr: dict[str, Any]) -> None:
    """
    Fusion multi-signaux : pic confiance, posture répétée (≥2 heartbeats), preuve cumulée.
    Ne repasse jamais à False une fois True.
    """
    if oral.phone_detected:
        return
    cnt = int(ctr.get("phone_suspected_count") or 0)
    ev = float(ctr.get("phone_evidence_sum") or 0.0)
    peak = float(ctr.get("phone_confidence_peak") or 0.0)
    posture_streak = int(ctr.get("phone_posture_streak") or 0)
    if peak >= 0.4:
        oral.phone_detected = True
    elif posture_streak >= 1:
        oral.phone_detected = True
    elif ev >= 0.85:
        oral.phone_detected = True
    elif peak >= 0.4 and cnt >= 1 and ev >= 0.30:
        oral.phone_detected = True
    elif cnt >= 2 and ev >= 0.60:
        oral.phone_detected = True
    elif cnt >= 3 and ev >= 0.95:
        oral.phone_detected = True
    elif cnt >= 4 and ev >= 2.0:
        oral.phone_detected = True
    if oral.phone_detected:
        ctr["phone_detection_peak_confidence"] = round(peak, 3)
    print(
        "PHONE_DETECTED_EVAL",
        {
            "oral_id": str(oral.id),
            "phone_suspected_count": cnt,
            "phone_evidence_sum": ev,
            "phone_confidence_peak": peak,
            "phone_posture_streak": posture_streak,
            "phone_detected": oral.phone_detected,
        },
        flush=True,
    )


def compute_suspicion_score(
    oral: TestOral,
    flags: dict[str, Any],
    temporal_bonus: float = 0.0,
) -> float:
    """
    Score agrégé 0–100 : regard, mouvements, navigation, téléphone (preuve cumulée), visages multiples, visage absent.
    """
    flags = normalize_proctoring_flags(flags)
    _recompute_gaze_ratios(flags["gaze"])
    g = flags.get("gaze") or {}
    ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
    off_ratio = float(g.get("off_ratio") or 0.0)
    rapid = min(int(ctr.get("rapid_motion_heartbeat_count") or 0), 10)
    tabs = int(oral.tab_switch_count or 0)
    fs = int(oral.fullscreen_exit_count or 0)
    phone_ev = float(ctr.get("phone_evidence_sum") or 0.0)
    mf = int(ctr.get("multiple_faces_count") or 0)
    fnv = int(ctr.get("face_not_visible_count") or 0)
    head_hb = min(int(ctr.get("suspicious_head_movement_heartbeat_count") or 0), 12)

    sg_client = int(ctr.get("client_suspicious_gaze_heartbeats") or 0)
    mf_weight = 14.0 if bool(oral.other_person_detected) else 3.5
    fnv_weight = 10.0 if fnv >= 8 else 4.0
    score = (
        off_ratio * 30.0
        + float(rapid) * 2.0
        + float(tabs) * 5.0
        + float(fs) * 5.0
        + phone_ev * 20.0
        + float(mf) * mf_weight
        + float(fnv) * fnv_weight
        + float(max(0.0, temporal_bonus))
        + min(22.0, float(sg_client) * 3.2)
        + float(head_hb) * 0.9
    )
    return float(max(0.0, min(100.0, score)))


def suspicion_risk_level(score: float) -> str:
    if score < 30.0:
        return "LOW"
    if score <= 60.0:
        return "MEDIUM"
    return "HIGH"


def gate_suspicion_high_level(
    oral: TestOral,
    flags: dict[str, Any],
    score: float,
    level: str,
) -> tuple[float, str]:
    """
    HIGH uniquement si au moins deux familles de signaux « confirmées » côté session,
    ou un signal répété (seuils compteurs) — évite les pics à partir d’un seul bruit court.
    """
    if level != "HIGH":
        return score, level
    ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
    kinds = (
        (1 if oral.phone_detected else 0)
        + (1 if oral.other_person_detected else 0)
        + (1 if oral.presence_anomaly_detected else 0)
    )
    pres_ev = int(ctr.get("presence_anomaly_events") or 0)
    mf_ev = int(ctr.get("multiple_faces_count") or 0)
    fnv = int(ctr.get("face_not_visible_count") or 0)
    if kinds >= 2:
        return score, level
    if pres_ev >= 3 or mf_ev >= 3 or fnv >= 10:
        return score, level
    capped = float(min(score, 58.0))
    return capped, "MEDIUM"


def apply_minimum_suspicion_for_critical_flags(
    oral: TestOral,
    suspicion_score: float,
    flags: Optional[dict[str, Any]] = None,
) -> float:
    """
    Signaux critiques (téléphone, tiers, sortie de cadre / présence) : plancher de suspicion 35/100
    et niveau au minimum MEDIUM via les seuils des fonctions appelantes (ex. score ≥ 35 → pas LOW
    avec `suspicion_risk_level` qui bascule à MEDIUM dès 30).
    Regard atypique répété côté client (fenêtre glissante) : même plancher.
    """
    out = float(suspicion_score)
    if oral.phone_detected or oral.other_person_detected:
        out = max(out, 35.0)
    if oral.presence_anomaly_detected:
        if flags is not None:
            ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
            pae = int(ctr.get("presence_anomaly_events") or 0)
            if pae >= 2 or oral.phone_detected or oral.other_person_detected:
                out = max(out, 30.0)
            else:
                out = max(out, 16.0)
        else:
            out = max(out, 16.0)
    # Mouvement suspect (toutes sources) : planchers atténués pour limiter les faux positifs
    mv = int(oral.suspicious_movements_count or 0)
    if mv >= 1:
        out = max(out, 18.0)
    if mv >= 2:
        out = max(out, 26.0)
    if flags is not None:
        ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
        sh = int(ctr.get("suspicious_head_movement_heartbeat_count") or 0)
        if sh >= 1:
            out = max(out, 10.0)
        if sh >= 2:
            out = max(out, 16.0)
        # Si `estimates.head_pose.suspicious_head_movement == true` (ex. métrique client), appliquer le plancher.
        est = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
        hp = est.get("head_pose") if isinstance(est.get("head_pose"), dict) else {}
        if hp.get("suspicious_head_movement") is True:
            out = max(out, 12.0)
        if int(ctr.get("client_suspicious_gaze_heartbeats") or 0) >= 2:
            out = max(out, 28.0)
    return out


def _suspicious_gaze_from_ratios(g: dict[str, Any]) -> bool:
    off_r = float(g.get("off_ratio") or 0.0)
    down_r = float(g.get("down_ratio") or 0.0)
    left_r = float(g.get("left_ratio") or 0.0)
    right_r = float(g.get("right_ratio") or 0.0)
    up_r = float(g.get("up_ratio") or 0.0)
    return bool(
        off_r > 0.55
        or down_r > 0.4
        or left_r > 0.4
        or right_r > 0.4
        or up_r > 0.45
    )


def _compute_behavior_tag(
    suspicion_score: float,
    risk_level: str,
    suspicious_gaze: bool,
    oral: TestOral,
) -> str:
    if risk_level == "HIGH" or (oral.phone_detected and oral.other_person_detected):
        return "high_risk"
    if (
        oral.phone_detected
        or oral.other_person_detected
        or suspicion_score >= 45.0
        or suspicious_gaze
        or oral.presence_anomaly_detected
    ):
        return "suspicious"
    if (
        suspicion_score >= 22.0
        or (oral.tab_switch_count or 0) >= 5
        or (oral.fullscreen_exit_count or 0) >= 4
    ):
        return "distracted"
    return "stable"


def _record_heartbeat_temporal(flags: dict[str, Any], gaze_dir: str, meta: dict[str, Any]) -> float:
    """Séquence courte de heartbeats + bonus si motif répété (ex. regard bas, mouvements)."""
    pt = flags.setdefault("proctoring_temporal", {})
    if not isinstance(pt, dict):
        pt = {}
        flags["proctoring_temporal"] = pt
    seq = pt.setdefault("gaze_recent", [])
    if not isinstance(seq, list):
        seq = []
        pt["gaze_recent"] = seq
    ts = _utc_iso()
    seq.append(
        {
            "gaze": gaze_dir,
            "ts": ts,
            "rapid": bool(meta.get("rapid_motion")),
        }
    )
    if len(seq) > 16:
        del seq[: len(seq) - 16]
    ev_ts = pt.setdefault("last_event_ts", [])
    if isinstance(ev_ts, list):
        ev_ts.append(ts)
        if len(ev_ts) > 40:
            del ev_ts[: len(ev_ts) - 40]

    bonus = 0.0
    if len(seq) >= 3 and all(str(x.get("gaze")) == "down" for x in seq[-3:]):
        bonus += 8.0
    last5 = seq[-5:]
    if len(last5) >= 3:
        downs = sum(1 for x in last5 if str(x.get("gaze")) == "down")
        if downs >= 3:
            bonus += 5.0
        raps = sum(1 for x in last5 if x.get("rapid"))
        if raps >= 3:
            bonus += 7.0
    pt["last_temporal_bonus"] = round(bonus, 2)
    return bonus


def _apply_intelligent_detections(oral: TestOral, flags: dict[str, Any]) -> dict[str, Any]:
    """
    Met à jour booléens (téléphone / autre personne / présence collants où requis),
    regard suspect, score de suspicion, niveau de risque, behavior_tag.
    """
    ensure_oral_proctoring_fields(oral)
    flags = normalize_proctoring_flags(flags)
    _sync_gaze_counters(flags, oral)
    _recompute_gaze_ratios(flags["gaze"])
    g = flags["gaze"]
    ctr = flags.setdefault("counters", {})
    if not isinstance(ctr, dict):
        ctr = {}
        flags["counters"] = ctr

    # Présence / tiers : ne pas forcer depuis des ratios bruités ; les heartbeats et événements dédiés pilotent les booléens.

    est_gw = (flags.get("estimates") or {}).get("gaze_window")
    gw_snap = est_gw if isinstance(est_gw, dict) else {}
    client_suspicious = bool(gw_snap.get("suspicious_gaze") is True)
    suspicious_gaze = (
        _suspicious_gaze_from_ratios(g)
        or client_suspicious
        or _client_window_ratios_suspicious(gw_snap)
    )

    _evaluate_phone_detected(oral, ctr)

    pt = flags.get("proctoring_temporal") if isinstance(flags.get("proctoring_temporal"), dict) else {}
    temporal_bonus = float(pt.get("last_temporal_bonus") or 0.0)

    suspicion = compute_suspicion_score(oral, flags, temporal_bonus)
    suspicion = apply_minimum_suspicion_for_critical_flags(oral, suspicion, flags)
    suspicion = float(max(0.0, min(100.0, suspicion)))
    risk = suspicion_risk_level(suspicion)
    suspicion, risk = gate_suspicion_high_level(oral, flags, suspicion, risk)
    behavior_tag = _compute_behavior_tag(suspicion, risk, suspicious_gaze, oral)

    print(
        "PROCTORING ANALYSIS:",
        {
            "score": round(suspicion, 2),
            "risk": risk,
            "phone": oral.phone_detected,
            "other_person": oral.other_person_detected,
            "presence": oral.presence_anomaly_detected,
            "suspicious_gaze": suspicious_gaze,
            "behavior_tag": behavior_tag,
            "temporal_bonus": temporal_bonus,
        },
        flush=True,
    )

    return {
        "suspicion_score": round(suspicion, 2),
        "suspicion_risk_level": risk,
        "suspicious_gaze": suspicious_gaze,
        "behavior_tag": behavior_tag,
        "temporal_bonus_applied": round(temporal_bonus, 2),
    }


def _append_event(flags: dict[str, Any], event_type: str, detail: Any = None) -> None:
    """Événements discrets (navigation, regard agrégé, etc.) — complète la timeline."""
    ev: dict[str, Any] = {"type": event_type, "ts": _utc_iso()}
    if detail is not None:
        ev["detail"] = detail
    events: list = flags.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        flags["events"] = events
    events.append(ev)
    if len(events) > MAX_EVENTS:
        del events[: len(events) - MAX_EVENTS]


def _has_audio_relevance_scores(db: Session, test_oral_id: Any) -> bool:
    q = (
        db.query(OralTestQuestion)
        .filter(
            OralTestQuestion.test_oral_id == test_oral_id,
            OralTestQuestion.relevance_score.isnot(None),
        )
        .first()
    )
    return q is not None


def build_flags_global_summary(oral: TestOral, flags: dict[str, Any]) -> str:
    """Résumé professionnel (neutre) : une phrase d’ensemble + détails factuels."""
    tabs = oral.tab_switch_count or 0
    fs = oral.fullscreen_exit_count or 0
    mv = oral.suspicious_movements_count or 0
    gaze = flags.get("gaze") or {}
    samples = int(gaze.get("samples") or 0)
    off = int(gaze.get("off_count") or 0)
    gaze_off_ratio = off / max(samples, 1) if samples else 0.0
    cr = float(gaze.get("center_ratio") or 0.0)
    lr = float(gaze.get("left_ratio") or 0.0)
    rr = float(gaze.get("right_ratio") or 0.0)
    ur = float(gaze.get("up_ratio") or 0.0)
    dr = float(gaze.get("down_ratio") or 0.0)
    unk_r = float(gaze.get("unknown_ratio") or 0.0)

    severity = 0
    if oral.phone_detected or oral.other_person_detected:
        severity += 2
    if tabs >= 6 or fs >= 6:
        severity += 2
    elif tabs >= 3 or fs >= 4:
        severity += 1
    if oral.presence_anomaly_detected:
        severity += 1
    if mv >= 8:
        severity += 2
    elif mv >= 4:
        severity += 1
    if samples > 8 and gaze_off_ratio >= 0.38:
        severity += 1

    if severity >= 4:
        headline = "Plusieurs indicateurs techniques à examiner : regard, navigation ou environnement."
    elif severity >= 2:
        headline = "À vérifier : signaux de navigation, cadrage visage ou mouvements."
    else:
        headline = "Comportement global stable au regard des indicateurs enregistrés."

    parts: list[str] = [headline]
    if tabs:
        parts.append(f"Perte de visibilité document : {tabs} occurrence(s).")
    if fs:
        parts.append(f"Sortie du plein écran : {fs} occurrence(s).")
    if mv:
        parts.append(f"Mouvements atypiques comptabilisés : {mv}.")
    if oral.phone_detected:
        parts.append("Indicateur « objet type téléphone » (heuristique caméra).")
    if oral.other_person_detected:
        parts.append("Indicateur « plusieurs visages » sur au moins deux détections.")
    if oral.presence_anomaly_detected:
        parts.append("Périodes sans visage détecté de façon répétée.")
    if samples > 8:
        parts.append(
            f"Regard (échantillonnage caméra) : centré ~{cr:.0%}, gauche ~{lr:.0%}, droite ~{rr:.0%}, "
            f"haut ~{ur:.0%}, bas ~{dr:.0%}, hors cadre ~{gaze_off_ratio:.0%}, indéterminé ~{unk_r:.0%}."
        )
    eye = oral.eye_contact_score_global
    if eye is not None:
        parts.append(f"Maintien du regard (estim.) : {eye}/100.")
    return " ".join(parts)


def get_proctoring_summary_text(oral: TestOral) -> str:
    """
    Texte de synthèse proctoring : lu depuis `cheating_flags.summary_global` si présent,
    sinon recalculé (rétrocompatibilité / lignes sans champ JSON).
    """
    flags = normalize_proctoring_flags(oral.cheating_flags)
    s = flags.get("summary_global")
    if isinstance(s, str) and s.strip():
        return s.strip()
    return build_flags_global_summary(oral, flags)


def build_candidate_warning(event_type: str, metadata: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Message court pour le candidat (non accusatoire). Retourné par /proctoring-event.
    """
    et = (event_type or "").strip().lower()
    meta = metadata or {}
    if et in ("visibility_hidden", "document_hidden", "tab_switch"):
        return {
            "id": "tab",
            "message": "Merci de rester sur l’onglet de l’entretien. Les sorties d’onglet peuvent être signalées.",
            "severity": "info",
        }
    if et in ("fullscreen_exit", "fullscreen_leave"):
        return {
            "id": "fs",
            "message": "Veuillez rester en plein écran pendant l’entretien.",
            "severity": "warn",
        }
    if et in ("suspicious_motion", "motion_spike"):
        return {
            "id": "motion",
            "message": "Essayez de limiter les mouvements brusques devant la caméra.",
            "severity": "info",
        }
    if et == "phone_detected":
        return {
            "id": "phone",
            "message": "Éloignez tout objet ressemblant à un téléphone du champ de la caméra.",
            "severity": "warn",
        }
    if et == "phone_suspected" and meta.get("active", True):
        return {
            "id": "phone",
            "message": "Éloignez tout objet ressemblant à un téléphone du champ de la caméra.",
            "severity": "warn",
        }
    if et == "other_person_suspected" and meta.get("active", True):
        return {
            "id": "other_person",
            "message": "Une autre personne semble visible : veuillez rester seul·e face à la caméra.",
            "severity": "warn",
        }
    if et == "other_person_detected":
        return {
            "id": "other_person",
            "message": "Une autre personne semble visible : veuillez rester seul·e face à la caméra.",
            "severity": "warn",
        }
    if et == "presence_anomaly":
        return {
            "id": "face",
            "message": "Gardez votre visage bien visible et centré dans le cadre.",
            "severity": "warn",
        }
    if et in ("heartbeat", "gaze_heartbeat"):
        gz = str(meta.get("gaze_region") or meta.get("gaze") or meta.get("gaze_direction") or "").lower()
        if gz in ("left", "right", "up", "down"):
            return {
                "id": f"gaze_{gz}",
                "message": "Merci de regarder vers l’écran / la caméra lorsque vous répondez.",
                "severity": "info",
            }
        if meta.get("phone_suspected"):
            return {
                "id": "phone_hb",
                "message": "Objet type téléphone détecté : merci de le retirer du cadre si possible.",
                "severity": "warn",
            }
        faces = meta.get("faces_count")
        if isinstance(faces, int) and faces >= 2:
            return {
                "id": "multi",
                "message": "Plusieurs visages détectés : assurez-vous d’être seul·e pendant l’entretien.",
                "severity": "warn",
            }
    return None


def compute_gaze_off_ratio(flags: dict[str, Any]) -> float:
    g = flags.get("gaze") or {}
    samples = max(1, int(g.get("samples") or 0))
    off = int(g.get("off_count") or 0)
    return off / samples


def compute_gaze_quality(flags: dict[str, Any]) -> dict[str, Any]:
    """
    Qualité du regard (0–100 + libellé + direction dominante) à partir des compteurs serveur
    et, si présents, des ratios fenêtre glissante envoyés par le client (heartbeat).
    """
    flags = normalize_proctoring_flags(flags)
    _recompute_gaze_ratios(flags["gaze"])
    g = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    est = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
    gw = est.get("gaze_window") if isinstance(est.get("gaze_window"), dict) else {}

    samples = int(g.get("samples") or 0)
    cr_s = float(g.get("center_ratio") or 0.0)
    off_s = float(g.get("off_ratio") or 0.0)
    down_s = float(g.get("down_ratio") or 0.0)
    left_s = float(g.get("left_ratio") or 0.0)
    right_s = float(g.get("right_ratio") or 0.0)
    up_s = float(g.get("up_ratio") or 0.0)
    unk_s = float(g.get("unknown_ratio") or 0.0)

    def _quality_from_ratios(
        cr: float,
        off: float,
        down: float,
        left: float,
        right: float,
        up: float,
        unk: float,
    ) -> tuple[str, str, float]:
        if cr >= 0.70 and off <= 0.20:
            return (
                "bonne",
                (
                    "Maintien du regard majoritairement vers la caméra / le centre, avec peu d’écarts hors cadre."
                ),
                float(max(0.0, min(100.0, 72.0 + cr * 28.0 - off * 22.0 - down * 12.0))),
            )
        if off > 0.50 or down > 0.40:
            return (
                "faible",
                (
                    "Part importante du temps hors cadre ou regard baissé : engagement visuel faible ou lecture possible."
                ),
                float(max(0.0, min(100.0, 38.0 + cr * 35.0 - off * 45.0 - down * 20.0))),
            )
        if cr >= 0.45:
            return (
                "moyenne",
                "Regard globalement centré mais avec des écarts réguliers hors axe ou hors cadre.",
                float(max(0.0, min(100.0, 52.0 + cr * 42.0 - off * 38.0 - unk * 15.0))),
            )
        return (
            "faible",
            "Peu de fixation centrale stable ; comportement visuel dispersé ou peu orienté caméra.",
            float(max(0.0, min(100.0, 35.0 + cr * 40.0 - off * 40.0))),
        )

    if _has_useful_client_gaze_window(gw):
        cr = float(gw.get("gaze_center_ratio") or 0.0)
        left = float(gw.get("gaze_left_ratio") or 0.0)
        right = float(gw.get("gaze_right_ratio") or 0.0)
        up = float(gw.get("gaze_up_ratio") or 0.0)
        down = float(gw.get("gaze_down_ratio") or 0.0)
        off = float(gw.get("gaze_off_ratio") or 0.0)
        ssum = cr + left + right + up + down + off
        if ssum > 1.001:
            sc = 1.0 / ssum
            cr, left, right, up, down, off = cr * sc, left * sc, right * sc, up * sc, down * sc, off * sc
        unk = max(0.0, 1.0 - cr - left - right - up - down - off)
        dirs = {
            "centre": cr,
            "hors cadre": off,
            "bas": down,
            "gauche": left,
            "droite": right,
            "haut": up,
        }
        dominant = max(dirs, key=lambda k: dirs[k])
        cli_label = gw.get("gaze_quality_label")
        cli_score = gw.get("gaze_quality_score")
        if isinstance(cli_label, str) and cli_label.strip() and isinstance(cli_score, (int, float)):
            label = cli_label.strip()
            score = float(max(0.0, min(100.0, float(cli_score))))
            expl = (
                "Synthèse issue de l’analyse caméra côté poste candidat (fenêtre glissante sur les derniers échantillons)."
            )
        else:
            label, expl, score = _quality_from_ratios(cr, off, down, left, right, up, max(unk, 0.02))
        gsamples = max(samples, 12)
        return {
            "label": label,
            "dominant_direction": dominant,
            "score": round(score, 2),
            "explanation": expl,
            "gaze_samples": gsamples,
            "gaze_center_ratio": round(cr, 4),
            "gaze_off_ratio": round(off, 4),
            "gaze_down_ratio": round(down, 4),
            "gaze_left_ratio": round(left, 4),
            "gaze_right_ratio": round(right, 4),
            "gaze_up_ratio": round(up, 4),
            "gaze_unknown_ratio": round(unk, 4),
            "source": "client_window",
        }

    cr, off, down, left, right, up, unk = cr_s, off_s, down_s, left_s, right_s, up_s, unk_s
    dirs = {
        "centre": cr,
        "hors cadre": off,
        "bas": down,
        "gauche": left,
        "droite": right,
        "haut": up,
    }
    dominant = max(dirs, key=lambda k: dirs[k])
    if samples < 5:
        label = "données insuffisantes"
        expl = (
            f"Échantillons de regard insuffisants ({samples} < 5) : interprétation limitée, "
            "à nuancer avec le contexte de la session."
        )
        score = 42.0
    else:
        label, expl, score = _quality_from_ratios(cr, off, down, left, right, up, unk)

    return {
        "label": label,
        "dominant_direction": dominant,
        "score": round(score, 2),
        "explanation": expl,
        "gaze_samples": samples,
        "gaze_center_ratio": round(cr, 4),
        "gaze_off_ratio": round(off, 4),
        "gaze_down_ratio": round(down, 4),
        "gaze_left_ratio": round(left, 4),
        "gaze_right_ratio": round(right, 4),
        "gaze_up_ratio": round(up, 4),
        "gaze_unknown_ratio": round(unk, 4),
        "source": "server_aggregates",
    }


def compute_movement_level(flags: dict[str, Any], oral: TestOral) -> dict[str, Any]:
    """
    Niveau d’agitation / mouvement (heartbeats rapides + agrégat mouvements suspects).
    """
    flags = normalize_proctoring_flags(flags)
    ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
    rapid = int(ctr.get("rapid_motion_heartbeat_count") or 0)
    sus = int(oral.suspicious_movements_count or 0)
    g = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    hb = int(g.get("samples") or 0)

    motion_index = rapid + min(sus, 8)
    # Seuils renforcés (retour terrain) : 2 mouvements rapides -> modéré ; 5 -> élevé
    if rapid >= 5 or motion_index >= 9:
        label = "élevé"
        expl = "Mouvements rapides fréquents et/ou instabilité marquée : agitation notable sur la session."
        agitation = float(min(100.0, 72.0 + (min(motion_index, 18) - 9) * 4.0))
    elif rapid >= 2 or motion_index >= 3:
        label = "modéré"
        expl = "Plusieurs mouvements rapides ou ajustements répétés ; compatible avec stress ou environnement perturbé."
        agitation = float(min(78.0, 38.0 + (motion_index - 2) * 8.5))
    elif motion_index <= 2:
        label = "faible"
        expl = "Peu de mouvements brusques détectés ; session visuellement stable."
        agitation = float(min(100.0, motion_index * 18.0))

    stability_score = float(max(0.0, min(100.0, 100.0 - agitation)))

    return {
        "label": label,
        "score": round(agitation, 2),
        "stability_score": round(stability_score, 2),
        "explanation": expl,
        "rapid_motion_heartbeat_count": rapid,
        "suspicious_movements_count": sus,
        "heartbeat_samples": hb,
        "motion_index": motion_index,
    }


def compute_presence_stability(oral: TestOral, flags: dict[str, Any]) -> dict[str, Any]:
    """Stabilité de présence (visage, cadre, conformité nombre de personnes)."""
    flags = normalize_proctoring_flags(flags)
    _recompute_gaze_ratios(flags["gaze"])
    g = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
    samples = int(g.get("samples") or 0)
    off = float(g.get("off_ratio") or 0.0)
    fnv = int(ctr.get("face_not_visible_count") or 0)
    mf = int(ctr.get("multiple_faces_count") or 0)

    if samples < 5:
        label = "données insuffisantes"
        score = 48.0
        expl = "Pas assez d’échantillons caméra pour conclure sur la stabilité de présence."
    elif oral.other_person_detected:
        label = "présence non conforme"
        score = 18.0
        expl = (
            "Indicateur « autre personne » ou visages multiples : la session ne respecte pas le cadre solo attendu."
        )
    elif fnv >= 3:
        label = "instable"
        score = 32.0
        expl = "Visage souvent absent du cadre : suivis de présence irréguliers."
    elif samples >= 5 and off > 0.60:
        label = "instable"
        score = 38.0
        expl = "Regard très souvent hors cadre ; cohérent avec une présence ou une attention moins continue."
    else:
        label = "stable"
        score = float(max(55.0, min(100.0, 88.0 - fnv * 6.0 - max(0.0, off - 0.25) * 40.0)))
        expl = "Candidat généralement visible et présent dans le cadre pendant la session."

    return {
        "label": label,
        "score": round(score, 2),
        "explanation": expl,
        "face_not_visible_count": fnv,
        "multiple_faces_count": mf,
        "gaze_samples": samples,
        "gaze_off_ratio": round(off, 4),
    }


def compute_suspicion_assessment(oral: TestOral, flags: dict[str, Any]) -> dict[str, Any]:
    """
    Niveau de suspicion RH (0–100) à partir de signaux observables, avec liste de signaux en français.
    """
    flags = normalize_proctoring_flags(flags)
    _recompute_gaze_ratios(flags["gaze"])
    g = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
    off = float(g.get("off_ratio") or 0.0)
    down = float(g.get("down_ratio") or 0.0)
    rapid = int(ctr.get("rapid_motion_heartbeat_count") or 0)
    tabs = int(oral.tab_switch_count or 0)
    fs = int(oral.fullscreen_exit_count or 0)

    gw_hb = (flags.get("estimates") or {}).get("gaze_window")
    gw_hb = gw_hb if isinstance(gw_hb, dict) else {}

    score = (
        float(tabs) * 8.0
        + float(fs) * 12.0
        + (30.0 if oral.phone_detected else 0.0)
        + (35.0 if oral.other_person_detected else 0.0)
        + (10.0 if oral.presence_anomaly_detected else 0.0)
        + off * 20.0
        + down * 15.0
        + float(min(rapid, 10)) * 2.0
    )
    if gw_hb.get("suspicious_gaze") is True or _client_window_ratios_suspicious(gw_hb):
        score += 18.0
    if int(ctr.get("client_suspicious_gaze_heartbeats") or 0) >= 2:
        score += 12.0
    score = float(max(0.0, min(100.0, score)))
    score = apply_minimum_suspicion_for_critical_flags(oral, score, flags)
    score = float(max(0.0, min(100.0, score)))

    if score < 25.0:
        level = "LOW"
    elif score <= 55.0:
        level = "MEDIUM"
    else:
        level = "HIGH"
    score, level = gate_suspicion_high_level(oral, flags, score, level)

    signals: list[str] = []
    if tabs > 0:
        signals.append(f"changements d’onglet ({tabs})")
    if fs > 0:
        signals.append(f"sorties du plein écran ({fs})")
    if oral.phone_detected:
        signals.append("objet type téléphone signalé")
    if oral.other_person_detected:
        signals.append("autre personne ou visages multiples")
    if oral.presence_anomaly_detected:
        signals.append("anomalie de présence / visage")
    if off >= 0.28:
        signals.append("regard souvent hors cadre")
    if down >= 0.22:
        signals.append("regard baissé fréquent")
    if rapid >= 3:
        signals.append("mouvements rapides répétés")
    if int(ctr.get("client_suspicious_gaze_heartbeats") or 0) >= 1:
        signals.append("regard atypique (analyse fenêtre navigateur)")
    if not signals:
        signals.append("aucun signal critique majeur dans les agrégats disponibles")

    expl = (
        f"Agrégat technique {score:.0f}/100 ({level}) basé sur navigation, caméra et indicateurs de session."
    )

    return {
        "level": level,
        "score": round(score, 2),
        "explanation": expl,
        "signals": signals,
    }


def merge_proctoring_estimates_enriched(oral: TestOral, flags: dict[str, Any]) -> dict[str, Any]:
    """
    Bloc à fusionner dans ``cheating_flags.estimates`` : analyses détaillées + métadonnées.
    N’écrase pas les booléens sur ``oral`` (JSON uniquement).
    """
    gaze_q = compute_gaze_quality(flags)
    movement = compute_movement_level(flags, oral)
    presence = compute_presence_stability(oral, flags)
    suspicion = compute_suspicion_assessment(oral, flags)

    out: dict[str, Any] = {
        "gaze_quality": gaze_q,
        "movement_analysis": movement,
        "presence_analysis": presence,
        "suspicion_assessment": suspicion,
        "suspicion_score": suspicion["score"],
        "suspicion_risk_level": suspicion["level"],
        "cheating_score": suspicion["score"],
        "cheating_risk_level": suspicion["level"],
        "gaze_stability_label": gaze_q["label"],
        "proctoring_enriched_at": _utc_iso(),
    }
    est_in = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
    gw_in = est_in.get("gaze_window") if isinstance(est_in.get("gaze_window"), dict) else None
    if gw_in:
        out["gaze_window_client"] = dict(gw_in)
    return out


def proctoring_stress_for_flags(oral: TestOral, flags: dict[str, Any]) -> float:
    """Stress technique session (0–100) à partir des colonnes + regard."""
    return _compute_proctoring_stress(oral, compute_gaze_off_ratio(flags))


def proctoring_confidence_for_flags(oral: TestOral, flags: dict[str, Any]) -> float:
    """Confiance « stabilité visuelle / session » (0–100)."""
    return _compute_proctoring_confidence(compute_gaze_off_ratio(flags), oral)


def _compute_proctoring_stress(oral: TestOral, gaze_off_ratio: float) -> float:
    """0–100 : niveau de « tension technique » estimé (onglets, plein écran, regard, objets)."""
    s = 0.0
    s += min(40.0, (oral.tab_switch_count or 0) * 7.0)
    s += min(35.0, (oral.fullscreen_exit_count or 0) * 9.0)
    s += min(25.0, (oral.suspicious_movements_count or 0) * 4.0)
    s += min(30.0, gaze_off_ratio * 55.0)
    if oral.phone_detected:
        s += 22.0
    if oral.other_person_detected:
        s += 18.0
    if oral.presence_anomaly_detected:
        s += 15.0
    return float(max(0.0, min(100.0, s)))


def _compute_proctoring_confidence(gaze_off_ratio: float, oral: TestOral) -> float:
    """0–100 : stabilité perçue (inverse partielle du stress visuel)."""
    base = 100.0 - gaze_off_ratio * 45.0
    base -= min(25.0, (oral.tab_switch_count or 0) * 4.0)
    base -= min(20.0, (oral.fullscreen_exit_count or 0) * 5.0)
    if oral.presence_anomaly_detected:
        base -= 12.0
    return float(max(0.0, min(100.0, base)))


def _sync_gaze_counters(flags: dict[str, Any], oral: TestOral) -> None:
    """Compteurs agrégés (indicateurs, pas verdict)."""
    g = flags.get("gaze") or {}
    c = flags.setdefault("counters", {})
    if not isinstance(c, dict):
        c = {}
        flags["counters"] = c
    c["looking_left_count"] = int(g.get("left") or 0)
    c["looking_right_count"] = int(g.get("right") or 0)
    c["looking_up_count"] = int(g.get("up") or 0)
    c["looking_down_count"] = int(g.get("down") or 0)
    c["looking_center_count"] = int(g.get("center") or 0)
    c["tab_switch_count"] = int(oral.tab_switch_count or 0)
    c["fullscreen_exit_count"] = int(oral.fullscreen_exit_count or 0)


def _recompute_gaze_ratios(g: dict[str, Any]) -> None:
    """Ratios directionnels / hors cadre à partir des compteurs `gaze`."""
    samples = max(0, int(g.get("samples") or 0))
    if samples <= 0:
        for rk in (
            "left_ratio",
            "right_ratio",
            "up_ratio",
            "down_ratio",
            "center_ratio",
            "off_ratio",
            "unknown_ratio",
        ):
            g[rk] = 0.0
        return
    s = float(samples)
    g["left_ratio"] = round(int(g.get("left") or 0) / s, 4)
    g["right_ratio"] = round(int(g.get("right") or 0) / s, 4)
    g["up_ratio"] = round(int(g.get("up") or 0) / s, 4)
    g["down_ratio"] = round(int(g.get("down") or 0) / s, 4)
    g["center_ratio"] = round(int(g.get("center") or 0) / s, 4)
    g["off_ratio"] = round(int(g.get("off_count") or 0) / s, 4)
    g["unknown_ratio"] = round(int(g.get("unknown_count") or 0) / s, 4)


def _heartbeat_meta_float(meta: dict[str, Any], key: str) -> Optional[float]:
    v = meta.get(key)
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _has_useful_client_gaze_window(gw: dict[str, Any]) -> bool:
    keys = (
        "gaze_center_ratio",
        "gaze_left_ratio",
        "gaze_right_ratio",
        "gaze_up_ratio",
        "gaze_down_ratio",
        "gaze_off_ratio",
    )
    n = sum(1 for k in keys if isinstance(gw.get(k), (int, float)) and not isinstance(gw.get(k), bool))
    return n >= 2


def _client_window_ratios_suspicious(gw: dict[str, Any]) -> bool:
    if not isinstance(gw, dict) or not _has_useful_client_gaze_window(gw):
        return False
    return bool(
        float(gw.get("gaze_down_ratio") or 0) > 0.4
        or float(gw.get("gaze_off_ratio") or 0) > 0.5
        or float(gw.get("gaze_left_ratio") or 0) > 0.45
        or float(gw.get("gaze_right_ratio") or 0) > 0.45
        or float(gw.get("gaze_up_ratio") or 0) > 0.45
    )


def _ingest_client_heartbeat_metrics(flags: dict[str, Any], oral: TestOral, meta: dict[str, Any]) -> None:
    """
    Métriques fenêtre glissante + téléphone envoyées par le navigateur (heartbeat).
    Stockage dans ``estimates.gaze_window`` ; renfort compteurs ``gaze`` et suspicion téléphone.
    """
    est = flags.setdefault("estimates", {})
    if not isinstance(est, dict):
        est = {}
        flags["estimates"] = est

    cr = _heartbeat_meta_float(meta, "gaze_center_ratio")
    lr = _heartbeat_meta_float(meta, "gaze_left_ratio")
    rr = _heartbeat_meta_float(meta, "gaze_right_ratio")
    ur = _heartbeat_meta_float(meta, "gaze_up_ratio")
    dr = _heartbeat_meta_float(meta, "gaze_down_ratio")
    orr = _heartbeat_meta_float(meta, "gaze_off_ratio")

    gw: dict[str, Any] = {}
    if cr is not None:
        gw["gaze_center_ratio"] = round(cr, 4)
    if lr is not None:
        gw["gaze_left_ratio"] = round(lr, 4)
    if rr is not None:
        gw["gaze_right_ratio"] = round(rr, 4)
    if ur is not None:
        gw["gaze_up_ratio"] = round(ur, 4)
    if dr is not None:
        gw["gaze_down_ratio"] = round(dr, 4)
    if orr is not None:
        gw["gaze_off_ratio"] = round(orr, 4)

    dom_raw = meta.get("dominant_gaze_direction")
    if isinstance(dom_raw, str) and dom_raw.strip():
        gw["dominant_gaze_direction"] = dom_raw.strip().lower()

    gqs = _heartbeat_meta_float(meta, "gaze_quality_score")
    if gqs is not None:
        gw["gaze_quality_score"] = round(max(0.0, min(100.0, gqs)), 2)
    gql = meta.get("gaze_quality_label")
    if isinstance(gql, str) and gql.strip():
        gw["gaze_quality_label"] = gql.strip()

    if meta.get("suspicious_gaze") is True:
        gw["suspicious_gaze"] = True

    prev_gw = est.get("gaze_window") if isinstance(est.get("gaze_window"), dict) else {}
    merged: dict[str, Any] = dict(prev_gw)
    merged.update(gw)
    if meta.get("suspicious_gaze") is True:
        merged["suspicious_gaze"] = True
    if gw or meta.get("suspicious_gaze") is True:
        merged["updated_at"] = _utc_iso()
        est["gaze_window"] = merged

    if _has_useful_client_gaze_window(merged):
        logger.info(
            "BACKEND GAZE METRICS RECEIVED oral_id=%s dominant=%s suspicious=%s ratios=%s",
            oral.id,
            merged.get("dominant_gaze_direction"),
            merged.get("suspicious_gaze"),
            {k: merged.get(k) for k in merged if isinstance(k, str) and k.startswith("gaze_") and k.endswith("_ratio")},
        )

    ctr = flags.setdefault("counters", {})
    if not isinstance(ctr, dict):
        ctr = {}
        flags["counters"] = ctr

    if meta.get("suspicious_gaze") is True:
        ctr["client_suspicious_gaze_heartbeats"] = int(ctr.get("client_suspicious_gaze_heartbeats") or 0) + 1

    # --- Nouveaux métriques (Web/Mediapipe) : gaze_ratio + head pose ---
    gaze_ratio = _heartbeat_meta_float(meta, "gaze_ratio")
    head_yaw = _heartbeat_meta_float(meta, "head_yaw")
    head_pitch = _heartbeat_meta_float(meta, "head_pitch")
    sus_head = meta.get("suspicious_head_movement") is True
    sus_gaze_ratio = False
    if gaze_ratio is not None:
        try:
            sus_gaze_ratio = float(gaze_ratio) < 0.38 or float(gaze_ratio) > 0.62
        except Exception:
            sus_gaze_ratio = False

    # Si yaw/pitch sont présents, appliquer les seuils même si le client n'a pas mis le booléen.
    if head_yaw is not None and abs(float(head_yaw)) > 12:
        sus_head = True
    if head_pitch is not None and float(head_pitch) > 15:
        sus_head = True

    if sus_head:
        print(
            "BACKEND HEAD MOVEMENT RECEIVED",
            {
                "oral_id": str(oral.id),
                "head_yaw": head_yaw,
                "head_pitch": head_pitch,
                "suspicious_head_movement": True,
            },
            flush=True,
        )

    if head_yaw is not None or head_pitch is not None or gaze_ratio is not None:
        hp_prev = est.get("head_pose") if isinstance(est.get("head_pose"), dict) else {}
        hp: dict[str, Any] = dict(hp_prev)
        if head_yaw is not None:
            hp["head_yaw"] = round(float(head_yaw), 3)
        if head_pitch is not None:
            hp["head_pitch"] = round(float(head_pitch), 3)
        if sus_head:
            hp["suspicious_head_movement"] = True
        hp["updated_at"] = _utc_iso()
        est["head_pose"] = hp

        gm_prev = est.get("gaze_metrics") if isinstance(est.get("gaze_metrics"), dict) else {}
        gm: dict[str, Any] = dict(gm_prev)
        if gaze_ratio is not None:
            gm["gaze_ratio"] = round(float(gaze_ratio), 3)
            gm["suspicious_gaze_ratio"] = bool(sus_gaze_ratio)
        gm["updated_at"] = _utc_iso()
        est["gaze_metrics"] = gm

    if sus_head:
        ctr["suspicious_head_movement_heartbeat_count"] = int(ctr.get("suspicious_head_movement_heartbeat_count") or 0) + 1
        c0 = int(ctr.get("suspicious_head_movement_heartbeat_count") or 0)
        # Incrémenter aussi le compteur SQL (throttlé pour éviter de surcompter chaque heartbeat)
        if c0 in (1, 2, 4) or c0 % 8 == 0:
            oral.suspicious_movements_count = int(oral.suspicious_movements_count or 0) + 1
        if c0 in (1, 3, 6) or c0 % 12 == 0:
            _append_timeline(
                flags,
                {
                    "type": "mouvement_tete_suspect",
                    "detail": {
                        "source": "head_pose",
                        "head_yaw": head_yaw,
                        "head_pitch": head_pitch,
                    },
                },
            )
    if sus_gaze_ratio:
        ctr["suspicious_gaze_ratio_heartbeat_count"] = int(ctr.get("suspicious_gaze_ratio_heartbeat_count") or 0) + 1
        c1 = int(ctr.get("suspicious_gaze_ratio_heartbeat_count") or 0)
        if c1 in (1, 4) or c1 % 15 == 0:
            _append_timeline(
                flags,
                {
                    "type": "heartbeat",
                    "detail": {
                        "source": "gaze_ratio",
                        "gaze_ratio": gaze_ratio,
                        "suspicious_gaze_ratio": True,
                    },
                },
            )

    objs = meta.get("objects")
    if isinstance(objs, list) and any(isinstance(o, str) and o.lower() in ("book", "laptop") for o in objs):
        ctr["forbidden_object_heartbeat_count"] = int(ctr.get("forbidden_object_heartbeat_count") or 0) + 1
        prev_forb = est.get("forbidden_objects_recent") if isinstance(est.get("forbidden_objects_recent"), list) else []
        cur = list(prev_forb)
        for o in objs:
            if isinstance(o, str) and o.lower() in ("book", "laptop"):
                cur.append(o.lower())
        est["forbidden_objects_recent"] = cur[-20:]
        c2 = int(ctr.get("forbidden_object_heartbeat_count") or 0)
        if c2 in (1, 2) or c2 % 10 == 0:
            _append_timeline(
                flags,
                {
                    "type": "heartbeat",
                    "detail": {
                        "source": "forbidden_object",
                        "objects": [o for o in objs if isinstance(o, str) and o.lower() in ("book", "laptop")][:4],
                    },
                },
            )

    pps = _heartbeat_meta_float(meta, "phone_posture_score")
    pstreak = meta.get("phone_posture_streak")
    p_det = meta.get("phone_detected") is True
    p_susp = meta.get("phone_suspected") is True
    if pps is not None or p_det or p_susp or isinstance(pstreak, (int, float)):
        logger.info(
            "BACKEND PHONE METRICS RECEIVED oral_id=%s phone_posture_score=%s streak=%s "
            "phone_detected=%s phone_suspected=%s",
            oral.id,
            pps,
            pstreak,
            p_det,
            p_susp,
        )

    objs = meta.get("objects")
    obj_phone = False
    if isinstance(objs, list):
        for o in objs:
            if not isinstance(o, str):
                continue
            s = o.lower().strip()
            if "phone" in s or s in ("mobile", "smartphone", "cell"):
                obj_phone = True
                break
    phone_signal = bool(
        p_det
        or p_susp
        or obj_phone
        or (pps is not None and pps >= 0.25)
    )
    if phone_signal:
        oral.phone_detected = True
        print(
            "BACKEND PHONE RECEIVED",
            {
                "oral_id": str(oral.id),
                "phone_detected": True,
                "phone_posture_score": pps,
                "phone_posture_streak": pstreak,
                "objects": meta.get("objects"),
            },
            flush=True,
        )
        # Compteur explicite (évite ambiguïtés côté rapport)
        ctr["phone_detected_events"] = int(ctr.get("phone_detected_events") or 0) + 1
        # Stockage des métriques téléphone côté estimates pour le rapport (sans nouvelles colonnes)
        pm_prev = est.get("phone_metrics") if isinstance(est.get("phone_metrics"), dict) else {}
        pm: dict[str, Any] = dict(pm_prev)
        pm["phone_detected"] = True
        if pps is not None:
            pm["phone_posture_score"] = round(float(pps), 3)
        if isinstance(pstreak, (int, float)) and not isinstance(pstreak, bool):
            pm["phone_posture_streak"] = int(max(0, round(float(pstreak))))
        pm["source"] = str(meta.get("source") or "heartbeat")
        pm["updated_at"] = _utc_iso()
        est["phone_metrics"] = pm
        # Timeline : marquer le 1er signal téléphone (et quelques répétitions), sans spam
        cph = int(ctr.get("phone_suspected_count") or 0)
        if cph in (0, 1, 2, 4) or cph % 12 == 0:
            _append_timeline(
                flags,
                {"type": "phone_detected", "detail": {"source": "heartbeat", "phone_posture_score": pps}},
            )

    if isinstance(pstreak, (int, float)) and not isinstance(pstreak, bool):
        ps_i = int(max(0, round(float(pstreak))))
        ctr["phone_posture_streak"] = max(int(ctr.get("phone_posture_streak") or 0), ps_i)

    g = flags.get("gaze")
    merged_gw = est.get("gaze_window") if isinstance(est.get("gaze_window"), dict) else {}
    if isinstance(g, dict) and _has_useful_client_gaze_window(merged_gw):
        dom = str(merged_gw.get("dominant_gaze_direction") or "").lower().strip()
        ratio_map = {
            "left": float(merged_gw.get("gaze_left_ratio") or 0.0),
            "right": float(merged_gw.get("gaze_right_ratio") or 0.0),
            "up": float(merged_gw.get("gaze_up_ratio") or 0.0),
            "down": float(merged_gw.get("gaze_down_ratio") or 0.0),
        }
        rdom = ratio_map.get(dom)
        if rdom is not None and rdom >= 0.38:
            boost = 2 if rdom >= 0.5 else 1
            if dom in ratio_map:
                k = dom
                g[k] = int(g.get(k) or 0) + boost
                _recompute_gaze_ratios(g)


def _gaze_stability_label(center_ratio: float, unknown_ratio: float, off_ratio: float) -> str:
    """Libellé neutre pour rapports (données réelles uniquement)."""
    if center_ratio >= 0.52 and unknown_ratio <= 0.12 and off_ratio <= 0.18:
        return "bonne"
    if center_ratio >= 0.34 or (unknown_ratio + off_ratio) <= 0.42:
        return "moyenne"
    return "faible"


def _apply_heartbeat_payload(flags: dict[str, Any], oral: TestOral, meta: dict[str, Any]) -> None:
    """Échantillon caméra / regard (heartbeat ou gaze_heartbeat, même charge utile)."""
    faces = int(meta.get("faces_count") if meta.get("faces_count") is not None else -1)
    face_visible = meta.get("face_visible")
    gaze = meta.get("gaze_region") or meta.get("gaze") or meta.get("gaze_direction") or "unknown"
    g = flags["gaze"]
    g["samples"] = int(g["samples"] or 0) + 1

    gz = str(gaze).lower()
    if gz in ("off", "away") or face_visible is False:
        g["off_count"] = int(g["off_count"] or 0) + 1
    elif gz in ("unknown",):
        g["unknown_count"] = int(g.get("unknown_count") or 0) + 1
    elif gz in ("left",):
        g["left"] = int(g["left"] or 0) + 1
    elif gz in ("right",):
        g["right"] = int(g["right"] or 0) + 1
    elif gz in ("up", "top"):
        g["up"] = int(g["up"] or 0) + 1
    elif gz in ("down", "bottom"):
        g["down"] = int(g["down"] or 0) + 1
    elif gz in ("center",):
        g["center"] = int(g.get("center") or 0) + 1
    else:
        g["unknown_count"] = int(g.get("unknown_count") or 0) + 1

    _recompute_gaze_ratios(g)

    ctr = flags.setdefault("counters", {})
    if not isinstance(ctr, dict):
        ctr = {}
        flags["counters"] = ctr

    pps_hb = meta.get("phone_posture_score")
    if isinstance(pps_hb, (int, float)):
        if float(pps_hb) >= 0.25:
            ctr["phone_posture_streak"] = int(ctr.get("phone_posture_streak") or 0) + 1
        elif float(pps_hb) < 0.20:
            ctr["phone_posture_streak"] = 0

    samp = int(g.get("samples") or 0)
    if samp <= 3 or samp % 60 == 0:
        logger.info(
            "oral_proctoring: gaze_heartbeat oral_id=%s samples=%s direction=%s faces=%s "
            "face_visible=%s video_not_ready=%s",
            oral.id,
            samp,
            gz,
            faces,
            face_visible,
            meta.get("video_not_ready"),
        )

    det_avail = meta.get("face_detector_available")
    face_detected = meta.get("face_detected")
    video_nr = meta.get("video_not_ready") is True
    if video_nr:
        ctr["video_not_ready_hb_streak"] = int(ctr.get("video_not_ready_hb_streak") or 0) + 1
    else:
        ctr["video_not_ready_hb_streak"] = 0

    no_face = (faces == 0 and face_visible is False) or (face_detected is False)
    if det_avail is not False and no_face:
        ctr["face_not_visible_count"] = int(ctr.get("face_not_visible_count") or 0) + 1
        ctr["face_missing_hb_streak"] = int(ctr.get("face_missing_hb_streak") or 0) + 1
    else:
        ctr["face_missing_hb_streak"] = 0

    if gz in ("off", "away"):
        ctr["gaze_off_hb_streak"] = int(ctr.get("gaze_off_hb_streak") or 0) + 1
    else:
        ctr["gaze_off_hb_streak"] = 0

    if face_detected is False:
        ctr["face_detected_false_hb_streak"] = int(ctr.get("face_detected_false_hb_streak") or 0) + 1
    else:
        ctr["face_detected_false_hb_streak"] = 0

    _HB_PRESENCE_CONFIRM = 3
    _HB_MULTI_FACE_CONFIRM = 3

    presence_reason = None
    if int(ctr.get("video_not_ready_hb_streak") or 0) >= _HB_PRESENCE_CONFIRM:
        presence_reason = "video_not_ready"
    elif int(ctr.get("face_missing_hb_streak") or 0) >= _HB_PRESENCE_CONFIRM:
        presence_reason = "face_missing"
    elif int(ctr.get("face_detected_false_hb_streak") or 0) >= _HB_PRESENCE_CONFIRM:
        presence_reason = "face_missing"

    if meta.get("presence_anomaly_detected") is True:
        presence_reason = presence_reason or str(meta.get("reason") or "frontend_flag")

    before_presence = bool(oral.presence_anomaly_detected)
    if presence_reason:
        oral.presence_anomaly_detected = True
        ctr["presence_anomaly_events"] = int(ctr.get("presence_anomaly_events") or 0) + 1
        est = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
        pm_prev = est.get("presence_metrics") if isinstance(est.get("presence_metrics"), dict) else {}
        pm: dict[str, Any] = dict(pm_prev)
        pm.update(
            {
                "presence_anomaly_detected": True,
                "faces_count": faces,
                "face_detected": meta.get("face_detected"),
                "gaze_direction": gz,
                "reason": str(meta.get("reason") or presence_reason),
                "source": str(meta.get("source") or "heartbeat"),
                "updated_at": _utc_iso(),
            }
        )
        est["presence_metrics"] = pm
        flags["estimates"] = est
        if not before_presence:
            print("BACKEND PRESENCE ANOMALY RECEIVED", {"reason": presence_reason, "meta": meta}, flush=True)
            _append_timeline(flags, {"type": "presence_anomaly", "detail": {"reason": presence_reason}})
            _append_event(flags, "presence_anomaly", {"reason": presence_reason})

    if faces >= 2:
        ctr["multi_face_hb_streak"] = int(ctr.get("multi_face_hb_streak") or 0) + 1
    else:
        ctr["multi_face_hb_streak"] = 0

    mfc_raw = meta.get("multiple_faces_confirmed")
    mfs = int(ctr.get("multi_face_hb_streak") or 0)
    if mfc_raw is False:
        multi_ok = False
    else:
        multi_ok = faces >= 2 and mfs >= _HB_MULTI_FACE_CONFIRM
    if multi_ok:
        before_op = bool(oral.other_person_detected)
        ctr["multiple_faces_count"] = int(ctr.get("multiple_faces_count") or 0) + 1
        ctr["other_person_suspected_count"] = int(ctr.get("other_person_suspected_count") or 0) + 1
        ctr["max_faces_count"] = int(max(int(ctr.get("max_faces_count") or 0), int(faces)))
        oral.other_person_detected = True
        print(
            "OTHER PERSON DETECTION (gaze_heartbeat):",
            {
                "oral_id": str(oral.id),
                "faces_count": faces,
                "multiple_faces_count": ctr.get("multiple_faces_count"),
                "other_person_suspected_count": ctr.get("other_person_suspected_count"),
                "other_person_detected_before": before_op,
                "other_person_detected_after": oral.other_person_detected,
                "multi_face_hb_streak": mfs,
                "multiple_faces_confirmed": mfc_raw,
            },
            flush=True,
        )

    print(
        "BACKEND PROCTORING RAW:",
        {
            "faces": faces,
            "face_visible": face_visible,
            "video_not_ready": meta.get("video_not_ready"),
            "presence_anomaly_detected": meta.get("presence_anomaly_detected"),
            "multiple_faces_confirmed": meta.get("multiple_faces_confirmed"),
            "multi_face_hb_streak": ctr.get("multi_face_hb_streak"),
            "face_missing_hb_streak": ctr.get("face_missing_hb_streak"),
            "video_not_ready_hb_streak": ctr.get("video_not_ready_hb_streak"),
        },
        flush=True,
    )
    if _heartbeat_phone_signal(meta):
        ctr["phone_detected_events"] = int(ctr.get("phone_detected_events") or 0) + 1
        if meta.get("phone_detected") is True:
            print("BACKEND PHONE RECEIVED", {"event_type": "heartbeat", "meta": meta}, flush=True)
        print(
            "PHONE DEBUG:",
            {
                "type": "heartbeat",
                "oral_id": str(oral.id),
                "payload": {k: meta.get(k) for k in ("phone_suspected", "phone_detected", "phone_confidence", "score", "phone_posture_score", "objects")},
            },
            flush=True,
        )
        w = _phone_signal_weight(meta)
        pps = meta.get("phone_posture_score")
        if isinstance(pps, (int, float)):
            w = max(w, min(1.0, float(pps) * 0.95))
        before_ev = float(ctr.get("phone_evidence_sum") or 0.0)
        before_cnt = int(ctr.get("phone_suspected_count") or 0)
        before_pd = bool(oral.phone_detected)
        _accumulate_phone_evidence(ctr, w, meta)
        if isinstance(meta.get("phone_confidence"), (int, float)) and float(meta["phone_confidence"]) >= 0.4:
            oral.phone_detected = True
        if meta.get("phone_detected") is True:
            oral.phone_detected = True
        _evaluate_phone_detected(oral, ctr)
        print(
            "PHONE SIGNAL (gaze_heartbeat)",
            {
                "oral_id": str(oral.id),
                "weight": w,
                "phone_evidence_sum_before": before_ev,
                "phone_evidence_sum_after": ctr.get("phone_evidence_sum"),
                "phone_suspected_count_before": before_cnt,
                "phone_suspected_count_after": ctr.get("phone_suspected_count"),
                "phone_detected_before": before_pd,
                "phone_detected_after": oral.phone_detected,
                "pps": meta.get("phone_posture_score"),
            },
            flush=True,
        )
    if meta.get("rapid_motion"):
        ctr["rapid_motion_heartbeat_count"] = int(ctr.get("rapid_motion_heartbeat_count") or 0) + 1

    _record_heartbeat_temporal(flags, gz, meta)

    tl: list = flags["timeline"]
    hb_in_tl = sum(1 for x in tl if isinstance(x, dict) and x.get("type") == "heartbeat")
    if samp % 18 == 0 and hb_in_tl < 48:
        _append_timeline(
            flags,
            {
                "type": "heartbeat",
                "faces": faces if faces >= 0 else None,
                "gaze": gz,
                "face_visible": face_visible,
            },
        )

    _ingest_client_heartbeat_metrics(flags, oral, meta)


def _load_test_oral_after_commit(db: Session, oral: TestOral) -> TestOral:
    """
    Recharge la ligne après commit sans appeler refresh() sur une instance potentiellement détachée
    (InvalidRequestError: Could not refresh instance <TestOral>).
    """
    oid = oral.id
    row = db.get(TestOral, oid)
    if row is not None:
        return row
    logger.warning("oral_proctoring: TestOral id=%s introuvable après commit, instance d'origine", oid)
    return oral


def _compute_cheating_score_and_risk(oral: TestOral, flags: dict[str, Any]) -> tuple[float, str]:
    """Aligné sur `compute_suspicion_score` + bonus temporel (cœur multi-signaux)."""
    pt = flags.get("proctoring_temporal") if isinstance(flags.get("proctoring_temporal"), dict) else {}
    tb = float(pt.get("last_temporal_bonus") or 0.0)
    s = compute_suspicion_score(oral, flags, tb)
    s = apply_minimum_suspicion_for_critical_flags(oral, s, flags)
    s = float(max(0.0, min(100.0, s)))
    level = suspicion_risk_level(s)
    s, level = gate_suspicion_high_level(oral, flags, s, level)
    return s, level


# Aucun échantillon gaze : valeur plancher explicite (évite NULL en base tout en signalant l’absence de données).
EYE_CONTACT_SCORE_NO_GAZE_SAMPLES = 20.0


def _compute_eye_contact_score_float(gaze: dict[str, Any]) -> float:
    """
    Score de maintien du regard 5–100 à partir des compteurs `gaze` (ratios à jour).
    Si `samples == 0`, retourne le plancher `EYE_CONTACT_SCORE_NO_GAZE_SAMPLES` (jamais None).
    """
    samples = max(0, int(gaze.get("samples") or 0))
    if samples <= 0:
        return float(EYE_CONTACT_SCORE_NO_GAZE_SAMPLES)
    off = max(0, int(gaze.get("off_count") or 0))
    gaze_off_ratio = off / max(samples, 1)
    unk = max(0, int(gaze.get("unknown_count") or 0))
    unknown_ratio = unk / max(samples, 1)
    lateral = int(gaze.get("left") or 0) + int(gaze.get("right") or 0)
    vertical = int(gaze.get("up") or 0) + int(gaze.get("down") or 0)
    lateral_ratio = lateral / max(samples, 1)
    vertical_ratio = vertical / max(samples, 1)
    center_ratio = int(gaze.get("center") or 0) / max(samples, 1)
    down_share = int(gaze.get("down") or 0) / max(samples, 1)
    quality = (
        0.66 * center_ratio
        + 0.06 * max(0.0, 1.0 - gaze_off_ratio - unknown_ratio)
    )
    noise = (
        0.40 * gaze_off_ratio
        + 0.18 * unknown_ratio
        + 0.26 * min(1.0, lateral_ratio + vertical_ratio)
        + 0.06 * down_share
    )
    eye = round(100.0 * max(0.0, min(1.0, quality - noise)), 2)
    return float(max(5.0, min(100.0, eye)))


def compute_eye_contact_score_global_from_flags(raw_flags: Any) -> float:
    """
    Point d’entrée pour recalculer le score regard depuis `cheating_flags` (JSON brut ou dict).
    Toujours un flottant : avec échantillons gaze le score calculé, sinon plancher.
    """
    flags = normalize_proctoring_flags(raw_flags)
    _recompute_gaze_ratios(flags["gaze"])
    return _compute_eye_contact_score_float(flags["gaze"])


def apply_proctoring_derived_scores(db: Session, oral: TestOral) -> TestOral:
    """
    Recalcule eye_contact_score_global, estimates JSON, résumé texte dans `cheating_flags.summary_global`,
    et (si pas encore de scores audio par question) confidence/stress depuis le proctoring seul.
    """
    ensure_oral_proctoring_fields(oral)
    flags = normalize_proctoring_flags(oral.cheating_flags)
    _recompute_gaze_ratios(flags["gaze"])
    _sync_gaze_counters(flags, oral)
    intel = _apply_intelligent_detections(oral, flags)
    cheat_s, cheat_lvl = _compute_cheating_score_and_risk(oral, flags)

    gaze = flags["gaze"]
    samples = max(0, int(gaze.get("samples") or 0))
    off = max(0, int(gaze.get("off_count") or 0))
    gaze_off_ratio = off / max(samples, 1)
    unk = max(0, int(gaze.get("unknown_count") or 0))
    unknown_ratio = unk / max(samples, 1)

    # Score global « maintien visuel » : prime au centre, pénalités douces hors cadre / hors axe / indéterminé
    lateral = int(gaze.get("left") or 0) + int(gaze.get("right") or 0)
    vertical = int(gaze.get("up") or 0) + int(gaze.get("down") or 0)
    lateral_ratio = lateral / max(samples, 1)
    vertical_ratio = vertical / max(samples, 1)
    center_ratio = int(gaze.get("center") or 0) / max(samples, 1)
    down_share = int(gaze.get("down") or 0) / max(samples, 1)

    eye = _compute_eye_contact_score_float(gaze)
    oral.eye_contact_score_global = eye

    agg_mv = _aggregate_suspicious_movements_from_flags(flags)
    event_mv = int(oral.suspicious_movements_count or 0)
    oral.suspicious_movements_count = max(event_mv, agg_mv)

    pc = _compute_proctoring_confidence(gaze_off_ratio, oral)
    ps = _compute_proctoring_stress(oral, gaze_off_ratio)
    stab = _gaze_stability_label(center_ratio, unknown_ratio, gaze_off_ratio)
    prev_est = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
    core_estimates = {
        "proctoring_confidence": round(pc, 2),
        "proctoring_stress": round(ps, 2),
        "gaze_off_ratio": round(gaze_off_ratio, 4),
        "gaze_unknown_ratio": round(unknown_ratio, 4),
        "gaze_center_ratio": round(center_ratio, 4),
        "gaze_samples": samples,
        "gaze_stability_label": stab,
        "cheating_score": round(cheat_s, 2),
        "cheating_risk_level": cheat_lvl,
        "suspicion_score": intel.get("suspicion_score"),
        "suspicion_risk_level": intel.get("suspicion_risk_level"),
        "suspicious_gaze": intel.get("suspicious_gaze"),
        "behavior_tag": intel.get("behavior_tag"),
        "temporal_bonus_applied": intel.get("temporal_bonus_applied"),
        "updated_at": _utc_iso(),
    }
    # IMPORTANT: ne pas écraser les métriques enrichies issues des heartbeats (head_pose, gaze_metrics, etc.).
    est_merged = dict(prev_est)
    est_merged.update(core_estimates)
    est_merged.update(merge_proctoring_estimates_enriched(oral, flags))
    est_merged["suspicious_gaze"] = intel.get("suspicious_gaze")
    est_merged["behavior_tag"] = intel.get("behavior_tag")
    est_merged["temporal_bonus_applied"] = intel.get("temporal_bonus_applied")
    flags["estimates"] = est_merged
    ss = flags.setdefault("session_scores", {})
    if isinstance(ss, dict):
        ss["gaze_breakdown"] = {
            "samples": samples,
            "center_ratio": round(center_ratio, 4),
            "left_ratio": round(float(gaze.get("left_ratio") or 0), 4),
            "right_ratio": round(float(gaze.get("right_ratio") or 0), 4),
            "up_ratio": round(float(gaze.get("up_ratio") or 0), 4),
            "down_ratio": round(float(gaze.get("down_ratio") or 0), 4),
            "off_ratio": round(gaze_off_ratio, 4),
            "unknown_ratio": round(unknown_ratio, 4),
            "stability_label": stab,
            "eye_contact_score_global": eye,
        }

    flags["summary_global"] = build_flags_global_summary(oral, flags)
    oral.cheating_flags = flags

    if not _has_audio_relevance_scores(db, oral.id):
        from app.services.oral_answer_analysis import (
            compute_session_confidence_detailed,
            compute_session_stress_detailed,
        )

        ctr0 = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
        rapid0 = int(ctr0.get("rapid_motion_heartbeat_count") or 0)
        fnv0 = int(ctr0.get("face_not_visible_count") or 0)
        gz0 = compute_gaze_quality(flags)
        mv0 = compute_movement_level(flags, oral)
        susp0 = compute_suspicion_assessment(oral, flags)
        stress0, stress_bd0 = compute_session_stress_detailed(
            None,
            rapid0,
            gaze_off_ratio,
            fnv0,
            short_answer_penalty=0.0,
        )
        conf0, conf_bd0 = compute_session_confidence_detailed(
            None,
            float(gz0["score"]),
            float(mv0["stability_score"]),
            55.0,
            0.0,
            str(susp0.get("level") or ""),
            oral,
        )
        oral.stress_score = round(stress0, 2)
        oral.confidence_score = round(conf0, 2)
        est_audio = dict(flags.get("estimates") or {})
        est_audio["stress_breakdown"] = stress_bd0
        est_audio["confidence_breakdown"] = conf_bd0
        flags["estimates"] = est_audio
        oral.cheating_flags = flags
        print(
            "PROCTORING SCORE DEBUG:",
            {
                "gaze": gz0,
                "movement": mv0,
                "presence": est_audio.get("presence_analysis"),
                "suspicion": susp0,
                "confidence": oral.confidence_score,
                "stress": oral.stress_score,
            },
            flush=True,
        )

    db.add(oral)
    db.commit()
    oral = _load_test_oral_after_commit(db, oral)
    logger.info(
        "oral_proctoring: derived scores test_oral_id=%s eye_global=%s proc_conf=%s proc_stress=%s",
        oral.id,
        oral.eye_contact_score_global,
        pc,
        ps,
    )

    # Réaligner confidence/stress avec l’audio si des réponses existent déjà (import paresseux)
    if _has_audio_relevance_scores(db, oral.id):
        from app.services.oral_answer_analysis import compute_oral_score

        compute_oral_score(db, oral.id)
        oral = _load_test_oral_after_commit(db, oral)
    return oral


def apply_proctoring_event(
    db: Session,
    oral: TestOral,
    event_type: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Applique un événement proctoring (incréments, booléens collants, timeline, regard).
    `event_type` : voir contrat route /oral/proctoring-event.
    """
    ensure_oral_proctoring_fields(oral)
    meta = dict(metadata or {})
    _normalize_proctoring_metadata_objects(meta)
    flags = normalize_proctoring_flags(oral.cheating_flags)

    et = (event_type or "").strip().lower()
    print("PROCTORING EVENT RECEIVED:", {"event_type": et, "metadata": meta}, flush=True)

    if et in ("visibility_hidden", "document_hidden", "tab_switch"):
        oral.tab_switch_count = (oral.tab_switch_count or 0) + 1
        _append_timeline(flags, {"type": "visibility_hidden", "detail": meta.get("detail")})
        _append_event(flags, "tab_switch", {"detail": meta.get("detail"), "count": oral.tab_switch_count})

    elif et in ("fullscreen_exit", "fullscreen_leave"):
        oral.fullscreen_exit_count = (oral.fullscreen_exit_count or 0) + 1
        _append_timeline(flags, {"type": "fullscreen_exit"})
        _append_event(flags, "fullscreen_exit", {"count": oral.fullscreen_exit_count})

    elif et in ("suspicious_motion", "motion_spike"):
        oral.suspicious_movements_count = (oral.suspicious_movements_count or 0) + 1
        _append_timeline(flags, {"type": "suspicious_motion", "detail": meta.get("detail")})
        _append_event(flags, "suspicious_motion", meta.get("detail"))

    elif et == "phone_detected":
        print("BACKEND PHONE EVENT HIT", meta, flush=True)
        ctr = flags.setdefault("counters", {})
        ctr["phone_detected_events"] = int(ctr.get("phone_detected_events") or 0) + 1
        before_pd = bool(oral.phone_detected)
        oral.phone_detected = True
        print("BACKEND PHONE RECEIVED", {"event_type": et, "meta": meta}, flush=True)
        print("PHONE DETECTION EVENT RECEIVED:", et, meta, flush=True)
        print(
            "PHONE DEBUG:",
            {
                "type": "phone_detected",
                "oral_id": str(oral.id),
                "payload": {k: meta.get(k) for k in ("phone_detected", "phone_confidence", "score", "phone_posture_score", "objects")},
            },
            flush=True,
        )
        pc = float(meta.get("phone_confidence") or meta.get("score") or 0.9)
        w = max(0.88, min(1.0, pc))
        _accumulate_phone_evidence(ctr, w, meta)
        ctr["phone_confidence_peak"] = round(max(float(ctr.get("phone_confidence_peak") or 0.0), w), 3)
        _evaluate_phone_detected(oral, ctr)
        print("PHONE EVIDENCE SUM:", ctr.get("phone_evidence_sum"), flush=True)
        print("PHONE DETECTED BEFORE:", before_pd, "AFTER:", oral.phone_detected, flush=True)
        _append_timeline(flags, {"type": "phone_detected", "confidence": pc})
        _append_event(flags, "phone_detected", {"confidence": pc, "evidence_sum": ctr.get("phone_evidence_sum")})
        est = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
        pm_prev = est.get("phone_metrics") if isinstance(est.get("phone_metrics"), dict) else {}
        pm: dict[str, Any] = dict(pm_prev)
        pps_ev = meta.get("phone_posture_score")
        pps_out: Optional[float] = None
        if isinstance(pps_ev, (int, float)) and not isinstance(pps_ev, bool):
            pps_out = round(float(pps_ev), 3)
        psk_ev = meta.get("phone_posture_streak")
        psk_out: Optional[int] = None
        if isinstance(psk_ev, (int, float)) and not isinstance(psk_ev, bool):
            psk_out = int(max(0, round(float(psk_ev))))
        pm.update(
            {
                "phone_detected": True,
                "phone_suspected": bool(meta.get("phone_suspected") or meta.get("phone_detected")),
                "phone_posture_score": pps_out if pps_out is not None else pps_ev,
                "phone_posture_streak": psk_out if psk_out is not None else psk_ev,
                "objects": meta.get("objects"),
                "source": str(meta.get("source") or "event"),
                "updated_at": _utc_iso(),
            }
        )
        est["phone_metrics"] = pm
        flags["estimates"] = est

    elif et in ("multiple_faces", "other_person_detected"):
        ctr = flags.setdefault("counters", {})
        faces = meta.get("faces_count") or meta.get("persons_count") or 2
        try:
            faces_i = int(faces)
        except Exception:
            faces_i = 2
        before_op = bool(oral.other_person_detected)
        ctr["multiple_faces_count"] = int(ctr.get("multiple_faces_count") or 0) + 1
        ctr["other_person_suspected_count"] = int(ctr.get("other_person_suspected_count") or 0) + 1
        ctr["max_faces_count"] = int(max(int(ctr.get("max_faces_count") or 0), faces_i))
        if faces_i >= 2 or meta.get("other_person_detected") is True:
            oral.other_person_detected = True
        print(
            "OTHER PERSON DETECTION:",
            {"faces_count": faces_i, "other_person_detected_before": before_op, "after": oral.other_person_detected},
            flush=True,
        )
        _append_timeline(flags, {"type": "multi_face", "faces": faces_i})
        _append_event(flags, "other_person_detected", {"faces": faces_i, "max_faces_count": ctr.get("max_faces_count")})

    elif et == "phone_suspected" and meta.get("active", True):
        ctr = flags.setdefault("counters", {})
        print("PHONE DETECTION EVENT RECEIVED:", et, meta, flush=True)
        print(
            "PHONE DEBUG:",
            {
                "type": "phone_suspected",
                "oral_id": str(oral.id),
                "payload": {k: meta.get(k) for k in ("phone_suspected", "phone_detected", "phone_confidence", "score", "phone_posture_score", "objects")},
            },
            flush=True,
        )
        strong = False
        if meta.get("phone_detected") is True:
            strong = True
        pc0 = meta.get("phone_confidence")
        if isinstance(pc0, (int, float)) and float(pc0) >= 0.4:
            strong = True
        objs = meta.get("objects")
        if isinstance(objs, list):
            for o in objs:
                if isinstance(o, str) and o.lower() in ("phone", "mobile", "cell", "smartphone"):
                    strong = True
                    break
                if isinstance(o, dict):
                    lab = str(o.get("label") or o.get("name") or o.get("class") or "").lower().strip()
                    if lab in ("phone", "mobile", "cell", "smartphone"):
                        strong = True
                        break
        w = max(_phone_signal_weight(meta), 0.58)
        if strong:
            w = max(w, 0.88)
        before_pd = bool(oral.phone_detected)
        _accumulate_phone_evidence(ctr, w, meta)
        if strong:
            oral.phone_detected = True
        _evaluate_phone_detected(oral, ctr)
        print("PHONE EVIDENCE SUM:", ctr.get("phone_evidence_sum"), flush=True)
        print("PHONE DETECTED BEFORE:", before_pd, "AFTER:", oral.phone_detected, flush=True)
        _append_timeline(flags, {"type": "phone_suspected", "score": meta.get("score")})
        _append_event(
            flags,
            "phone_suspected",
            {
                "score": meta.get("score"),
                "count": ctr["phone_suspected_count"],
                "evidence_sum": ctr.get("phone_evidence_sum"),
                "phone_confidence_peak": ctr.get("phone_confidence_peak"),
            },
        )

    elif et == "other_person_suspected" and meta.get("active", True):
        ctr = flags.setdefault("counters", {})
        before_op = bool(oral.other_person_detected)
        ctr["multiple_faces_count"] = int(ctr.get("multiple_faces_count") or 0) + 1
        ctr["other_person_suspected_count"] = int(ctr.get("other_person_suspected_count") or 0) + 1
        faces0 = meta.get("faces_count") or meta.get("persons_count")
        try:
            faces_i = int(faces0) if faces0 is not None else 2
        except Exception:
            faces_i = 2
        ctr["max_faces_count"] = int(max(int(ctr.get("max_faces_count") or 0), faces_i))
        if faces_i >= 2 or meta.get("other_person_detected") is True:
            oral.other_person_detected = True
        print(
            "OTHER PERSON DETECTION:",
            {
                "faces_count": faces_i,
                "multiple_faces_count": ctr.get("multiple_faces_count"),
                "other_person_suspected_count": ctr.get("other_person_suspected_count"),
                "other_person_detected_before": before_op,
                "other_person_detected_after": oral.other_person_detected,
            },
            flush=True,
        )
        _append_timeline(flags, {"type": "multi_face", "faces": faces_i})
        _append_event(
            flags,
            "other_person_suspected",
            {"faces": faces_i, "max_faces_count": ctr.get("max_faces_count")},
        )

    elif et == "presence_anomaly":
        ctr = flags.setdefault("counters", {})
        before_presence = bool(oral.presence_anomaly_detected)
        ctr["presence_anomaly_events"] = int(ctr.get("presence_anomaly_events") or 0) + 1
        ctr["face_not_visible_count"] = int(ctr.get("face_not_visible_count") or 0) + 1
        oral.presence_anomaly_detected = True
        print("BACKEND PRESENCE ANOMALY RECEIVED", {"event_type": et, "meta": meta}, flush=True)
        reason = meta.get("reason") or meta.get("detail") or "frontend_flag"
        est = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
        pm_prev = est.get("presence_metrics") if isinstance(est.get("presence_metrics"), dict) else {}
        pm: dict[str, Any] = dict(pm_prev)
        pm.update(
            {
                "presence_anomaly_detected": True,
                "faces_count": meta.get("faces_count"),
                "face_detected": meta.get("face_detected"),
                "gaze_direction": meta.get("gaze_direction") or meta.get("gaze_region") or meta.get("gaze"),
                "reason": reason,
                "source": meta.get("source") or "event",
                "updated_at": _utc_iso(),
            }
        )
        est["presence_metrics"] = pm
        flags["estimates"] = est
        if not before_presence:
            _append_timeline(flags, {"type": "presence_anomaly", "detail": {"reason": reason}})
        _append_event(flags, "presence_anomaly", {"reason": reason})

    elif et in ("heartbeat", "gaze_heartbeat"):
        _apply_heartbeat_payload(flags, oral, meta)

    elif et == "session_start":
        if oral.started_at is None:
            oral.started_at = datetime.now(timezone.utc)
        st = (oral.status or "").strip().lower()
        if not st or st in ("pending", "scheduled", "nouvelle"):
            oral.status = "in_progress"
        _append_timeline(flags, {"type": "session_start"})
        _append_event(flags, "session_start", None)

    elif et == "session_end":
        oral.finished_at = datetime.now(timezone.utc)
        if oral.started_at and oral.finished_at:
            ds = int(max(0.0, (oral.finished_at - oral.started_at).total_seconds()))
            oral.duration_seconds = ds
        oral.status = "completed"
        _append_timeline(flags, {"type": "session_end"})
        _append_event(flags, "session_end", {"duration_seconds": oral.duration_seconds})

    else:
        logger.warning("oral_proctoring: event_type inconnu ignoré: %s", event_type)
        return {"ok": False, "ignored": True, "reason": "unknown_event_type"}

    g_snap = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    if et in ("heartbeat", "gaze_heartbeat"):
        gz_dir = (
            meta.get("gaze_direction")
            or meta.get("gaze_region")
            or meta.get("gaze")
            or "—"
        )
        print(
            "BACKEND PROCTORING FINAL STATE:",
            {
                "event_type": et,
                "gaze_samples_after": int(g_snap.get("samples") or 0),
                "faces_count": meta.get("faces_count"),
                "gaze_direction": gz_dir,
                "face_visible": meta.get("face_visible"),
                "face_detector_available": meta.get("face_detector_available"),
                "tab": oral.tab_switch_count,
                "fullscreen": oral.fullscreen_exit_count,
                "phone": oral.phone_detected,
                "presence": oral.presence_anomaly_detected,
                "faces_counter_multiple": (flags.get("counters") or {}).get("multiple_faces_count"),
            },
            flush=True,
        )

    oral.cheating_flags = flags
    db.add(oral)
    db.commit()
    print(
        "PROCTORING BOOLEANS SAVED:",
        {
            "phone_detected": oral.phone_detected,
            "other_person_detected": oral.other_person_detected,
            "presence_anomaly_detected": oral.presence_anomaly_detected,
        },
        flush=True,
    )
    oral = _load_test_oral_after_commit(db, oral)

    oral = apply_proctoring_derived_scores(db, oral)

    warn = build_candidate_warning(et, meta)
    out: dict[str, Any] = {
        "ok": True,
        "tab_switch_count": oral.tab_switch_count,
        "fullscreen_exit_count": oral.fullscreen_exit_count,
        "suspicious_movements_count": oral.suspicious_movements_count,
        "presence_anomaly_detected": oral.presence_anomaly_detected,
        "phone_detected": oral.phone_detected,
        "other_person_detected": oral.other_person_detected,
        "eye_contact_score_global": oral.eye_contact_score_global,
        "confidence_score": oral.confidence_score,
        "stress_score": oral.stress_score,
    }
    if warn:
        out["candidate_warning"] = warn
    return out


def merge_audio_and_proctoring_scores(oral: TestOral) -> None:
    """
    Combine scores issus des réponses audio (déjà posés sur `oral`) avec
    les estimations proctoring stockées dans `cheating_flags.estimates`.
    Ne modifie pas `score_oral_global` (reste audio).
    """
    flags = normalize_proctoring_flags(oral.cheating_flags)
    est = flags.get("estimates") or {}
    pc = est.get("proctoring_confidence")
    ps = est.get("proctoring_stress")

    if pc is None and ps is None:
        return

    try:
        audio_c = oral.confidence_score
        audio_s = oral.stress_score
    except Exception:
        return

    if audio_c is not None and pc is not None:
        oral.confidence_score = round(
            max(0.0, min(100.0, 0.5 * float(audio_c) + 0.5 * float(pc))),
            2,
        )
    elif pc is not None:
        oral.confidence_score = round(float(pc), 2)

    if audio_s is not None and ps is not None:
        # Combine : les deux signaux montent le « bruit » global sans affirmer cause
        oral.stress_score = round(
            max(0.0, min(100.0, (float(audio_s) ** 2 * 0.5 + float(ps) ** 2 * 0.5) ** 0.5)),
            2,
        )
    elif ps is not None:
        oral.stress_score = round(float(ps), 2)
