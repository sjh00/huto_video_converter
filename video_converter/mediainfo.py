import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional, List, Tuple

from .utils import Utils


class MediaInfo:
    def __init__(self):
        self._probe_cache: Dict[Tuple[str, int, int, bool], Optional[Dict]] = {}

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
        if candidate and Path(candidate).exists():
            return candidate
        return None

    def _run_ffprobe(self, media_path: str, include_chapters: bool = False) -> Optional[Dict]:
        path = Path(media_path)
        try:
            stat = path.stat()
        except OSError:
            return None
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size, include_chapters)
        if cache_key in self._probe_cache:
            return self._probe_cache[cache_key]
        ffprobe_path = self._ffprobe_path()
        if not ffprobe_path:
            self._probe_cache[cache_key] = None
            return None
        cmd = [
            ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
        ]
        if include_chapters:
            cmd.append("-show_chapters")
        cmd.append(media_path)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            self._probe_cache[cache_key] = None
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            data = None
        self._probe_cache[cache_key] = data
        return data

    def extract_duration_info(self, media_path: str) -> Dict[str, float]:
        data = self._run_ffprobe(media_path)
        if not data:
            return {}
        streams = data.get("streams", [])
        format_info = data.get("format", {})
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        format_duration = float(format_info.get("duration") or 0)
        video_duration = float(video_stream.get("duration") or 0)
        if not video_duration:
            fps = self._parse_frame_rate(
                video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate", "")
            )
            nb_frames = video_stream.get("nb_frames")
            if nb_frames and str(nb_frames).isdigit() and fps:
                video_duration = float(nb_frames) / fps
        return {
            "format_duration": format_duration,
            "video_duration": video_duration,
        }

    def extract_chapters(self, media_path: str) -> List[Tuple[float, str]]:
        data = self._run_ffprobe(media_path, include_chapters=True)
        if not data:
            return []
        chapters = []
        for idx, chapter in enumerate(data.get("chapters", []), 1):
            start_time = chapter.get("start_time")
            title = chapter.get("tags", {}).get("title") or f"Chapter {idx}"
            if start_time is None:
                continue
            try:
                start_seconds = float(start_time)
            except ValueError:
                continue
            chapters.append((start_seconds, title))
        chapters.sort(key=lambda x: x[0])
        return chapters

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
        duration_seconds = float(format_info.get("duration") or 0)
        if not duration_seconds:
            video_duration = float(video_stream.get("duration") or 0)
            if video_duration:
                duration_seconds = video_duration
        if nb_frames and str(nb_frames).isdigit():
            frame_count = int(nb_frames)
            if fps and not duration_seconds:
                duration_seconds = frame_count / fps
        elif fps and duration_seconds:
            frame_count = int(round(duration_seconds * fps))
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
        color = self._color_from_video_stream(video_stream)
        size_bytes = 0
        size_value = format_info.get("size")
        if size_value:
            try:
                size_bytes = int(float(size_value))
            except ValueError:
                size_bytes = 0
        bit_rate = 0
        tags = video_stream.get("tags") or {}
        for value in (
            video_stream.get("bit_rate"),
            tags.get("BPS"),
            tags.get("BPS-eng"),
            tags.get("bitrate"),
        ):
            if not value:
                continue
            try:
                bit_rate = int(float(value))
            except (TypeError, ValueError):
                bit_rate = 0
            if bit_rate > 0:
                break
        if not bit_rate:
            bytes_value = tags.get("NUMBER_OF_BYTES") or tags.get("NUMBER_OF_BYTES-eng")
            tag_duration = tags.get("DURATION") or tags.get("DURATION-eng")
            duration_for_bps = duration_seconds
            if tag_duration and ":" in str(tag_duration):
                try:
                    parts = str(tag_duration).split(":")
                    duration_for_bps = (
                        float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                    )
                except (TypeError, ValueError, IndexError):
                    duration_for_bps = duration_seconds
            if bytes_value and duration_for_bps > 0:
                try:
                    bit_rate = int(float(bytes_value) * 8 / duration_for_bps)
                except (TypeError, ValueError):
                    bit_rate = 0
        if not bit_rate:
            try:
                bit_rate = int(float(format_info.get("bit_rate") or 0))
            except (TypeError, ValueError):
                bit_rate = 0
        if not bit_rate and size_bytes and duration_seconds:
            bit_rate = int((size_bytes * 8) / duration_seconds)
        return {
            "output_depth": output_depth,
            "output_csp": output_csp,
            "is_4k": is_4k,
            "frame_count": frame_count,
            "fps": fps,
            "vmaf_subsample": self._calculate_vmaf_subsample(frame_count),
            "audio_stream_pids": audio_stream_pids,
            "subtitle_stream_pids": subtitle_stream_pids,
            "duration_seconds": duration_seconds,
            "bit_rate": bit_rate,
            "size_bytes": size_bytes,
            "color_primaries": color.get("color_primaries"),
            "color_transfer": color.get("color_transfer"),
            "color_space": color.get("color_space"),
            "color_range": color.get("color_range"),
            "mastering_display": color.get("mastering_display"),
            "max_cll": color.get("max_cll"),
            "max_fall": color.get("max_fall"),
        }

    def extract_audio_tracks(self, input_file: str) -> List[Dict[str, object]]:
        data = self._run_ffprobe(input_file)
        if not data:
            return []
        tracks: List[Dict[str, object]] = []
        audio_index = 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") != "audio":
                continue
            tags = stream.get("tags", {}) or {}
            language = (tags.get("language") or "").lower()
            disposition = stream.get("disposition", {}) or {}
            is_default = bool(int(disposition.get("default", 0) or 0))
            tracks.append(
                {
                    "index": audio_index + 1,
                    "language": language,
                    "is_default": is_default,
                }
            )
            audio_index += 1
        return tracks

    def map_languages_by_pid(
        self,
        langs: Optional[Dict[int, str]],
        pids: Optional[Dict[int, str]],
        stream_pids: Optional[List[str]],
    ) -> Dict[int, str]:
        if not langs or not pids or not stream_pids:
            return {}
        pid_to_lang = {}
        for idx, lang in langs.items():
            pid = pids.get(idx)
            if pid and lang:
                pid_to_lang[pid] = lang
        if not pid_to_lang:
            return {}
        mapped = {}
        for track_index, pid in enumerate(stream_pids):
            lang = pid_to_lang.get(pid)
            if lang:
                mapped[track_index] = lang
        return mapped

    @staticmethod
    def _norm_color_value(value: Optional[object]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().lower().replace("_", "-")
        if not text or text in {"unknown", "unspecified", "none"}:
            return None
        aliases = {
            "bt2020ncl": "bt2020-ncl",
            "bt2020nc": "bt2020-ncl",
            "bt2020-ncl": "bt2020-ncl",
            "bt2020": "bt2020",
            "smpte2084": "smpte2084",
            "pq": "smpte2084",
            "arib-std-b67": "arib-std-b67",
            "hlg": "arib-std-b67",
            "limited": "tv",
            "mpeg": "tv",
            "tv": "tv",
            "full": "pc",
            "jpeg": "pc",
            "pc": "pc",
        }
        return aliases.get(text, text)

    def _color_from_video_stream(self, video_stream: Dict) -> Dict[str, Optional[object]]:
        color_range = self._norm_color_value(video_stream.get("color_range"))
        mastering = None
        max_cll = None
        max_fall = None
        for side in video_stream.get("side_data_list") or []:
            kind = str(side.get("side_data_type") or "")
            if "Mastering display" in kind:
                parts = []
                for key in (
                    "red_x",
                    "red_y",
                    "green_x",
                    "green_y",
                    "blue_x",
                    "blue_y",
                    "white_x",
                    "white_y",
                    "min_luminance",
                    "max_luminance",
                ):
                    value = side.get(key)
                    if value is not None:
                        parts.append(f"{key}={value}")
                if parts:
                    mastering = ",".join(parts)
            elif "Content light level" in kind:
                if side.get("max_content") is not None:
                    max_cll = str(side.get("max_content"))
                if side.get("max_average") is not None:
                    max_fall = str(side.get("max_average"))
        return {
            "color_primaries": self._norm_color_value(video_stream.get("color_primaries")),
            "color_transfer": self._norm_color_value(video_stream.get("color_transfer")),
            "color_space": self._norm_color_value(video_stream.get("color_space")),
            "color_range": color_range,
            "mastering_display": mastering,
            "max_cll": max_cll,
            "max_fall": max_fall,
        }

    def extract_color_info(self, media_path: str) -> Dict[str, Optional[object]]:
        data = self._run_ffprobe(media_path)
        if not data:
            return {}
        video_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            {},
        )
        return self._color_from_video_stream(video_stream)

    def compare_color_metadata(
        self,
        source_info: Dict[str, object],
        output_file: str,
    ) -> List[str]:
        source_keys = (
            "color_primaries",
            "color_transfer",
            "color_space",
            "color_range",
            "mastering_display",
            "max_cll",
            "max_fall",
        )
        if not any(source_info.get(key) for key in source_keys):
            return []
        output_color = self.extract_color_info(output_file)
        if not output_color:
            return ["成片无法读取色彩信息"]
        labels = {
            "color_primaries": "color_primaries",
            "color_transfer": "color_transfer",
            "color_space": "color_space",
            "color_range": "color_range",
        }
        warnings: List[str] = []
        for key, label in labels.items():
            src = self._norm_color_value(source_info.get(key))
            dst = self._norm_color_value(output_color.get(key))
            if not src:
                continue
            if not dst:
                warnings.append(f"{label} 丢失（源 {src}）")
            elif src != dst:
                warnings.append(f"{label} 不一致（源 {src} → 成片 {dst}）")
        for key, label in (
            ("mastering_display", "mastering display"),
            ("max_cll", "MaxCLL"),
            ("max_fall", "MaxFALL"),
        ):
            src = source_info.get(key)
            dst = output_color.get(key)
            if not src:
                continue
            if not dst:
                warnings.append(f"{label} 丢失")
        return warnings

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

    def _build_fileinfo_element(self, data: Dict, encoder: str) -> ET.Element:
        streams = data.get("streams", [])
        format_info = data.get("format", {})
        fileinfo = ET.Element("fileinfo")
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
            lang = stream.get("tags", {}).get("language", "")
            if lang:
                ET.SubElement(audio, "language").text = lang
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
        return fileinfo

    def _serialize_element(self, element: ET.Element) -> str:
        tree = ET.ElementTree(element)
        ET.indent(tree, space="  ")
        return ET.tostring(element, encoding="unicode")

    def find_sidecar_nfo(self, media_path: str) -> Optional[Path]:
        path = Path(media_path)
        for suffix in (".nfo", ".NFO"):
            candidate = path.with_suffix(suffix)
            if candidate.is_file():
                return candidate
        return None

    def find_directory_nfo(self, directory: str) -> Optional[Path]:
        path = Path(directory)
        if not path.is_dir():
            return None
        for suffix in (".nfo", ".NFO"):
            candidate = path / f"{path.name}{suffix}"
            if candidate.is_file():
                return candidate
        return None

    def _indent_xml_block(self, xml_text: str, indent: str) -> str:
        lines = xml_text.splitlines()
        if not lines:
            return xml_text
        indented = [lines[0]]
        for line in lines[1:]:
            indented.append(f"{indent}{line}" if line else line)
        return "\n".join(indented)

    def _apply_fileinfo_to_nfo_text(self, nfo_text: str, fileinfo_xml: str) -> str:
        pattern = re.compile(r"<fileinfo\b[^>]*>.*?</fileinfo>", re.DOTALL | re.IGNORECASE)
        match = pattern.search(nfo_text)
        if match:
            line_start = nfo_text.rfind("\n", 0, match.start()) + 1
            indent = nfo_text[line_start:match.start()]
            if indent.strip():
                indent = "  "
            replacement = self._indent_xml_block(fileinfo_xml, indent)
            return nfo_text[:match.start()] + replacement + nfo_text[match.end():]
        close_match = re.search(
            r"(\r?\n)?([ \t]*)</([A-Za-z0-9:_\-]+)>\s*$",
            nfo_text,
        )
        if not close_match:
            raise ValueError("源NFO缺少fileinfo且无法定位根节点")
        indent = close_match.group(2) + "  "
        insertion = self._indent_xml_block(fileinfo_xml, indent)
        newline = close_match.group(1) or "\n"
        return nfo_text[:close_match.start()] + newline + indent + insertion + nfo_text[close_match.start():]

    def _reuse_nfo_with_fileinfo(self, source_nfo: Path, fileinfo: ET.Element) -> Tuple[str, str]:
        raw = source_nfo.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        if not text.strip():
            raise ValueError("源NFO为空")
        xml_text = self._apply_fileinfo_to_nfo_text(text, self._serialize_element(fileinfo))
        encoding = "utf-8-sig" if has_bom else "utf-8"
        return xml_text, encoding

    def write_nfo(
        self,
        output_file: str,
        encoder: str,
        input_file: Optional[str] = None,
        nfo_path: Optional[str] = None,
        source_nfo: Optional[str] = None,
    ) -> bool:
        if not Path(output_file).is_file():
            return False
        data = self._run_ffprobe(output_file)
        if not data:
            print("错误: 无法获取媒体信息，未生成NFO")
            return False
        nfo_path = Path(nfo_path) if nfo_path else Path(output_file).with_suffix(".nfo")
        source_nfo_path = Path(source_nfo) if source_nfo else None
        if source_nfo_path is not None and not source_nfo_path.is_file():
            source_nfo_path = None
        if source_nfo_path is None and input_file:
            source_nfo_path = self.find_sidecar_nfo(input_file)
        if source_nfo_path is None:
            return False
        try:
            xml_text, encoding = self._reuse_nfo_with_fileinfo(
                source_nfo_path,
                self._build_fileinfo_element(data, encoder),
            )
            nfo_path.write_text(xml_text, encoding=encoding)
            print(f"已复用源NFO并更新fileinfo: {nfo_path}")
            return True
        except (OSError, UnicodeError, ValueError, ET.ParseError) as exc:
            print(f"警告: 复用源NFO失败，未写入NFO: {exc}")
            return False
