import tempfile
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from .constants import Constants
from .utils import Utils
from .mpls import MPLS


class BluRayDetector:
    @staticmethod
    def is_bluray_directory(directory: str) -> bool:
        path = Path(directory)
        if not path.is_dir():
            return False

        for required_file in Constants.BLURAY_REQUIRED_PATHS:
            if not (path / required_file).exists():
                return False

        stream_dir = path / Constants.BLURAY_PATHS["STREAM"]
        m2ts_files = list(stream_dir.glob("*.m2ts"))
        return len(m2ts_files) > 0

    @staticmethod
    def _parse_mpls(mpls_path: Path):
        try:
            return MPLS(str(mpls_path))
        except Exception as e:
            print(f"警告: 解析 MPLS 文件失败: {e}")
            return None

    @staticmethod
    def parse_mpls_chapters(mpls_path: Path) -> Tuple[List[Tuple[float, str]], str]:
        chapters = []
        mpls = BluRayDetector._parse_mpls(mpls_path)
        if not mpls or not hasattr(mpls, "PlayListMarks") or not mpls.PlayListMarks:
            return [], ""

        play_list_marks = mpls.PlayListMarks.get("PlayListMarks", [])
        for mark in play_list_marks:
            if mark.get("MarkType", 0) == Constants.MARK_TYPE_CHAPTER:
                timestamp_seconds = mark.get("MarkTimeStamp", 0) / 45000.0
                chapters.append((timestamp_seconds, f"Chapter {len(chapters) + 1}"))
        if chapters:
            chapter_file = BluRayDetector._write_chapters_file(chapters)
        else:
            chapter_file = ""
        return chapters, chapter_file

    @staticmethod
    def _extract_language_info(stream_entries: List) -> Dict[int, str]:
        langs = {}
        for i, entry in enumerate(stream_entries):
            if isinstance(entry, dict):
                stream_attrs = entry.get("StreamAttributes", {})
                lang_code = stream_attrs.get("LanguageCode", "").strip()
                if lang_code and lang_code != "und":
                    langs[i] = lang_code
        return langs

    @staticmethod
    def parse_mpls_stream_info(mpls_path: Path) -> Dict:
        stream_info = {
            "audio_languages": {},
            "subtitle_languages": {},
            "video_count": 0,
            "audio_count": 0,
            "subtitle_count": 0,
        }
        mpls = BluRayDetector._parse_mpls(mpls_path)
        if not mpls or not hasattr(mpls, "PlayList") or not mpls.PlayList:
            return stream_info

        play_items = mpls.PlayList.get("PlayItems", [])
        for play_item in play_items:
            stn_table = play_item.get("STNTable", {})

            video_entries = stn_table.get("PrimaryVideoStreamEntries", [])
            audio_entries = stn_table.get("PrimaryAudioStreamEntries", [])
            subtitle_entries = stn_table.get("PrimaryPGStreamEntries", [])

            stream_info["video_count"] = max(stream_info["video_count"], len(video_entries))
            stream_info["audio_count"] = max(stream_info["audio_count"], len(audio_entries))
            stream_info["subtitle_count"] = max(
                stream_info["subtitle_count"], len(subtitle_entries)
            )

            stream_info["audio_languages"].update(
                BluRayDetector._extract_language_info(audio_entries)
            )
            stream_info["subtitle_languages"].update(
                BluRayDetector._extract_language_info(subtitle_entries)
            )

        return stream_info

    @staticmethod
    def parse_mpls_info(mpls_path: Path) -> Optional[Dict]:
        mpls = BluRayDetector._parse_mpls(mpls_path)
        if not mpls or not hasattr(mpls, "PlayList") or not mpls.PlayList:
            return None
        play_items = mpls.PlayList.get("PlayItems", [])
        clip_names = []
        duration_seconds = 0.0
        for play_item in play_items:
            clip_name = play_item.get("ClipInformationFileName")
            if clip_name:
                if not clip_name.endswith(".m2ts"):
                    clip_name += ".m2ts"
                clip_names.append(clip_name)
            in_time = play_item.get("INTime", 0)
            out_time = play_item.get("OUTTime", 0)
            if out_time > in_time:
                duration_seconds += (out_time - in_time) / 45000.0
        chapter_count = 0
        play_list_marks = {}
        if hasattr(mpls, "PlayListMarks") and mpls.PlayListMarks:
            play_list_marks = mpls.PlayListMarks.get("PlayListMarks", [])
        for mark in play_list_marks:
            if mark.get("MarkType", 0) == Constants.MARK_TYPE_CHAPTER:
                chapter_count += 1
        return {
            "duration": duration_seconds,
            "clip_names": clip_names,
            "chapter_count": chapter_count,
            "play_item_count": len(play_items),
        }

    @staticmethod
    def parse_mpls_audio_languages(mpls_path: Path) -> Dict[int, str]:
        return BluRayDetector.parse_mpls_stream_info(mpls_path).get("audio_languages", {})

    @staticmethod
    def _find_pes_packets(data: bytes) -> List[Tuple[int, int]]:
        pes_packets = []
        for i in range(len(data) - 10):
            if data[i] == 0x00 and data[i + 1] == 0x00 and data[i + 2] == 0x01:
                stream_id = data[i + 3]
                if stream_id in Constants.PES_STREAM_IDS:
                    pes_packets.append((i, stream_id))
        return pes_packets

    @staticmethod
    def _find_ts_packet_for_pes(data: bytes, pes_pos: int) -> Optional[int]:
        ts_pos = pes_pos
        while ts_pos > 0:
            if data[ts_pos] == Constants.TS_SYNC_BYTE:
                if ts_pos + 188 <= len(data):
                    return ts_pos
                break
            ts_pos -= 1
        return None

    @staticmethod
    def parse_m2ts_pesid(m2ts_path: Path) -> Dict[str, str]:
        pesid_map = {}
        try:
            with open(m2ts_path, "rb") as f:
                data = f.read(2000000)

            for pes_pos, stream_id in BluRayDetector._find_pes_packets(data):
                ts_pos = BluRayDetector._find_ts_packet_for_pes(data, pes_pos)
                if ts_pos is not None:
                    pid = ((data[ts_pos + 1] & 0x1F) << 8) | data[ts_pos + 2]
                    if pid not in pesid_map:
                        pesid_map[f"0x{pid:04x}"] = f"0x{stream_id:02x}"
        except Exception as e:
            print(f"警告: 解析 M2TS PESID 失败: {e}")

        return pesid_map

    @staticmethod
    def _parse_clpi_streams(
        data: bytes, stream_type: int, lang_offset: int
    ) -> Tuple[int, Dict[int, str], Dict[int, str]]:
        count = 0
        languages = {}
        pids = {}
        pos = 0

        while True:
            pos = data.find(stream_type, pos)
            if pos == -1:
                break

            if pos >= 4 and pos + 8 <= len(data):
                prefix = data[pos - 4 : pos]
                if prefix == b"\x00\x00\x00\x00":
                    if data[pos + 2] == 0x15:
                        lang_pos = pos + lang_offset
                        if lang_pos + 3 <= len(data):
                            lang_code = data[lang_pos : lang_pos + 3].decode(
                                "ascii", errors="ignore"
                            )
                            if lang_code and lang_code.isalpha():
                                pid = (data[pos] << 8) | data[pos + 1]
                                languages[count] = lang_code
                                pids[count] = f"0x{pid:04x}"
                                count += 1
            pos += 1

        return count, languages, pids

    @staticmethod
    def parse_clpi_stream_info(clpi_path: Path) -> Dict:
        stream_info = {
            "audio_languages": {},
            "subtitle_languages": {},
            "audio_pids": {},
            "subtitle_pids": {},
            "audio_pesids": {},
            "video_count": 0,
            "audio_count": 0,
            "subtitle_count": 0,
        }

        if not clpi_path.exists():
            print(f"警告: 未找到 CLPI 文件: {clpi_path}")
            return stream_info

        try:
            with open(clpi_path, "rb") as f:
                data = f.read()

                audio_count, audio_langs, audio_pids = BluRayDetector._parse_clpi_streams(
                    data, Constants.STREAM_TYPE_AUDIO, 5
                )
                stream_info["audio_count"] = audio_count
                stream_info["audio_languages"] = audio_langs
                stream_info["audio_pids"] = audio_pids

                sub_count, sub_langs, sub_pids = BluRayDetector._parse_clpi_streams(
                    data, Constants.STREAM_TYPE_SUBTITLE, 4
                )
                stream_info["subtitle_count"] = sub_count
                stream_info["subtitle_languages"] = sub_langs
                stream_info["subtitle_pids"] = sub_pids

            return stream_info
        except Exception as e:
            print(f"警告: 解析 CLPI 流信息失败: {e}")
            return stream_info

    @staticmethod
    def parse_mpls_file(mpls_path: Path) -> List[str]:
        mpls = BluRayDetector._parse_mpls(mpls_path)
        if not mpls or not hasattr(mpls, "PlayList") or not mpls.PlayList:
            return []

        m2ts_names = []
        for play_item in mpls.PlayList["PlayItems"]:
            clip_name = play_item["ClipInformationFileName"]
            if not clip_name.endswith(".m2ts"):
                clip_name += ".m2ts"
            m2ts_names.append(clip_name)
        return m2ts_names

    @staticmethod
    def get_main_movie_file(directory: str) -> Optional[str]:
        path = Path(directory)
        stream_dir = path / Constants.BLURAY_PATHS["STREAM"]
        if not stream_dir.exists():
            return None

        m2ts_files = list(stream_dir.glob("*.m2ts"))
        if not m2ts_files:
            return None

        m2ts_files.sort(key=lambda x: x.stat().st_size, reverse=True)
        return str(m2ts_files[0])

    @staticmethod
    def get_large_m2ts_files(directory: str, min_size_mb: int = None) -> List[Tuple[str, str]]:
        if min_size_mb is None:
            min_size_mb = Constants.MIN_BLURAY_FILE_SIZE_MB
        path = Path(directory)
        stream_dir = path / Constants.BLURAY_PATHS["STREAM"]
        if not stream_dir.exists():
            return []

        m2ts_files = list(stream_dir.glob("*.m2ts"))
        if not m2ts_files:
            return []

        min_size_bytes = min_size_mb * 1024 * 1024
        large_files = [(str(f), f.name) for f in m2ts_files if f.stat().st_size >= min_size_bytes]
        large_files.sort(key=lambda x: Path(x[0]).stat().st_size, reverse=True)
        return large_files

    @staticmethod
    def find_mpls_for_m2ts(directory: str, m2ts_name: str) -> Optional[Path]:
        path = Path(directory)
        playlist_dir = path / Constants.BLURAY_PATHS["PLAYLIST"]

        if not playlist_dir.exists():
            return None

        for mpls_file in playlist_dir.glob("*.mpls"):
            m2ts_names = BluRayDetector.parse_mpls_file(mpls_file)
            if m2ts_name in m2ts_names:
                return mpls_file
        return None

    @staticmethod
    def _write_chapters_file(chapters: List[Tuple[float, str]]) -> str:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".xml", delete=False) as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write("<Chapters>\n")
            f.write("  <EditionEntry>\n")
            for timestamp, name in chapters:
                f.write("    <ChapterAtom>\n")
                f.write(f"      <ChapterTimeStart>{Utils.format_chapter_time(timestamp)}</ChapterTimeStart>\n")
                f.write("      <ChapterDisplay>\n")
                f.write(f"        <ChapterString>{name}</ChapterString>\n")
                f.write("        <ChapterLanguage>eng</ChapterLanguage>\n")
                f.write("      </ChapterDisplay>\n")
                f.write("    </ChapterAtom>\n")
            f.write("  </EditionEntry>\n")
            f.write("</Chapters>\n")
            return f.name

    @staticmethod
    def is_tv_series(directory: str) -> bool:
        path = Path(directory)
        if not path.is_dir():
            return False
        return len(Utils.get_video_files(path)) > 1

    @staticmethod
    def detect_structure(directory: str) -> str:
        if BluRayDetector.is_bluray_directory(directory):
            return "bluray"
        if BluRayDetector.is_tv_series(directory):
            return "tv_series"
        return "single_video"
