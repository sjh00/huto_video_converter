from pathlib import Path
from typing import List
from .constants import Constants


class Utils:
    @staticmethod
    def is_iso_file(file_path: str) -> bool:
        return Path(file_path).suffix.lower() == Constants.ISO_EXTENSION

    @staticmethod
    def format_duration(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def format_chapter_time(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:01d}.{millis:03d}"

    @staticmethod
    def format_bitrate(bitrate: int) -> str:
        if bitrate > 0:
            return f"{bitrate / 1000000:.2f} Mbps"
        return "Unknown"

    @staticmethod
    def get_video_files(directory: Path) -> List[Path]:
        video_files = set()
        for ext in Constants.VIDEO_EXTENSIONS:
            video_files.update(directory.glob(f"*{ext}"))
            video_files.update(directory.glob(f"*{ext.upper()}"))
        return list(video_files)

    @staticmethod
    def get_output_dir(output_dir: str = None) -> Path:
        if output_dir:
            return Path(output_dir)
        script_dir = Path(__file__).parent.parent
        output_path = script_dir / "output"
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path

    @staticmethod
    def find_tool(tool_name: str) -> str:
        # script_dir = Path(__file__).parent.parent
        # thirdpart_dir = script_dir / "thirdpart"

        # # Check for .exe extension on Windows
        # candidates = [tool_name]
        # if sys.platform.startswith("win") and not tool_name.lower().endswith(".exe"):
        #     candidates.insert(0, f"{tool_name}.exe")

        # for name in candidates:
        #     tool_path = thirdpart_dir / name
        #     if tool_path.exists():
        #         return str(tool_path)

        return tool_name
