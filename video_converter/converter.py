import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

from .utils import Utils
from .bluray import BluRayDetector
from .transcoder import NVEncTranscoder
from .mediainfo import MediaInfo
from .constants import Constants


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

    def _get_source_bitrate_kbps(self, source_video_info: Dict[str, object]) -> float:
        bit_rate = float(source_video_info.get("bit_rate") or 0)
        duration_seconds = float(source_video_info.get("duration_seconds") or 0)
        size_bytes = float(source_video_info.get("size_bytes") or 0)
        if bit_rate <= 0 and duration_seconds > 0 and size_bytes > 0:
            bit_rate = (size_bytes * 8) / duration_seconds
        if bit_rate <= 0:
            return 0.0
        return bit_rate / 1000.0

    def _create_test_clip(self, input_file: str, duration_seconds: float) -> Tuple[str, bool]:
        if duration_seconds <= 20:
            return input_file, False
        sample_duration = 20.0
        start_time = max(0.0, (duration_seconds - sample_duration) / 2.0)
        temp_dir = Path(__file__).parent.parent / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = temp_dir / f"{Path(input_file).stem}_sample_{timestamp}.mkv"
        ffmpeg_path = Utils.find_tool("ffmpeg")
        cmd = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start_time:.3f}",
            "-t",
            f"{sample_duration:.3f}",
            "-i",
            input_file,
            "-map",
            "0:v:0",
            "-c",
            "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0 or not output_path.exists():
            print("警告: 采样片段截取失败，将使用全片测试")
            output_path.unlink(missing_ok=True)
            return input_file, False
        return str(output_path), True

    def _auto_select_qvbr(
        self,
        input_file: str,
        encoder: str,
        source_video_info: Dict[str, object],
    ) -> Tuple[Optional[int], bool]:
        duration_seconds = float(source_video_info.get("duration_seconds") or 0)
        source_kbps = self._get_source_bitrate_kbps(source_video_info)
        if duration_seconds <= 0:
            return None, False
        test_input, created_clip = self._create_test_clip(input_file, duration_seconds)
        temp_dir = Path(__file__).parent.parent / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        tester = NVEncTranscoder(self.transcoder.nvenc_path, True)
        candidates = [0] + list(range(25, 33))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        previous_candidate = None
        last_candidate = None
        last_vmaf = None
        last_encoded_kbps = None
        try:
            for candidate in candidates:
                temp_output = temp_dir / f"{Path(input_file).stem}_qvbr_{candidate}_{timestamp}.mkv"
                temp_output.unlink(missing_ok=True)
                result = tester.transcode(
                    test_input,
                    str(temp_output),
                    encoder,
                    "",
                    None,
                    None,
                    source_video_info,
                    candidate,
                )
                temp_output.unlink(missing_ok=True)
                if result.get("aborted"):
                    raise KeyboardInterrupt
                if not result.get("success"):
                    continue
                metrics = result.get("quality", {})
                vmaf = metrics.get("vmaf")
                encoded_kbps = metrics.get("encoded_kbps")
                i_avg_qp = metrics.get("i_avg_qp")
                if vmaf is None or encoded_kbps is None:
                    continue
                last_candidate = candidate
                last_vmaf = vmaf
                last_encoded_kbps = encoded_kbps
                if i_avg_qp is not None and i_avg_qp >= 51.0:
                    break
                if vmaf <= 96.5:
                    return previous_candidate if previous_candidate is not None else candidate, False
                previous_candidate = candidate
        finally:
            if created_clip and test_input != input_file:
                Path(test_input).unlink(missing_ok=True)
        if last_vmaf is not None and last_vmaf > 96.5:
            if source_kbps > 0 and last_encoded_kbps is not None:
                if last_encoded_kbps < source_kbps * 0.8:
                    return last_candidate, False
        return None, True

    def _handle_existing_output(self, output_file: str) -> str:
        output_path = Path(output_file)
        if not output_path.exists():
            return "transcode"

        print(f"\n检测到输出文件已存在: {output_file}")
        print(f"文件大小: {output_path.stat().st_size / (1024**2):.2f} MB")
        print(
            f"修改时间: {datetime.fromtimestamp(output_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print("\n请选择处理方式:")
        print("  1. 重新转码 (删除现有文件并重新转码)")
        print("  2. 跳过 (继续处理下一个)")
        print("  3. 放弃 (退出程序)")

        while True:
            choice = input("\n请输入选项 (1-3): ").strip()
            if choice in ["1", "2", "3"]:
                choice_res = ["transcode", "skip", "abort"][int(choice) - 1]
                if choice_res == "transcode":
                    print(f"删除现有文件: {output_file}")
                    output_path.unlink(missing_ok=True)
                return choice_res
            print("无效选项，请重新输入")

    def convert_file(
        self,
        input_file: str,
        output_file: str = None,
        encoder: str = "av1_nvenc",
        qvbr: Optional[int] = None,
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

        handle_choice = self._handle_existing_output(output_file)
        if handle_choice == "abort":
            print(f"转换已中止: {input_file}")
            sys.exit(0)
        elif handle_choice == "skip":
            print(f"已跳过: {input_file}")
            self.media_info.write_nfo(output_file, encoder)
            return True

        if qvbr is None:
            selected_qvbr, should_skip = self._auto_select_qvbr(
                input_file, encoder, source_video_info
            )
            if should_skip:
                print(f"\033[93m该视频无需转码: {input_file}\033[0m")
                return True
            if selected_qvbr is not None:
                qvbr = selected_qvbr

        result = self.transcoder.transcode(
            input_file,
            output_file,
            encoder,
            chapter_file,
            audio_langs,
            subtitle_langs,
            source_video_info,
            qvbr,
        )

        success = result.get("success", False)

        if success:
            print(f"转换完成: {output_file}")
            self.media_info.write_nfo(output_file, encoder)
        elif result.get("aborted", False):
            print(f"转换已中止: {input_file}")
            sys.exit(0)
        else:
            print(f"转换失败: {input_file}")

        return success

    def _process_bluray_directory(
        self,
        directory: str,
        output_dir: str,
        encoder: str,
        qvbr: Optional[int],
    ) -> bool:
        print("开始处理蓝光目录...")
        dir_path = Path(directory)
        bluray_root = dir_path.parent if dir_path.name.upper() == "BDMV" else dir_path
        bdmv_dir = (
            bluray_root / "BDMV" if (bluray_root / "BDMV").exists() else dir_path
        )
        playlist_dir = bdmv_dir / Constants.BLURAY_PATHS["PLAYLIST"]
        stream_dir = bdmv_dir / Constants.BLURAY_PATHS["STREAM"]

        playlist_infos = []
        if playlist_dir.exists() and stream_dir.exists():
            m2ts_size_map = {
                f.name: f.stat().st_size for f in stream_dir.glob("*.m2ts")
            }
            for mpls_file in playlist_dir.glob("*.mpls"):
                info = self.detector.parse_mpls_info(mpls_file)
                if not info:
                    continue
                clip_names = info.get("clip_names", [])
                size_bytes = sum(m2ts_size_map.get(name, 0) for name in clip_names)
                info["mpls_name"] = mpls_file.stem
                info["size_mb"] = size_bytes / (1024 * 1024)
                playlist_infos.append(info)

        if playlist_infos:
            deduped = {}
            for info in playlist_infos:
                key = tuple(info.get("clip_names", []))
                if not key:
                    continue
                existing = deduped.get(key)
                if not existing or info["duration"] > existing["duration"]:
                    deduped[key] = info
            playlist_infos = list(deduped.values())

            max_duration = max(info["duration"] for info in playlist_infos)
            min_duration = 15.0
            min_size_mb = 40.0
            long_duration = 600.0

            candidates = []
            for info in playlist_infos:
                duration = info["duration"]
                size_mb = info["size_mb"]
                chapter_count = info["chapter_count"]
                relative_ok = max_duration > 0 and duration >= max_duration * 0.15
                if duration < min_duration:
                    continue
                if not (
                    size_mb >= min_size_mb
                    or chapter_count > 0
                    or duration >= long_duration
                    or relative_ok
                ):
                    continue
                candidates.append(info)

            if candidates:
                candidates.sort(key=lambda x: x["duration"], reverse=True)
                single_clip_candidates = [
                    info
                    for info in candidates
                    if len(info["clip_names"]) == 1
                    and (stream_dir / info["clip_names"][0]).exists()
                ]
                if single_clip_candidates:
                    input_name = bluray_root.name or datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_path = Utils.get_output_dir(output_dir) / input_name
                    output_path.mkdir(parents=True, exist_ok=True)

                    success_count = 0
                    for idx, info in enumerate(single_clip_candidates, 1):
                        m2ts_name = info["clip_names"][0]
                        m2ts_file = str(stream_dir / m2ts_name)
                        m2ts_stem = Path(m2ts_name).stem
                        output_file = str(output_path / f"{m2ts_stem}.mkv")

                        print(
                            f"[{idx}/{len(single_clip_candidates)}] 正在转换 {m2ts_name}"
                        )

                        if self.convert_file(m2ts_file, output_file, encoder, qvbr):
                            success_count += 1

                    print(
                        f"\n完成: 成功 {success_count}/{len(single_clip_candidates)} 个文件"
                    )
                    return success_count == len(single_clip_candidates)
                print("警告: 未找到可直接处理的单片段播放列表，回退到按文件大小筛选")
            else:
                print("警告: 未找到符合条件的播放列表，回退到按文件大小筛选")
        else:
            print("警告: 未找到可用播放列表，回退到按文件大小筛选")

        large_m2ts_files = self.detector.get_large_m2ts_files(directory)

        if not large_m2ts_files:
            print("错误: 蓝光目录中未找到有价值的 M2TS 文件")
            return False

        print(f"发现 {len(large_m2ts_files)} 个有价值的 M2TS 文件，开始转换")

        input_name = bluray_root.name or datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Utils.get_output_dir(output_dir) / input_name
        output_path.mkdir(parents=True, exist_ok=True)

        success_count = 0
        for idx, (m2ts_file, m2ts_name) in enumerate(large_m2ts_files, 1):
            m2ts_stem = Path(m2ts_name).stem
            output_file = str(output_path / f"{m2ts_stem}.mkv")

            print(f"[{idx}/{len(large_m2ts_files)}] 正在转换 {m2ts_name}")

            if self.convert_file(m2ts_file, output_file, encoder, qvbr):
                success_count += 1

        print(f"\n完成: 成功 {success_count}/{len(large_m2ts_files)} 个文件")
        return success_count == len(large_m2ts_files)

    def _process_single_video_directory(
        self,
        directory: str,
        output_dir: str,
        encoder: str,
        qvbr: Optional[int],
    ) -> bool:
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

            return self.convert_file(input_file, output_file, encoder, qvbr)
        else:
            print("错误: 目录中未找到视频文件")
            return False

    def _process_tv_series_directory(
        self,
        directory: str,
        output_dir: str,
        encoder: str,
        qvbr: Optional[int],
    ) -> bool:
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
            if self.convert_file(str(video_file), output_file, encoder, qvbr):
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

    def convert_directory(
        self,
        directory: str,
        output_dir: str = None,
        encoder: str = "av1_nvenc",
        qvbr: Optional[int] = None,
    ) -> bool:
        dir_path = Path(directory)

        if not dir_path.exists() or not dir_path.is_dir():
            print(f"错误: 目录不存在: {directory}")
            return False
        if dir_path.name == "BDMV" and dir_path.parent.exists():
            if self.detector.is_bluray_directory(str(dir_path.parent)):
                directory = str(dir_path.parent)
                dir_path = Path(directory)

        structure = self.detector.detect_structure(directory)
        print(f"检测到结构类型: {structure}")

        if structure == "bluray":
            return self._process_bluray_directory(directory, output_dir, encoder, qvbr)
        elif structure == "tv_series":
            return self._process_tv_series_directory(directory, output_dir, encoder, qvbr)
        else:
            return self._process_single_video_directory(directory, output_dir, encoder, qvbr)

    def convert(
        self,
        input_path: str,
        output_path: str = None,
        encoder: str = "av1_nvenc",
        qvbr: Optional[int] = None,
    ) -> bool:
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
                return self.convert_file(input_path, output_file, encoder, qvbr)
            return self.convert_file(input_path, output_path, encoder, qvbr)
        elif path.is_dir():
            return self.convert_directory(input_path, output_path, encoder, qvbr)
        else:
            print(f"错误: 路径不存在: {input_path}")
            return False
