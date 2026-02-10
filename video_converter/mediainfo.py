import json
import math
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional, List

from .utils import Utils


class MediaInfo:
    def _nfo_codec_from_encoder(self, encoder: str) -> str:
        if "av1" in encoder:
            return "av1"
        if "hevc" in encoder or "h265" in encoder:
            return "hevc"
        if "h264" in encoder or "avc" in encoder:
            return "h264"
        return "av1"

    def _ffprobe_path(self) -> Optional[str]:
        candidate = Utils.find_tool("ffprobe")
        if Path(candidate).exists():
            return str(Path(candidate))
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        return None

    def _run_ffprobe(self, media_path: str) -> Optional[Dict]:
        ffprobe_path = self._ffprobe_path()
        if not ffprobe_path:
            return None
        cmd = [
            ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            media_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def extract_source_video_info(self, input_file: str) -> Dict[str, Optional[object]]:
        data = self._run_ffprobe(input_file)
        if not data:
            return {}
        streams = data.get("streams", [])
        format_info = data.get("format", {})
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream_pids = [
            str(stream.get("id"))
            for stream in streams
            if stream.get("codec_type") == "audio" and stream.get("id") is not None
        ]
        subtitle_stream_pids = [
            str(stream.get("id"))
            for stream in streams
            if stream.get("codec_type") == "subtitle" and stream.get("id") is not None
        ]
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        pix_fmt = (video_stream.get("pix_fmt") or "").lower()
        frame_count = None
        nb_frames = video_stream.get("nb_frames")
        fps = self._parse_frame_rate(
            video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate", "")
        )
        if nb_frames and str(nb_frames).isdigit():
            frame_count = int(nb_frames)
        else:
            duration = float(format_info.get("duration") or 0)
            if fps and duration:
                frame_count = int(round(duration * fps))
        bits = None
        for key in ("bits_per_raw_sample", "bits_per_sample"):
            value = video_stream.get(key)
            if value:
                try:
                    bits = int(value)
                except ValueError:
                    bits = None
                if bits:
                    break
        if bits is None and pix_fmt:
            match = re.search(r"p(\d+)", pix_fmt)
            if match:
                bits = int(match.group(1))
        output_depth = None
        if bits is not None:
            output_depth = 10 if bits >= 10 else 8
        output_csp = None
        if "yuva420" in pix_fmt:
            output_csp = "yuva420"
        elif "yuv444" in pix_fmt:
            output_csp = "yuv444"
        elif "yuv422" in pix_fmt:
            output_csp = "yuv422"
        elif "yuv420" in pix_fmt:
            output_csp = "yuv420"
        elif "rgb" in pix_fmt or "gbr" in pix_fmt:
            output_csp = "rgb"
        is_4k = width >= 3840 or height >= 2160
        return {
            "output_depth": output_depth,
            "output_csp": output_csp,
            "is_4k": is_4k,
            "frame_count": frame_count,
            "fps": fps,
            "vmaf_subsample": self._calculate_vmaf_subsample(frame_count),
            "audio_stream_pids": audio_stream_pids,
            "subtitle_stream_pids": subtitle_stream_pids,
        }

    def map_audio_languages_by_pid(
        self,
        audio_langs: Optional[Dict[int, str]],
        audio_pids: Optional[Dict[int, str]],
        audio_stream_pids: Optional[List[str]],
    ) -> Dict[int, str]:
        if not audio_langs or not audio_pids or not audio_stream_pids:
            return {}
        pid_to_lang = {}
        for idx, lang in audio_langs.items():
            pid = audio_pids.get(idx)
            if pid and lang:
                pid_to_lang[pid] = lang
        if not pid_to_lang:
            return {}
        mapped = {}
        for track_index, pid in enumerate(audio_stream_pids):
            lang = pid_to_lang.get(pid)
            if lang:
                mapped[track_index] = lang
        return mapped

    def map_subtitle_languages_by_pid(
        self,
        subtitle_langs: Optional[Dict[int, str]],
        subtitle_pids: Optional[Dict[int, str]],
        subtitle_stream_pids: Optional[List[str]],
    ) -> Dict[int, str]:
        if not subtitle_langs or not subtitle_pids or not subtitle_stream_pids:
            return {}
        pid_to_lang = {}
        for idx, lang in subtitle_langs.items():
            pid = subtitle_pids.get(idx)
            if pid and lang:
                pid_to_lang[pid] = lang
        if not pid_to_lang:
            return {}
        mapped = {}
        for track_index, pid in enumerate(subtitle_stream_pids):
            lang = pid_to_lang.get(pid)
            if lang:
                mapped[track_index] = lang
        return mapped

    def _calculate_vmaf_subsample(self, frame_count: Optional[int]) -> int:
        if not frame_count or frame_count <= 0:
            return 1
        if frame_count <= 3000:
            return 1
        if frame_count <= 10000:
            return 2
        if frame_count <= 30000:
            return 3
        if frame_count <= 60000:
            return 4
        return 5

    def _parse_frame_rate(self, value: str) -> float:
        if not value or value == "0/0":
            return 0.0
        if "/" in value:
            num, den = value.split("/", 1)
            try:
                n = float(num)
                d = float(den)
                return n / d if d else 0.0
            except ValueError:
                return 0.0
        try:
            return float(value)
        except ValueError:
            return 0.0

    def _aspect_ratio(self, width: int, height: int) -> str:
        if not width or not height:
            return ""
        g = math.gcd(width, height)
        return f"{width // g}:{height // g}"

    def _bool_text(self, value: int) -> str:
        return "True" if value == 1 else "False"

    def _subtitle_codec(self, codec_name: str) -> str:
        if not codec_name:
            return ""
        lowered = codec_name.lower()
        if "pgs" in lowered:
            return "PGSSUB"
        return codec_name.upper()

    def _build_nfo_xml(self, data: Dict, encoder: str) -> str:
        streams = data.get("streams", [])
        format_info = data.get("format", {})
        root = ET.Element("movie")
        fileinfo = ET.SubElement(root, "fileinfo")
        streamdetails = ET.SubElement(fileinfo, "streamdetails")
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        video = ET.SubElement(streamdetails, "video")
        vcodec = video_stream.get("codec_name") or self._nfo_codec_from_encoder(encoder)
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        aspect = video_stream.get("display_aspect_ratio") or self._aspect_ratio(width, height)
        fps = self._parse_frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate", ""))
        duration_seconds = float(format_info.get("duration") or 0)
        ET.SubElement(video, "codec").text = vcodec
        ET.SubElement(video, "micodec").text = vcodec
        ET.SubElement(video, "bitrate").text = str(int(video_stream.get("bit_rate") or format_info.get("bit_rate") or 0))
        ET.SubElement(video, "width").text = str(width)
        ET.SubElement(video, "height").text = str(height)
        ET.SubElement(video, "aspect").text = aspect
        ET.SubElement(video, "aspectratio").text = aspect
        ET.SubElement(video, "framerate").text = f"{fps:.6f}" if fps else ""
        ET.SubElement(video, "scantype").text = (video_stream.get("field_order") or "progressive").lower()
        ET.SubElement(video, "default").text = self._bool_text(int(video_stream.get("disposition", {}).get("default", 0)))
        ET.SubElement(video, "forced").text = self._bool_text(int(video_stream.get("disposition", {}).get("forced", 0)))
        ET.SubElement(video, "duration").text = str(int(duration_seconds // 60))
        ET.SubElement(video, "durationinseconds").text = str(int(duration_seconds))
        for stream in streams:
            if stream.get("codec_type") != "audio":
                continue
            audio = ET.SubElement(streamdetails, "audio")
            acodec = stream.get("codec_name", "")
            ET.SubElement(audio, "codec").text = acodec
            ET.SubElement(audio, "micodec").text = acodec
            if stream.get("bit_rate"):
                ET.SubElement(audio, "bitrate").text = str(int(stream.get("bit_rate")))
            ET.SubElement(audio, "scantype").text = "progressive"
            ET.SubElement(audio, "channels").text = str(int(stream.get("channels") or 0))
            ET.SubElement(audio, "samplingrate").text = str(int(stream.get("sample_rate") or 0))
            ET.SubElement(audio, "default").text = self._bool_text(int(stream.get("disposition", {}).get("default", 0)))
            ET.SubElement(audio, "forced").text = self._bool_text(int(stream.get("disposition", {}).get("forced", 0)))
        for stream in streams:
            if stream.get("codec_type") != "subtitle":
                continue
            subtitle = ET.SubElement(streamdetails, "subtitle")
            scodec = self._subtitle_codec(stream.get("codec_name") or "")
            ET.SubElement(subtitle, "codec").text = scodec
            ET.SubElement(subtitle, "language").text = stream.get("tags", {}).get("language", "")
            ET.SubElement(subtitle, "default").text = self._bool_text(int(stream.get("disposition", {}).get("default", 0)))
            ET.SubElement(subtitle, "forced").text = self._bool_text(int(stream.get("disposition", {}).get("forced", 0)))
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        return ET.tostring(root, encoding="unicode")

    def write_nfo(self, output_file: str, encoder: str) -> bool:
        data = self._run_ffprobe(output_file)
        if not data:
            print("错误: 无法获取媒体信息，未生成NFO")
            return False
        xml_text = '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
        xml_text += self._build_nfo_xml(data, encoder)
        nfo_path = Path(output_file).with_suffix(".nfo")
        nfo_path.write_text(xml_text, encoding="utf-8")
        print(f"已生成NFO: {nfo_path}")
        return True
