import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

MIN_NVENC_VERSION = (9, 33)
SIGINT_EXIT_CODE = 130


class ExternalToolError(Exception):
    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


def find_binary(name: str, explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        return None
    names = [name]
    if sys.platform.startswith("win") and not name.lower().endswith(".exe"):
        names.insert(0, f"{name}.exe")
    for candidate in names:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _run_text(cmd: List[str], timeout: float = 20.0) -> str:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return f"{proc.stdout or ''}\n{proc.stderr or ''}"


def parse_nvenc_version(text: str) -> Optional[Tuple[int, int]]:
    match = re.search(
        r"NVEncC(?:64)?\s*(?:\([^)]+\))?\s*(\d+)\.(\d+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _version_label(version: Tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]:02d}" if version[1] < 10 else f"{version[0]}.{version[1]}"


def ffmpeg_has_encoder(ffmpeg_path: str, encoder: str) -> bool:
    text = _run_text([ffmpeg_path, "-hide_banner", "-encoders"])
    return bool(re.search(rf"\b{re.escape(encoder)}\b", text))


def stop_process(process: subprocess.Popen, grace_seconds: float = 5.0) -> None:
    if process.poll() is not None:
        return
    pid = process.pid
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            capture_output=True,
        )
        try:
            process.wait(timeout=grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
        )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def require_tools(nvenc_path: Optional[str], encoder: str) -> Optional[str]:
    ffmpeg_path = find_binary("ffmpeg")
    if not ffmpeg_path:
        raise ExternalToolError("未找到 ffmpeg，请安装并加入 PATH")
    ffprobe_path = find_binary("ffprobe")
    if not ffprobe_path:
        raise ExternalToolError("未找到 ffprobe，请安装并加入 PATH")

    from .constants import Constants

    if Constants.is_svt_encoder(encoder):
        if not ffmpeg_has_encoder(ffmpeg_path, "libsvtav1"):
            raise ExternalToolError(
                "当前 ffmpeg 未启用 libsvtav1，无法使用 --encoder svt_av1"
            )
        return find_binary("NVEncC64", nvenc_path) or nvenc_path

    resolved = find_binary("NVEncC64", nvenc_path)
    if not resolved:
        hint = "，或使用 --nvenc-path" if not nvenc_path else f": {nvenc_path}"
        raise ExternalToolError(
            f"未找到 NVEncC64{hint}。请安装 9.33 及以上并加入 PATH"
        )
    version_text = _run_text([resolved, "--version"])
    version = parse_nvenc_version(version_text)
    if version is None:
        raise ExternalToolError(
            f"无法解析 NVEncC 版本（{resolved}）。请确认是 9.33 及以上"
        )
    if version < MIN_NVENC_VERSION:
        raise ExternalToolError(
            f"NVEncC 版本 {_version_label(version)} 低于最低要求 "
            f"{_version_label(MIN_NVENC_VERSION)}"
        )
    return resolved
