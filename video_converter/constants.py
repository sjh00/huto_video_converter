class Constants:
    VIDEO_EXTENSIONS = [".mkv", ".mp4", ".ts", ".m2ts", ".avi", ".mov", ".mpeg", ".mpg"]
    ISO_EXTENSION = ".iso"
    MIN_BLURAY_FILE_SIZE_MB = 100

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
