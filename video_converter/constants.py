class Constants:
    VIDEO_EXTENSIONS = [".mkv", ".mp4", ".ts", ".m2ts", ".avi", ".mov", ".mpeg", ".mpg"]
    ISO_EXTENSION = ".iso"
    MIN_BLURAY_FILE_SIZE_MB = 40
    SEASON_CONSECUTIVE_SKIP = 3

    BLURAY_REQUIRED_PATHS = ["BDMV", "BDMV/STREAM"]
    BLURAY_PATHS = {"STREAM": "BDMV/STREAM", "PLAYLIST": "PLAYLIST", "CLIPINF": "CLIPINF"}

    MARK_TYPE_CHAPTER = 0x01

    STREAM_TYPE_AUDIO = 0x11
    STREAM_TYPE_SUBTITLE = 0x12

    DEFAULT_ENCODER = "av1_nvenc"
    SVT_AV1 = "svt_av1"

    ENCODER_NAMES = {
        "av1_nvenc": "NVIDIA NVENC AV1 (NVEncC)",
        "hevc_nvenc": "NVIDIA NVENC HEVC (NVEncC)",
        "svt_av1": "SVT-AV1 (软件)",
    }

    @staticmethod
    def is_svt_encoder(encoder: str) -> bool:
        return (encoder or "").lower() in ("svt_av1", "libsvtav1", "av1_svt")

    @staticmethod
    def quality_label(encoder: str) -> str:
        return "CRF" if Constants.is_svt_encoder(encoder) else "QVBR"

    @staticmethod
    def quality_search(keep_grain: bool, encoder: str) -> dict:
        # 目标取 certification 示例分，最低取 vmaf_floor / ssimu2_floor。
        cfg = {
            "target_vmaf": 97.3,
            "lowest_vmaf": 93.0,
            "target_ssimu2": 87.1,
            "lowest_ssimu2": 80.0,
            "size_limit": 0.85 if keep_grain else 0.80,
            "low": 10 if keep_grain else 18,
            "high": 26 if keep_grain else 30,
        }
        if Constants.is_svt_encoder(encoder):
            cfg["low"], cfg["high"] = (18, 32) if keep_grain else (24, 38)
        return cfg
