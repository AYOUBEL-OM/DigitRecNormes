"""
Analyse visuelle optionnelle YOLOv8 sur les snapshots caméra entretien oral.

Si ``ultralytics`` / les poids ne sont pas disponibles, retourne un fallback sans lever d'exception.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.models.test_oral import TestOral

logger = logging.getLogger(__name__)

CONF_THRESHOLD = 0.45

_YOLO_MODEL = None
_YOLO_LOAD_ERROR: Optional[str] = None

# Poids YOLO : toujours résolu depuis backend/ (pas le cwd du processus).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _yolo_weights_path() -> Path:
    p = _BACKEND_ROOT / "yolov8n.pt"
    if p.is_file():
        return p
    cwd = Path.cwd() / "yolov8n.pt"
    if cwd.is_file():
        return cwd.resolve()
    return p


def _normalize_label(name: str) -> str:
    return (name or "").strip().lower()


def _is_phone_label(label: str) -> bool:
    s = _normalize_label(label)
    if not s:
        return False
    return "phone" in s or s in ("cell phone", "mobile phone")


def _is_person_label(label: str) -> bool:
    return _normalize_label(label) == "person"


def _is_book_label(label: str) -> bool:
    return _normalize_label(label) == "book"


def _is_laptop_label(label: str) -> bool:
    return _normalize_label(label) == "laptop"


def _try_load_yolo():
    global _YOLO_MODEL, _YOLO_LOAD_ERROR
    if _YOLO_LOAD_ERROR is not None:
        return None
    if _YOLO_MODEL is not None:
        return _YOLO_MODEL
    try:
        from ultralytics import YOLO  # lazy : évite ImportError au démarrage
    except ImportError as e:
        _YOLO_LOAD_ERROR = f"YOLOv8 not installed: {e}"
        logger.warning("YOLO PROCTORING: ultralytics unavailable — %s", _YOLO_LOAD_ERROR)
        return None
    try:
        weights = _yolo_weights_path()
        _YOLO_MODEL = YOLO(str(weights))
    except Exception as e:
        _YOLO_LOAD_ERROR = str(e)
        logger.warning("YOLO PROCTORING: model load failed — %s", e)
        return None
    return _YOLO_MODEL


def analyze_snapshot_image(image_path: Path | str) -> dict[str, Any]:
    """
    Analyse une image snapshot ; sortie stable pour ``cheating_flags['yolo']['last_analysis']``.

    Retour attendu (succès) :
        person_count, phone_detected, book_detected, laptop_detected, objects[{label, confidence}]
    En échec import / inférence :
        available: false, reason: str
    """
    path = Path(image_path)
    if not path.is_file():
        out_miss = {"available": False, "reason": f"file_not_found:{path}"}
        print("YOLO PROCTORING START", str(path), flush=True)
        print(
            "YOLO PROCTORING RESULT",
            {
                "available": False,
                "person_count": None,
                "phone_detected": None,
                "objects": [],
                "reason": out_miss["reason"],
            },
            flush=True,
        )
        return out_miss

    model = _try_load_yolo()
    if model is None:
        reason = _YOLO_LOAD_ERROR or "YOLOv8 not installed"
        print("YOLO PROCTORING START", str(path), flush=True)
        print(
            "YOLO PROCTORING RESULT",
            {
                "available": False,
                "person_count": None,
                "phone_detected": None,
                "objects": [],
                "reason": reason,
            },
            flush=True,
        )
        return {"available": False, "reason": reason}

    print("YOLO PROCTORING START", str(path), flush=True)
    logger.info("YOLO PROCTORING START path=%s", path)

    try:
        results = model.predict(source=str(path), imgsz=640, verbose=False)
    except Exception as e:
        logger.exception("YOLO PROCTORING RESULT error=%s", e)
        print(
            "YOLO PROCTORING RESULT",
            {
                "available": False,
                "person_count": None,
                "phone_detected": None,
                "objects": [],
                "reason": str(e),
            },
            flush=True,
        )
        return {"available": False, "reason": str(e)}

    if not results:
        out = _empty_analysis_dict()
        out["available"] = True
        logger.info("YOLO PROCTORING RESULT empty_results path=%s", path)
        print(
            "YOLO PROCTORING RESULT",
            {
                "available": True,
                "person_count": 0,
                "phone_detected": False,
                "objects": [],
                "reason": None,
            },
            flush=True,
        )
        return out

    r0 = results[0]
    names = getattr(r0, "names", None) or {}
    boxes = getattr(r0, "boxes", None)
    objects: list[dict[str, Any]] = []
    person_count = 0
    phone_detected = False
    book_detected = False
    laptop_detected = False

    if boxes is not None and len(boxes):
        for b in boxes:
            try:
                cls_i = int(b.cls[0].item()) if hasattr(b, "cls") else -1
                conf_f = float(b.conf[0].item()) if hasattr(b, "conf") else 0.0
            except Exception:
                continue
            if conf_f < CONF_THRESHOLD:
                continue
            raw_name = str(names.get(cls_i, "") or "")
            label = raw_name or f"class_{cls_i}"
            objects.append({"label": label, "confidence": round(conf_f, 4)})
            ln = _normalize_label(label)
            if _is_person_label(ln) or ln == "person":
                person_count += 1
            elif _is_phone_label(ln):
                phone_detected = True
            elif _is_book_label(ln):
                book_detected = True
            elif _is_laptop_label(ln):
                laptop_detected = True

    out = {
        "person_count": person_count,
        "phone_detected": phone_detected,
        "book_detected": book_detected,
        "laptop_detected": laptop_detected,
        "objects": objects,
        "available": True,
    }
    logger.info(
        "YOLO PROCTORING RESULT path=%s persons=%s phone=%s book=%s laptop=%s n_boxes=%s",
        path,
        person_count,
        phone_detected,
        book_detected,
        laptop_detected,
        len(objects),
    )
    print(
        "YOLO PROCTORING RESULT",
        {
            "available": True,
            "person_count": person_count,
            "phone_detected": phone_detected,
            "objects": objects,
            "reason": None,
        },
        flush=True,
    )
    return out


def _empty_analysis_dict() -> dict[str, Any]:
    return {
        "person_count": 0,
        "phone_detected": False,
        "book_detected": False,
        "laptop_detected": False,
        "objects": [],
    }


def apply_yolo_snapshot_to_flags(
    oral: TestOral,
    flags: dict[str, Any],
    image_path: Path,
) -> None:
    """
    Met à jour ``flags['yolo']`` et les colonnes ``tests_oraux`` (booléens collants).

    Règles :
    - téléphone : ≥1 détection téléphone conf ≥ 0,45 → phone_detected True
    - plusieurs personnes : person_count ≥ 2 (conf ≥ 0,45) sur 2 snapshots consécutifs
    - absence : person_count == 0 sur 3 snapshots consécutifs → presence_anomaly_detected True
    """
    from app.services.oral_proctoring import ensure_oral_proctoring_fields

    ensure_oral_proctoring_fields(oral)

    prev_y = flags.get("yolo")
    prev_y = prev_y if isinstance(prev_y, dict) else {}

    analysis = analyze_snapshot_image(image_path)

    ts = datetime.now(timezone.utc).isoformat()

    if analysis.get("available") is not True:
        reason = str(analysis.get("reason") or "unknown")
        merged = dict(prev_y)
        prev_sig = prev_y.get("signals_latched") if isinstance(prev_y.get("signals_latched"), dict) else {}
        prev_sig = dict(prev_sig)
        if prev_sig.get("phone"):
            prev_sig.setdefault("phone_detected", True)
        if prev_sig.get("multiple_person"):
            prev_sig.setdefault("other_person_detected", True)
        if prev_sig.get("absence"):
            prev_sig.setdefault("presence_anomaly_detected", True)
        merged.update(
            {
                "available": False,
                "reason": reason,
                "last_analysis": {"available": False, "reason": reason},
                "phone_detections": int(prev_y.get("phone_detections") or 0),
                "multiple_person_detections": int(prev_y.get("multiple_person_detections") or 0),
                "absence_detections": int(prev_y.get("absence_detections") or 0),
                "consecutive_multi_person_snapshots": int(
                    prev_y.get("consecutive_multi_person_snapshots") or 0
                ),
                "consecutive_absence_snapshots": int(prev_y.get("consecutive_absence_snapshots") or 0),
                "signals_latched": prev_sig,
                "updated_at": ts,
            }
        )
        flags["yolo"] = merged
        logger.info("YOLO PROCTORING RESULT unavailable oral_id=%s reason=%s", oral.id, reason)
        print(
            "YOLO SNAPSHOT SKIP oral_id=%s reason=%s (YOLO inactif, colonnes SQL inchangées par cette passe)"
            % (oral.id, reason),
            flush=True,
        )
        return

    person_count = int(analysis.get("person_count") or 0)
    objs = analysis.get("objects") if isinstance(analysis.get("objects"), list) else []
    phone_boxes = sum(
        1
        for o in objs
        if isinstance(o, dict)
        and float(o.get("confidence") or 0) >= CONF_THRESHOLD
        and _is_phone_label(str(o.get("label") or ""))
    )
    persons_high = sum(
        1
        for o in objs
        if isinstance(o, dict)
        and float(o.get("confidence") or 0) >= CONF_THRESHOLD
        and (_is_person_label(str(o.get("label") or "")) or _normalize_label(str(o.get("label") or "")) == "person")
    )
    # sécurité : si person_count diverge, prendre le décompte filtré
    pc = max(person_count, persons_high)

    multi_this = 1 if pc >= 2 else 0
    absence_this = 1 if pc == 0 else 0

    streak_m = int(prev_y.get("consecutive_multi_person_snapshots") or 0)
    streak_a = int(prev_y.get("consecutive_absence_snapshots") or 0)

    if pc >= 2:
        streak_m += 1
    else:
        streak_m = 0

    if pc == 0:
        streak_a += 1
    else:
        streak_a = 0

    sig = prev_y.get("signals_latched") if isinstance(prev_y.get("signals_latched"), dict) else {}
    sig = dict(sig)
    phone_hit = bool(analysis.get("phone_detected")) or phone_boxes >= 1

    if phone_hit:
        sig["phone"] = True
        sig["phone_detected"] = True
        if not oral.phone_detected:
            oral.phone_detected = True
            logger.warning("YOLO PHONE DETECTED oral_id=%s", oral.id)

    if streak_m >= 2 and pc >= 2:
        sig["multiple_person"] = True
        sig["other_person_detected"] = True
        if not oral.other_person_detected:
            oral.other_person_detected = True
            logger.warning(
                "YOLO MULTIPLE PERSON DETECTED oral_id=%s streak=%s persons=%s",
                oral.id,
                streak_m,
                pc,
            )

    if streak_a >= 3:
        sig["absence"] = True
        sig["presence_anomaly_detected"] = True
        if not oral.presence_anomaly_detected:
            oral.presence_anomaly_detected = True
            logger.warning("YOLO PRESENCE ABSENCE DETECTED oral_id=%s streak=%s", oral.id, streak_a)

    phone_det_cumulative = int(prev_y.get("phone_detections") or 0) + int(phone_boxes)
    multi_det_cumulative = int(prev_y.get("multiple_person_detections") or 0) + int(multi_this)
    absence_det_cumulative = int(prev_y.get("absence_detections") or 0) + int(absence_this)

    sig["phone_detected"] = bool(sig.get("phone"))
    sig["other_person_detected"] = bool(sig.get("multiple_person"))
    sig["presence_anomaly_detected"] = bool(sig.get("absence"))

    flags["yolo"] = {
        "available": True,
        "last_analysis": analysis,
        "phone_detections": phone_det_cumulative,
        "multiple_person_detections": multi_det_cumulative,
        "absence_detections": absence_det_cumulative,
        "consecutive_multi_person_snapshots": streak_m,
        "consecutive_absence_snapshots": streak_a,
        "signals_latched": sig,
        "updated_at": ts,
    }
