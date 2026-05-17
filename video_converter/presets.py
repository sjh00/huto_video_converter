from typing import Dict
from .constants import Constants


class QualityPreset:
    encoders = ["av1_nvenc", "hevc_nvenc"]

    encoder_params = {
        "av1_nvenc": {
            "preset": "quality",
            "tune": "uhq",
            # "lookahead": 32, # 默认由preset和tune决定
            "bframes": 4, # 默认由preset和tune决定
            "qvbr": 0,
            "ref": 4, # 默认由preset和tune决定
            # "multipass": "2pass-full",
            "aq": None,
            "aq-temporal": None,
            "qp-min": 0,
            # "qp-max": "0:51:51",
            "qp-max": "0:150:150",
            "parallel": "auto",
        },
        "hevc_nvenc": {
            "preset": "quality",
            "tune": "uhq",
            # "lookahead": 32, # 默认由preset和tune决定
            "bframes": 4, # 默认由preset和tune决定
            "qvbr": 0,
            "ref": 4, # 默认由preset和tune决定
            # "multipass": "2pass-full",
            "aq": None,
            "aq-temporal": None,
            "qp-min": 0,
            # "qp-max": "0:51:51",
            "qp-max": "0:150:150",
            "parallel": "auto",
        },
    }

    @staticmethod
    def get_params(encoder: str) -> Dict:
        return QualityPreset.encoder_params.get(
            encoder, QualityPreset.encoder_params[Constants.DEFAULT_ENCODER]
        ).copy()
