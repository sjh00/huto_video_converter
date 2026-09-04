import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional
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
    def display_path(full_path: str, roots: Optional[List[str]] = None) -> str:
        full_n = os.path.normpath(full_path)
        best = None
        for root in roots or []:
            root_n = os.path.normpath(root)
            full_l = os.path.normcase(full_n)
            root_l = os.path.normcase(root_n)
            if full_l == root_l:
                candidate = os.path.basename(root_n)
            elif full_l.startswith(root_l.rstrip("\\/") + os.sep):
                candidate = full_n[len(root_n):].lstrip("\\/")
            else:
                continue
            if best is None or len(candidate) < len(best):
                best = candidate
        return best or os.path.basename(full_n)

    @staticmethod
    def get_video_files(directory: Path) -> List[Path]:
        video_files = set()
        for ext in Constants.VIDEO_EXTENSIONS:
            video_files.update(directory.glob(f"*{ext}"))
            video_files.update(directory.glob(f"*{ext.upper()}"))
        return list(video_files)

    @staticmethod
    def get_output_dir(output_dir: Optional[str] = None) -> Path:
        if output_dir:
            return Path(output_dir)
        script_dir = Path(__file__).parent.parent
        output_path = script_dir / "output"
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path

    @staticmethod
    def find_tool(tool_name: str) -> str:
        names = [tool_name]
        if sys.platform.startswith("win") and not tool_name.lower().endswith(".exe"):
            names.insert(0, f"{tool_name}.exe")
        for name in names:
            resolved = shutil.which(name)
            if resolved:
                return resolved
        return tool_name
