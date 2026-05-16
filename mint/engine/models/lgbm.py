"""
LightGBM 모델 wrapper — save/load + 캘리브레이션 확률 추론.

설계:
  - 학습된 LightGBM classifier + isotonic calibrator를 함께 직렬화 (joblib)
  - predict_proba: features dict → 캘리브레이션된 P(win) ∈ [0, 1]
  - lightgbm/joblib 미설치 시 import 자체는 실패하지만,
    rule_scanner.py와 main.py는 try/except로 graceful 처리.

파일 위치: mint/data/models/mint_lgbm.joblib (기본)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import numpy as np

from engine.features import FEATURE_NAMES, features_to_array

log = logging.getLogger("mint.lgbm")

DEFAULT_MODEL_PATH = os.environ.get(
    "MINT_MODEL_PATH", "mint/data/models/mint_lgbm.joblib"
)


@dataclass
class TrainedModel:
    """학습 완료된 모델 + 캘리브레이터 + 메타데이터."""
    booster: object                       # lightgbm Booster (predict 가능)
    calibrator: object                    # sklearn IsotonicRegression or None
    feature_names: List[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    trained_at: str = ""
    val_metrics: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)  # target_return, stop_loss 등 학습 시 컨텍스트

    def predict_proba(self, features: dict) -> Optional[float]:
        """단일 row 추론 — 캘리브레이션된 P(win)."""
        try:
            x = features_to_array({k: features[k] for k in self.feature_names})
            raw = float(self.booster.predict(x)[0])
            if self.calibrator is not None:
                return float(self.calibrator.predict(np.array([raw]))[0])
            return raw
        except Exception as e:
            log.debug("predict_proba failed: %s", e)
            return None

    def save(self, path: str = DEFAULT_MODEL_PATH) -> None:
        import joblib  # 지연 import

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "booster": self.booster,
            "calibrator": self.calibrator,
            "feature_names": self.feature_names,
            "trained_at": self.trained_at or datetime.now().isoformat(),
            "val_metrics": self.val_metrics,
            "config": self.config,
        }
        joblib.dump(payload, path)
        log.info("Saved model → %s", path)


def load_model(path: str = DEFAULT_MODEL_PATH) -> Optional[TrainedModel]:
    """모델 로드. 파일 없거나 의존성 미설치 시 None."""
    if not os.path.exists(path):
        return None
    try:
        import joblib
    except ImportError:
        log.warning("joblib 미설치 — pip install joblib lightgbm scikit-learn")
        return None

    try:
        payload = joblib.load(path)
        return TrainedModel(
            booster=payload["booster"],
            calibrator=payload.get("calibrator"),
            feature_names=payload.get("feature_names", list(FEATURE_NAMES)),
            trained_at=payload.get("trained_at", ""),
            val_metrics=payload.get("val_metrics", {}),
            config=payload.get("config", {}),
        )
    except Exception as e:
        log.warning("Model load failed (%s): %s", path, e)
        return None


# 프로세스 단위 캐시 — 매 스캔마다 디스크 IO 안 하도록.
_MODEL_CACHE: dict = {}


def get_cached_model(path: str = DEFAULT_MODEL_PATH) -> Optional[TrainedModel]:
    if path in _MODEL_CACHE:
        return _MODEL_CACHE[path]
    model = load_model(path)
    _MODEL_CACHE[path] = model
    return model


def clear_model_cache() -> None:
    _MODEL_CACHE.clear()
