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
        no_qp_max_limit: bool = False,
        keep_default_zh_audio: bool = False,
        keep_grain: bool = True,
    ):
        self.detector = BluRayDetector()
        self.transcoder = NVEncTranscoder(
            nvenc_path,
            enable_quality_eval,
            no_qp_max_limit,
            keep_grain,
        )
        self.media_info = MediaInfo()
        self.skip_count = 0
        self.skipped_files: List[str] = []
        self.always_skip_existing = False
        self.in_series_batch = False
        self.no_qp_max_limit = no_qp_max_limit
        self.keep_default_zh_audio = keep_default_zh_audio
        self.keep_grain = keep_grain

    def _temp_dir(self) -> Path:
        temp_dir = Path(__file__).parent.parent / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def _run_ffmpeg(self, args: List[str], output_path: Path) -> bool:
        cmd = [
            Utils.find_tool("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *args,
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0 or not output_path.exists():
            output_path.unlink(missing_ok=True)
            return False
        return True

    @staticmethod
    def _is_duration_mismatch(format_duration: float, video_duration: float) -> bool:
        if not format_duration or not video_duration:
            return False
        return (
            format_duration - video_duration >= 60
            and format_duration / video_duration >= 1.05
        )

    def _record_skip(self, input_file: str, output_file: str, encoder: str) -> None:
        self.skip_count += 1
        self.skipped_files.append(input_file)
        if Path(output_file).is_file():
            self.media_info.write_nfo(output_file, encoder, input_file)

    def _abort_conversion(self, input_file: str) -> None:
        print(f"转换已中止: {input_file}")
        sys.exit(0)

    def _select_audio_track_ids(self, input_file: str) -> Optional[List[int]]:
        if not self.keep_default_zh_audio:
            return None
        tracks = self.media_info.extract_audio_tracks(input_file)
        if not tracks:
            return None
        zh_langs = {"chi", "zho", "zh", "chs", "cht", "cmn", "cn", "zh-cn", "zh-hans", "zh-hant"}
        selected = []
        default_tracks = [t for t in tracks if t.get("is_default")]
        if default_tracks:
            selected.extend(t.get("index") for t in default_tracks if t.get("index"))
        else:
            first_index = tracks[0].get("index")
            if first_index:
                selected.append(first_index)
        for t in tracks:
            lang = str(t.get("language") or "").lower()
            if lang in zh_langs:
                idx = t.get("index")
                if idx and idx not in selected:
                    selected.append(idx)
        return selected or None

    def _get_default_output_file(self, input_file: str) -> str:
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
        if source_dir.name.upper() == "STREAM" and (source_dir.parent / "PLAYLIST").exists():
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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self._temp_dir() / f"{Path(input_file).stem}_sample_{timestamp}.mkv"
        ok = self._run_ffmpeg(
            [
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
            ],
            output_path,
        )
        if not ok:
            print("警告: 采样片段截取失败，将使用全片测试")
            return input_file, False
        return str(output_path), True

    def test_encode(
        self,
        input_file: str,
        output_path: Optional[str],
        encoder: str = "av1_nvenc",
        qvbr: Optional[int] = None,
    ) -> bool:
        input_path = Path(input_file)
        if not input_path.exists() or not input_path.is_file():
            print(f"错误: 输入文件不存在: {input_file}")
            return False

        if output_path:
            output_target = Path(output_path)
            if output_target.suffix:
                output_file = str(output_target)
            else:
                output_file = str(output_target / f"{input_path.stem}_test.mkv")
        else:
            output_dir = Utils.get_output_dir()
            output_file = str(output_dir / f"{input_path.stem}_test.mkv")

        source_video_info = self.media_info.extract_source_video_info(input_file)
        audio_track_ids = self._select_audio_track_ids(input_file)
        duration_seconds = float(source_video_info.get("duration_seconds") or 0)
        test_input, created_clip = self._create_test_clip(input_file, duration_seconds)

        handle_choice = self._handle_existing_output(output_file)
        if handle_choice == "abort":
            self._abort_conversion(input_file)
        elif handle_choice == "skip":
            print(f"已跳过: {input_file}")
            if created_clip and test_input != input_file:
                Path(test_input).unlink(missing_ok=True)
            return True

        result = self.transcoder.transcode(
            test_input,
            output_file,
            encoder,
            "",
            None,
            None,
            source_video_info,
            qvbr,
            audio_track_ids,
        )

        if created_clip and test_input != input_file:
            Path(test_input).unlink(missing_ok=True)

        success = result.get("success", False)
        if success:
            print(f"测试完成: {output_file}")
        elif result.get("aborted", False):
            print(f"转换已中止: {input_file}")
            sys.exit(0)
        else:
            print(f"测试失败: {input_file}")
        return success

    def _auto_select_qvbr(
        self,
        input_file: str,
        encoder: str,
        source_video_info: Dict[str, object],
    ) -> Tuple[Optional[int], str]:
        duration_seconds = float(source_video_info.get("duration_seconds") or 0)
        source_kbps = self._get_source_bitrate_kbps(source_video_info)
        quality_name = Constants.quality_label(encoder)
        if duration_seconds <= 0:
            print(f"错误: 无法解析源视频时长，{quality_name} 自动取值失败")
            return None, "fail"
        test_input, created_clip = self._create_test_clip(input_file, duration_seconds)
        temp_dir = self._temp_dir()
        tester = NVEncTranscoder(
            self.transcoder.nvenc_path,
            True,
            self.no_qp_max_limit,
            self.keep_grain,
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.keep_grain:
            target_vmaf = 94.0
            lowest_vmaf = 88.0
            target_ssimu2 = 92.0
            lowest_ssimu2 = 85.0
            low, high = (12, 25) if Constants.is_svt_encoder(encoder) else (18, 36)
        else:
            target_vmaf = 96.0
            lowest_vmaf = 90.0
            target_ssimu2 = 85.0
            lowest_ssimu2 = 75.0
            low, high = (18, 32) if Constants.is_svt_encoder(encoder) else (25, 45)
        best_over_candidate = None
        best_over_metrics = None
        best_under_candidate = None
        best_under_metrics = None
        tested_ok = False

        def has_qp_issue(i_avg_qp: Optional[float]) -> bool:
            return (
                not self.no_qp_max_limit and i_avg_qp is not None and i_avg_qp >= 150.0
            )

        def _ssimu2_ok(metrics: Dict[str, float], floor: float) -> bool:
            ssimu2 = metrics.get("ssimu2")
            if ssimu2 is None:
                return True
            return ssimu2 >= floor

        def meets_target_quality(metrics: Dict[str, float]) -> bool:
            vmaf = metrics.get("vmaf")
            return bool(
                vmaf
                and vmaf >= target_vmaf
                and _ssimu2_ok(metrics, target_ssimu2)
                and not has_qp_issue(metrics.get("i_avg_qp"))
            )

        def meets_lowest_quality(metrics: Dict[str, float]) -> bool:
            vmaf = metrics.get("vmaf")
            return bool(
                vmaf
                and vmaf >= lowest_vmaf
                and _ssimu2_ok(metrics, lowest_ssimu2)
                and not has_qp_issue(metrics.get("i_avg_qp"))
            )

        def is_smaller_than_source(encoded_kbps: Optional[float]) -> bool:
            if encoded_kbps is None or source_kbps <= 0:
                return False
            limit = 0.85 if self.keep_grain else 0.80
            return encoded_kbps < source_kbps * limit

        def _quality_gap(metrics: Dict[str, float]) -> float:
            vmaf = float(metrics.get("vmaf") or 0.0)
            ssimu2 = metrics.get("ssimu2")
            vmaf_gap = abs(target_vmaf - vmaf)
            if ssimu2 is None:
                return vmaf_gap
            return vmaf_gap + abs(target_ssimu2 - float(ssimu2)) / 5.0

        def _format_metrics(metrics: Dict[str, float]) -> str:
            parts = [f"VMAF={metrics['vmaf']:.2f}"]
            if metrics.get("ssimu2") is not None:
                parts.append(f"SSIMU2={metrics['ssimu2']:.2f}")
            return "，".join(parts)

        def try_candidate(candidate: int) -> Optional[Dict[str, float]]:
            temp_output = temp_dir / (
                f"{Path(input_file).stem}_{quality_name.lower()}_{candidate}_{timestamp}.mkv"
            )
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
                return None
            metrics = result.get("quality", {})
            if metrics.get("vmaf") is None or metrics.get("encoded_kbps") is None:
                return None
            return metrics

        try:
            while low <= high:
                mid = (low + high) // 2
                metrics = try_candidate(mid)
                if metrics is None:
                    low = mid + 1
                    continue
                tested_ok = True
                if meets_target_quality(metrics):
                    best_over_candidate = mid
                    best_over_metrics = metrics
                    low = mid + 1
                    continue
                if meets_lowest_quality(metrics):
                    if best_under_metrics is None or _quality_gap(metrics) < _quality_gap(
                        best_under_metrics
                    ) or (
                        _quality_gap(metrics) == _quality_gap(best_under_metrics)
                        and mid > best_under_candidate
                    ):
                        best_under_candidate = mid
                        best_under_metrics = metrics
                high = mid - 1
        finally:
            if created_clip and test_input != input_file:
                Path(test_input).unlink(missing_ok=True)

        if best_over_metrics is not None and is_smaller_than_source(
            best_over_metrics.get("encoded_kbps")
        ):
            print(
                f"自动选择 {quality_name}={best_over_candidate}，{_format_metrics(best_over_metrics)}，"
                f"达到目标；视频码率 {best_over_metrics['encoded_kbps']:.0f}/{source_kbps:.0f} kbps"
            )
            return best_over_candidate, "encode"
        if best_under_metrics is not None and is_smaller_than_source(
            best_under_metrics.get("encoded_kbps")
        ):
            print(
                f"自动选择 {quality_name}={best_under_candidate}，{_format_metrics(best_under_metrics)}，"
                f"未达到目标但可压缩；视频码率 "
                f"{best_under_metrics['encoded_kbps']:.0f}/{source_kbps:.0f} kbps"
            )
            return best_under_candidate, "encode"
        if not tested_ok:
            print(f"错误: {quality_name} 试编码失败，无法判断是否需要转码")
            return None, "fail"
        if source_kbps > 0:
            print(
                f"源视频码率 {source_kbps:.0f} kbps，在可接受画质下无法再明显压缩，跳过转码"
            )
            return None, "skip"
        if best_over_candidate is not None:
            return best_over_candidate, "encode"
        if best_under_candidate is not None:
            return best_under_candidate, "encode"
        return None, "skip"

    def _handle_existing_output(self, output_file: str) -> str:
        output_path = Path(output_file)
        if not output_path.exists():
            return "transcode"
        if self.in_series_batch and self.always_skip_existing:
            print(f"检测到输出文件已存在，自动跳过: {output_file}")
            return "skip"

        print(f"\n检测到输出文件已存在: {output_file}")
        print(f"文件大小: {output_path.stat().st_size / (1024**2):.2f} MB")
        print(
            f"修改时间: {datetime.fromtimestamp(output_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print("\n请选择处理方式:")
        print("  1. 重新转码 (删除现有文件并重新转码)")
        print("  2. 跳过 (继续处理下一个)")
        print("  3. 放弃 (退出程序)")
        valid_choices = {"1", "2", "3"}
        if self.in_series_batch:
            print("  4. 总是跳过 (本次任务后续遇到已存在输出将自动跳过)")
            valid_choices.add("4")

        while True:
            choice = input("\n请输入选项对应数字: ").strip()
            if choice not in valid_choices:
                print("无效选项，请重新输入")
                continue
            if choice == "4":
                self.always_skip_existing = True
                return "skip"
            choice_res = {"1": "transcode", "2": "skip", "3": "abort"}[choice]
            if choice_res == "transcode":
                print(f"删除现有文件: {output_file}")
                output_path.unlink(missing_ok=True)
            return choice_res

    def _write_ffmetadata(
        self,
        chapters: List[Tuple[float, str]],
        duration_seconds: float,
        temp_dir: Path,
        stem: str,
        timestamp: str,
    ) -> str:
        if not chapters:
            return ""
        lines = [";FFMETADATA1"]
        filtered = []
        for start, title in chapters:
            if start < duration_seconds:
                filtered.append((start, title))
        if not filtered:
            return ""
        for idx, (start, title) in enumerate(filtered):
            next_start = (
                filtered[idx + 1][0] if idx + 1 < len(filtered) else duration_seconds
            )
            end = min(next_start, duration_seconds)
            if end <= start:
                continue
            lines.append("[CHAPTER]")
            lines.append("TIMEBASE=1/1000")
            lines.append(f"START={int(start * 1000)}")
            lines.append(f"END={int(end * 1000)}")
            lines.append(f"title={title}")
        if len(lines) <= 1:
            return ""
        meta_path = temp_dir / f"{stem}_chapters_{timestamp}.txt"
        meta_path.write_text("\n".join(lines), encoding="utf-8")
        return str(meta_path)

    def _auto_fix_output_duration(self, output_file: str) -> bool:
        info = self.media_info.extract_duration_info(output_file)
        format_duration = float(info.get("format_duration") or 0)
        video_duration = float(info.get("video_duration") or 0)
        if not self._is_duration_mismatch(format_duration, video_duration):
            return False
        print(
            f"\033[93m检测到时长异常，容器 {Utils.format_duration(format_duration)}，"
            f"视频 {Utils.format_duration(video_duration)}，尝试修正\033[0m"
        )
        temp_dir = self._temp_dir()
        output_path = Path(output_file)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_output = temp_dir / f"{output_path.stem}_trim_{timestamp}{output_path.suffix}"
        chapters = self.media_info.extract_chapters(output_file)
        meta_path = self._write_ffmetadata(
            chapters, video_duration, temp_dir, output_path.stem, timestamp
        )
        ffmpeg_args = ["-i", output_file, "-t", f"{video_duration:.3f}"]
        if meta_path:
            ffmpeg_args.extend(["-i", meta_path, "-map", "0", "-map_chapters", "1"])
        else:
            ffmpeg_args.extend(["-map", "0", "-map_chapters", "-1"])
        ffmpeg_args.extend(["-c", "copy"])
        ok = self._run_ffmpeg(ffmpeg_args, temp_output)
        if meta_path:
            Path(meta_path).unlink(missing_ok=True)
        if not ok:
            print("警告: 时长修正失败，保留原输出文件")
            return False
        output_path.unlink(missing_ok=True)
        temp_output.replace(output_path)
        print("\033[92m已修正输出时长与章节\033[0m")
        return True

    def _has_attached_pic_video(self, input_file: str) -> bool:
        data = self.media_info._run_ffprobe(input_file)
        if not data:
            return False
        for stream in data.get("streams", []):
            if stream.get("codec_type") != "video":
                continue
            disposition = stream.get("disposition", {}) or {}
            attached_pic = int(disposition.get("attached_pic", 0) or 0)
            if attached_pic:
                return True
        return False

    def _maybe_remove_attached_pic(self, input_file: str) -> Tuple[str, bool]:
        if not self._has_attached_pic_video(input_file):
            return input_file, False
        print("\033[93m检测到 attached_pic 视频流，将移除后再转码\033[0m")
        input_path = Path(input_file)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_input = self._temp_dir() / f"{input_path.stem}_no_ap_{timestamp}{input_path.suffix}"
        ok = self._run_ffmpeg(
            ["-i", input_file, "-map", "0", "-dn", "-c", "copy"],
            temp_input,
        )
        if not ok:
            print("警告: 移除 attached_pic 失败，继续使用原文件")
            return input_file, False
        print("\033[92m已移除 attached_pic 视频流\033[0m")
        return str(temp_input), True

    def _maybe_trim_source_input(self, input_file: str) -> Tuple[str, bool]:
        info = self.media_info.extract_duration_info(input_file)
        format_duration = float(info.get("format_duration") or 0)
        video_duration = float(info.get("video_duration") or 0)
        if not self._is_duration_mismatch(format_duration, video_duration):
            return input_file, False
        print(
            f"\033[93m检测到源文件时长异常，容器 {Utils.format_duration(format_duration)}，"
            f"视频 {Utils.format_duration(video_duration)}\033[0m"
        )
        choice = input("是否在转码前按真实视频时长截断输入? (y/N): ").strip().lower()
        if choice not in ("y", "yes", "是", "1"):
            return input_file, False
        input_path = Path(input_file)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_input = self._temp_dir() / f"{input_path.stem}_trim_src_{timestamp}{input_path.suffix}"
        ok = self._run_ffmpeg(
            ["-i", input_file, "-t", f"{video_duration:.3f}", "-map", "0", "-c", "copy"],
            temp_input,
        )
        if not ok:
            print("警告: 源文件截断失败，继续使用原文件")
            return input_file, False
        print("\033[92m已生成截断输入，使用截断文件进行转码\033[0m")
        return str(temp_input), True

    def convert_file(
        self,
        input_file: str,
        output_file: str = None,
        encoder: str = "av1_nvenc",
        qvbr: Optional[int] = None,
        skip_existing_check: bool = False,
    ) -> bool:
        input_path = Path(input_file)

        if not input_path.exists():
            print(f"错误: 输入文件不存在: {input_file}")
            return False

        if output_file is None:
            output_file = self._get_default_output_file(input_file)

        print(f"开始转换: {input_file}")
        print(f"输出文件: {output_file}")

        if not skip_existing_check:
            handle_choice = self._handle_existing_output(output_file)
            if handle_choice == "abort":
                self._abort_conversion(input_file)
            elif handle_choice == "skip":
                print(f"已跳过: {input_file}")
                self._record_skip(input_file, output_file, encoder)
                return True

        clean_input, cleaned = input_file, False
        trimmed_input, trimmed = input_file, False
        try:
            clean_input, cleaned = self._maybe_remove_attached_pic(input_file)
            trimmed_input, trimmed = self._maybe_trim_source_input(clean_input)
            chapter_file, audio_langs, subtitle_langs, audio_pids, subtitle_pids = (
                self._extract_bluray_metadata(input_path)
            )
            source_video_info = self.media_info.extract_source_video_info(trimmed_input)
            audio_track_ids = self._select_audio_track_ids(trimmed_input)
            if audio_langs and audio_pids:
                mapped_langs = self.media_info.map_languages_by_pid(
                    audio_langs,
                    audio_pids,
                    source_video_info.get("audio_stream_pids"),
                )
                if mapped_langs:
                    audio_langs = mapped_langs
            if audio_langs and audio_track_ids:
                filtered_langs = {}
                for idx, lang in audio_langs.items():
                    if idx + 1 in audio_track_ids:
                        filtered_langs[idx] = lang
                audio_langs = filtered_langs
            if subtitle_langs and subtitle_pids:
                mapped_langs = self.media_info.map_languages_by_pid(
                    subtitle_langs,
                    subtitle_pids,
                    source_video_info.get("subtitle_stream_pids"),
                )
                if mapped_langs:
                    subtitle_langs = mapped_langs

            if qvbr is None:
                selected_qvbr, qvbr_status = self._auto_select_qvbr(
                    trimmed_input, encoder, source_video_info
                )
                if qvbr_status == "fail":
                    print(f"转换失败: {input_file}")
                    return False
                if qvbr_status == "skip":
                    print(f"\033[93m该视频无需转码: {input_file}\033[0m")
                    self.skip_count += 1
                    self.skipped_files.append(input_file)
                    return True
                if selected_qvbr is not None:
                    qvbr = selected_qvbr

            result = self.transcoder.transcode(
                trimmed_input,
                output_file,
                encoder,
                chapter_file,
                audio_langs,
                subtitle_langs,
                source_video_info,
                qvbr,
                audio_track_ids,
            )

            success = result.get("success", False)

            if success:
                print(f"转换完成: {output_file}")
                self._auto_fix_output_duration(output_file)
                self.media_info.write_nfo(output_file, encoder, input_file)
            elif result.get("aborted", False):
                self._abort_conversion(input_file)
            else:
                print(f"转换失败: {input_file}")
            return success
        finally:
            for temp_path, created in (
                (clean_input, cleaned),
                (trimmed_input, trimmed),
            ):
                if created and temp_path != input_file:
                    Path(temp_path).unlink(missing_ok=True)

    def _process_bluray_directory(
        self,
        directory: str,
        output_dir: str,
        encoder: str,
        qvbr: Optional[int],
    ) -> bool:
        print("开始处理蓝光目录...")
        dir_path = Path(directory)
        dir_name = dir_path.name.upper()
        if dir_name == "BDMV":
            bdmv_dir = dir_path
            bluray_root = dir_path.parent
        elif dir_name in ("STREAM", "PLAYLIST", "CLIPINF"):
            bdmv_dir = dir_path.parent
            bluray_root = bdmv_dir.parent if bdmv_dir.name.upper() == "BDMV" else bdmv_dir
        else:
            bdmv_dir = dir_path / "BDMV" if (dir_path / "BDMV").exists() else dir_path
            bluray_root = dir_path if bdmv_dir.name.upper() == "BDMV" else bdmv_dir.parent
        playlist_dir = bdmv_dir / "PLAYLIST"
        stream_dir = bdmv_dir / "STREAM"

        playlist_infos = []
        if playlist_dir.exists() and stream_dir.exists():
            m2ts_files = self.detector.glob_m2ts(stream_dir)
            m2ts_size_map = {f.name.lower(): f.stat().st_size for f in m2ts_files}
            mpls_files = self.detector.glob_mpls(playlist_dir)
            for mpls_file in mpls_files:
                info = self.detector.parse_mpls_info(mpls_file)
                if not info:
                    continue
                clip_names = info.get("clip_names", [])
                size_bytes = sum(m2ts_size_map.get(name.lower(), 0) for name in clip_names)
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

    def _skip_season_video(
        self,
        video_file: Path,
        output_file: str,
        encoder: str,
        label: str,
        total_count: int,
    ) -> None:
        print(f"[{total_count}] 已跳过 {label}")
        self._record_skip(str(video_file), output_file, encoder)

    def _convert_season_videos(
        self,
        videos: List[Path],
        season_dir: Path,
        season_output: Path,
        encoder: str,
        qvbr: Optional[int],
        success_count: int,
        total_count: int,
        skip_existing_check: bool = False,
    ) -> Tuple[int, int]:
        for idx, video_file in enumerate(videos):
            total_count += 1
            output_file = str(season_output / f"{video_file.stem}.mkv")
            print(f"[{total_count}] 正在转换 {season_dir.name}\\{video_file.name}")
            if self.convert_file(
                str(video_file),
                output_file,
                encoder,
                qvbr,
                skip_existing_check and idx == 0,
            ):
                success_count += 1
        return success_count, total_count

    def _process_season(
        self,
        season_dir: Path,
        season_videos: List[Path],
        season_output: Path,
        encoder: str,
        qvbr: Optional[int],
        success_count: int,
        total_count: int,
    ) -> Tuple[int, int]:
        season_qvbr = qvbr
        start_index = 0
        skip_existing_for_first = False
        if season_qvbr is None:
            test_video = None
            for idx, video_file in enumerate(season_videos):
                output_file = str(season_output / f"{video_file.stem}.mkv")
                handle_choice = self._handle_existing_output(output_file)
                if handle_choice == "abort":
                    self._abort_conversion(str(video_file))
                if handle_choice == "skip":
                    total_count += 1
                    self._skip_season_video(
                        video_file,
                        output_file,
                        encoder,
                        f"{season_dir.name}\\{video_file.name}",
                        total_count,
                    )
                    success_count += 1
                    continue
                test_video = video_file
                start_index = idx
                break
            if test_video is None:
                return success_count, total_count
            source_video_info = self.media_info.extract_source_video_info(str(test_video))
            selected_qvbr, qvbr_status = self._auto_select_qvbr(
                str(test_video), encoder, source_video_info
            )
            if qvbr_status == "fail":
                print(
                    f"\033[91m{season_dir.name} 自动选择 {Constants.quality_label(encoder)} 失败，跳过该季\033[0m"
                )
                for video_file in season_videos[start_index:]:
                    total_count += 1
                    print(
                        f"[{total_count}] 失败 {season_dir.name}\\{video_file.name}"
                    )
                return success_count, total_count
            if qvbr_status == "skip":
                print(f"\033[93m{season_dir.name} 无需转码: 自动跳过该季\033[0m")
                for video_file in season_videos[start_index:]:
                    total_count += 1
                    output_file = str(season_output / f"{video_file.stem}.mkv")
                    self._skip_season_video(
                        video_file,
                        output_file,
                        encoder,
                        f"{season_dir.name}\\{video_file.name}",
                        total_count,
                    )
                    success_count += 1
                return success_count, total_count
            if selected_qvbr is not None:
                season_qvbr = selected_qvbr
            skip_existing_for_first = True
        return self._convert_season_videos(
            season_videos[start_index:],
            season_dir,
            season_output,
            encoder,
            season_qvbr,
            success_count,
            total_count,
            skip_existing_for_first,
        )

    def _process_tv_series_directory(
        self,
        directory: str,
        output_dir: str,
        encoder: str,
        qvbr: Optional[int],
    ) -> bool:
        print("开始处理电视剧目录...")
        dir_path = Path(directory)
        self.in_series_batch = True
        self.always_skip_existing = False
        try:
            season_dirs = sorted(
                self.detector.get_season_dirs(directory), key=lambda p: p.name
            )
            season_entries = []
            for season_dir in season_dirs:
                season_videos = sorted(Utils.get_video_files(season_dir))
                if season_videos:
                    season_entries.append((season_dir, season_videos))

            if season_entries:
                output_root = Utils.get_output_dir(output_dir) / dir_path.name
                output_root.mkdir(parents=True, exist_ok=True)
                success_count = 0
                total_count = 0
                for season_dir, season_videos in season_entries:
                    season_output = output_root / season_dir.name
                    season_output.mkdir(parents=True, exist_ok=True)
                    success_count, total_count = self._process_season(
                        season_dir,
                        season_videos,
                        season_output,
                        encoder,
                        qvbr,
                        success_count,
                        total_count,
                    )
                print(f"\n完成: 成功 {success_count}/{total_count} 个文件")
                return success_count == total_count

            video_files = Utils.get_video_files(dir_path)
            if not video_files:
                print("错误: 目录中未找到视频文件")
                return False

            output_path = Utils.get_output_dir(output_dir) / dir_path.name
            output_path.mkdir(parents=True, exist_ok=True)
            success_count = 0
            for idx, video_file in enumerate(sorted(video_files), 1):
                output_file = str(output_path / f"{video_file.stem}.mkv")
                print(f"[{idx}/{len(video_files)}] 正在转换 {video_file.name}")
                if self.convert_file(str(video_file), output_file, encoder, qvbr):
                    success_count += 1
            print(f"\n完成: 成功 {success_count}/{len(video_files)} 个文件")
            return success_count == len(video_files)
        finally:
            self.in_series_batch = False

    def _get_bluray_root_for_file(self, input_path: Path) -> Optional[Path]:
        if input_path.parent.name.upper() != "STREAM":
            return None
        bdmv_dir = input_path.parent.parent
        if bdmv_dir.name.upper() == "BDMV" and bdmv_dir.parent.exists():
            candidate = bdmv_dir.parent
            if self.detector.is_bluray_directory(str(candidate)):
                return candidate
        if self.detector.is_bluray_directory(str(bdmv_dir)):
            return bdmv_dir
        return None

    def _resolve_bluray_output_file(self, input_path: Path, output_dir: str) -> str:
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
        if dir_path.name.upper() == "BDMV" and dir_path.parent.exists():
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
                output_file = self._resolve_bluray_output_file(path, output_dir)
                return self.convert_file(input_path, output_file, encoder, qvbr)
            return self.convert_file(input_path, output_path, encoder, qvbr)
        elif path.is_dir():
            return self.convert_directory(input_path, output_path, encoder, qvbr)
        else:
            print(f"错误: 路径不存在: {input_path}")
            return False
