from typing import Dict
from .constants import Constants


class QualityPreset:
    encoders = ["av1_nvenc", "hevc_nvenc"]

    encoder_params = {
        "av1_nvenc": {
            "preset": "quality",
            "tune": "uhq",
            "lookahead": 32, # 默认由preset和tune决定
            "bframes": 4, # 默认由preset和tune决定
            # "qvbr": 28, # 默认自动
            # "ref": 4, # 默认由preset和tune决定
            # "multipass": "2pass-full",
            "aq": None,
            "aq-temporal": None,
            "qp-max": "48:51:53",
            "parallel": "auto",
        },
        "hevc_nvenc": {
            "preset": "quality",
            "tune": "uhq",
            "lookahead": 32, # 默认由preset和tune决定
            "bframes": 4, # 默认由preset和tune决定
            # "qvbr": 28, # 默认自动
            # "ref": 4, # 默认由preset和tune决定
            # "multipass": "2pass-full",
            "aq": None,
            "aq-temporal": None,
            "qp-max": "48:51:53",
            "parallel": "auto",
        },
    }

    @staticmethod
    def get_params(encoder: str) -> Dict:
        return QualityPreset.encoder_params.get(
            encoder, QualityPreset.encoder_params[Constants.DEFAULT_ENCODER]
        ).copy()
