import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

from .utils import Utils
from .bluray import BluRayDetector
from .transcoder import NVEncTranscoder
from .mediainfo import MediaInfo


class VideoConverter:
    def __init__(
        self,
        nvenc_path: str = None,
        enable_quality_eval: bool = False,
    ):
        self.detector = BluRayDetector()
        self.transcoder = NVEncTranscoder(
            nvenc_path,
            enable_quality_eval,
        )
        self.media_info = MediaInfo()

    def _get_default_output_file(self, input_file: str, encoder: str = "av1_nvenc") -> str:
        input_path = Path(input_file)
        output_dir = Utils.get_output_dir()
        return str(output_dir / f"{input_path.stem}.mkv")

    def _extract_bluray_metadata(self, input_path: Path) -> Tuple[
        Optional[List[Tuple[float, str]]],
        Optional[Dict],
        Optional[Dict],
        Optional[Dict],
        Optional[Dict],
    ]:
        chapter_file = ""
        audio_langs = None
        subtitle_langs = None
        audio_pids = None
        subtitle_pids = None

        source_dir = input_path.parent
        if source_dir.name == "STREAM" and (source_dir.parent / "PLAYLIST").exists():
            mpls_file = self.detector.find_mpls_for_m2ts(str(source_dir.parent), input_path.name)
            if mpls_file:
                chapters, chapter_file = self.detector.parse_mpls_chapters(mpls_file)

                clpi_file = source_dir.parent / "CLIPINF" / (input_path.stem + ".clpi")

                if clpi_file.exists():
                    kind = "CLPI"
                    stream_info = self.detector.parse_clpi_stream_info(clpi_file)
                    audio_langs = stream_info.get("audio_languages", {})
                    subtitle_langs = stream_info.get("subtitle_languages", {})
                    audio_pids = stream_info.get("audio_pids", {})
                    subtitle_pids = stream_info.get("subtitle_pids", {})
                else:
                    kind = "MPLS"
                    stream_info = self.detector.parse_mpls_stream_info(mpls_file)
                    audio_langs = stream_info.get("audio_languages", {})
                    subtitle_langs = stream_info.get("subtitle_languages", {})

                if chapter_file or audio_langs or subtitle_langs:
                    print(
                        f"应用 {kind} 信息(章节: {len(chapters)}, 音轨: {len(audio_langs)}, 字幕: {len(subtitle_langs)})..."
                    )

        return chapter_file, audio_langs, subtitle_langs, audio_pids, subtitle_pids

    def convert_file(
        self,
        input_file: str,
        output_file: str = None,
        encoder: str = "av1_nvenc",
    ) -> bool:
        input_path = Path(input_file)

        if not input_path.exists():
            print(f"错误: 输入文件不存在: {input_file}")
            return False

        if output_file is None:
            output_file = self._get_default_output_file(input_file, encoder)

        print(f"开始转换: {input_file}")
        print(f"输出文件: {output_file}")

        chapter_file, audio_langs, subtitle_langs, audio_pids, subtitle_pids = self._extract_bluray_metadata(input_path)
        source_video_info = self.media_info.extract_source_video_info(input_file)
        if audio_langs and audio_pids:
            mapped_langs = self.media_info.map_audio_languages_by_pid(
                audio_langs,
                audio_pids,
                source_video_info.get("audio_stream_pids"),
            )
            if mapped_langs:
                audio_langs = mapped_langs
        if subtitle_langs and subtitle_pids:
            mapped_langs = self.media_info.map_subtitle_languages_by_pid(
                subtitle_langs,
                subtitle_pids,
                source_video_info.get("subtitle_stream_pids"),
            )
            if mapped_langs:
                subtitle_langs = mapped_langs

        result = self.transcoder.transcode(
            input_file,
            output_file,
            encoder,
            chapter_file,
            audio_langs,
            subtitle_langs,
            source_video_info,
        )

        success = result.get("success", False)

        if success:
            print(f"转换完成: {output_file}")
            self.media_info.write_nfo(output_file, encoder)
        elif result.get("aborted", False):
            print(f"转换已中止: {input_file}")
            sys.exit(0)
        elif result.get("skipped", False):
            print(f"已跳过: {input_file}")
            success = True
            self.media_info.write_nfo(output_file, encoder)
        else:
            print(f"转换失败: {input_file}")

        return success

    def _process_bluray_directory(self, directory: str, output_dir: str, encoder: str) -> bool:
        print("开始处理蓝光目录...")
        large_m2ts_files = self.detector.get_large_m2ts_files(directory)

        if not large_m2ts_files:
            print("错误: 蓝光目录中未找到大于 500MB 的 M2TS 文件")
            return False

        print(f"发现 {len(large_m2ts_files)} 个 M2TS 文件(>=500MB)，开始转换")

        dir_path = Path(directory)
        input_name = dir_path.name or datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Utils.get_output_dir(output_dir) / input_name
        output_path.mkdir(parents=True, exist_ok=True)

        ext_suffix = self._get_output_suffix(encoder)

        success_count = 0
        for idx, (m2ts_file, m2ts_name) in enumerate(large_m2ts_files, 1):
            m2ts_stem = Path(m2ts_name).stem
            output_file = str(output_path / f"{input_name}_{m2ts_stem}{ext_suffix}.mkv")

            print(f"[{idx}/{len(large_m2ts_files)}] 正在转换 {m2ts_name}")

            if self.convert_file(m2ts_file, output_file, encoder):
                success_count += 1

        print(f"\n完成: 成功 {success_count}/{len(large_m2ts_files)} 个文件")
        return success_count == len(large_m2ts_files)

    def _process_single_video_directory(self, directory: str, output_dir: str, encoder: str) -> bool:
        print("开始处理单视频目录...")
        dir_path = Path(directory)
        video_files = Utils.get_video_files(dir_path)

        if len(video_files) > 1:
            print("错误: 目录下包含多个视频文件，仅支持单影片转换")
            return False
        elif len(video_files) == 1:
            input_file = str(video_files[0])
            input_name = dir_path.name
            output_path = Utils.get_output_dir(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            output_file = str(output_path / f"{input_name}.mkv")

            return self.convert_file(input_file, output_file, encoder)
        else:
            print("错误: 目录中未找到视频文件")
            return False

    def _process_tv_series_directory(self, directory: str, output_dir: str, encoder: str) -> bool:
        print("开始处理电视剧目录...")
        dir_path = Path(directory)
        video_files = Utils.get_video_files(dir_path)

        if not video_files:
            print("错误: 目录中未找到视频文件")
            return False

        output_base = Utils.get_output_dir(output_dir)
        output_path = output_base / dir_path.name
        output_path.mkdir(parents=True, exist_ok=True)

        success_count = 0
        for idx, video_file in enumerate(sorted(video_files), 1):
            output_file = str(output_path / f"{dir_path.name}_{video_file.stem}.mkv")
            print(f"[{idx}/{len(video_files)}] 正在转换 {video_file.name}")
            if self.convert_file(str(video_file), output_file, encoder):
                success_count += 1

        print(f"\n完成: 成功 {success_count}/{len(video_files)} 个文件")
        return success_count == len(video_files)

    def _get_bluray_root_for_file(self, input_path: Path) -> Optional[Path]:
        if input_path.parent.name != "STREAM":
            return None
        bdmv_dir = input_path.parent.parent
        if bdmv_dir.name == "BDMV" and bdmv_dir.parent.exists():
            candidate = bdmv_dir.parent
            if self.detector.is_bluray_directory(str(candidate)):
                return candidate
        if self.detector.is_bluray_directory(str(bdmv_dir)):
            return bdmv_dir
        return None

    def _resolve_bluray_output_file(self, input_path: Path, output_dir: str, encoder: str) -> str:
        bluray_root = self._get_bluray_root_for_file(input_path)
        output_base = Utils.get_output_dir(output_dir)
        bluray_name = bluray_root.name if bluray_root else input_path.parent.name
        output_path = output_base / bluray_name if bluray_name else output_base
        output_path.mkdir(parents=True, exist_ok=True)

        return str(output_path / f"{input_path.stem}.mkv")

    def convert_directory(self, directory: str, output_dir: str = None, encoder: str = "av1_nvenc") -> bool:
        dir_path = Path(directory)

        if not dir_path.exists() or not dir_path.is_dir():
            print(f"错误: 目录不存在: {directory}")
            return False

        structure = self.detector.detect_structure(directory)
        print(f"检测到结构类型: {structure}")

        if structure == "bluray":
            print(
                "错误: 当前不支持蓝光文件夹批量处理。请进入 STREAM 目录选择具体视频文件并使用绝对路径。"
            )
            print("示例: python video_converter.py D:\\BDMV\\STREAM\\00001.m2ts")
            return False
        elif structure == "tv_series":
            return self._process_tv_series_directory(directory, output_dir, encoder)
        else:
            return self._process_single_video_directory(directory, output_dir, encoder)

    def convert(self, input_path: str, output_path: str = None, encoder: str = "av1_nvenc") -> bool:
        path = Path(input_path)

        if not path.exists():
            print(f"错误: 路径不存在: {input_path}")
            return False

        if Utils.is_iso_file(input_path):
            print(
                "ISO 文件：请先挂载镜像后指定光驱目录，按蓝光目录结构处理，或直接指定具体视频文件"
            )
            return False

        elif path.is_file():
            bluray_root = self._get_bluray_root_for_file(path)
            if bluray_root:
                output_dir = output_path
                if output_path and Path(output_path).suffix:
                    output_dir = str(Path(output_path).parent)
                output_file = self._resolve_bluray_output_file(path, output_dir, encoder)
                return self.convert_file(input_path, output_file, encoder)
            return self.convert_file(input_path, output_path, encoder)
        elif path.is_dir():
            return self.convert_directory(input_path, output_path, encoder)
        else:
            print(f"错误: 路径不存在: {input_path}")
            return False
