from typing import Dict
from .constants import Constants


class QualityPreset:
    encoders = ["av1_nvenc", "hevc_nvenc"]

    _common_params = {
        "preset": "quality",
        "tune": "uhq",
        "qvbr": 0,
        "qp-min": 0,
        "qp-max": "0:150:150",
        "parallel": "auto",
    }

    encoder_params = {
        "av1_nvenc": dict(_common_params),
        "hevc_nvenc": dict(_common_params),
        "svt_av1": {
            "preset": 5,
            "tune": 0,
        },
    }

    @staticmethod
    def get_params(encoder: str) -> Dict:
        return QualityPreset.encoder_params.get(
            encoder, QualityPreset.encoder_params[Constants.DEFAULT_ENCODER]
        ).copy()
