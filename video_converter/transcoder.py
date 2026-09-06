import subprocess
import re
import sys
import time
import math
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from .utils import Utils
from .presets import QualityPreset
from .constants import Constants
from .tools import stop_process


class NVEncTranscoder:
    def __init__(
        self,
        nvenc_path: str = None,
        enable_quality_eval: bool = False,
        no_qp_max_limit: bool = False,
        keep_grain: bool = True,
    ):
        self.nvenc_path = nvenc_path or Utils.find_tool("NVEncC64")
        self.enable_quality_eval = enable_quality_eval
        self.no_qp_max_limit = no_qp_max_limit
        self.keep_grain = keep_grain

    def _filter_nvenc_output(self, output: str) -> Tuple[str, bool]:
        errors = []
        warnings = []
        has_error = False

        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue

            if re.search(r"\b(error|failed|fatal|critical)\b", line, re.IGNORECASE):
                errors.append(line)
                has_error = True
            elif re.search(r"\b(warning|warn)\b", line, re.IGNORECASE):
                warnings.append(line)

        filtered_output = []
        if errors:
            filtered_output.append("=== 错误 ===")
            filtered_output.extend(errors)
        if warnings:
            filtered_output.append("=== 警告 ===")
            filtered_output.extend(warnings)

        return "\n".join(filtered_output), has_error

    def _check_nvenc_success(self, returncode: int, output: str, output_file: str) -> bool:
        if returncode == 0:
            return True
        if Path(output_file).exists():
            _, has_error = self._filter_nvenc_output(output)
            if not has_error:
                return True
        return False

    def _parse_time_to_seconds(self, value: str) -> Optional[float]:
        parts = value.strip().split(":")
        if len(parts) != 3:
            return None
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
        except ValueError:
            return None
        return hours * 3600 + minutes * 60 + seconds

    def _extract_quality_metrics(self, output: str) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        encoded_match = re.search(
            r"\bencoded\s+\d+\s+frames.*?,\s*([0-9]+(?:\.[0-9]+)?)\s*kbps,"
            r"\s*([0-9]+(?:\.[0-9]+)?)\s*MB",
            output,
            re.IGNORECASE,
        )
        if encoded_match:
            metrics["encoded_kbps"] = float(encoded_match.group(1))
            metrics["encoded_size_mb"] = float(encoded_match.group(2))
        encode_time_match = re.search(
            r"\bencode time\s*([0-9]+:[0-9]+:[0-9]+(?:\.[0-9]+)?)",
            output,
            re.IGNORECASE,
        )
        if encode_time_match:
            seconds = self._parse_time_to_seconds(encode_time_match.group(1))
            if seconds is not None:
                metrics["encode_time_seconds"] = seconds
        vmaf_match = re.search(
            r"\bVMAF\b.*?\bScore\s*([0-9]+(?:\.[0-9]+)?)", output, re.IGNORECASE
        )
        if vmaf_match:
            metrics["vmaf"] = float(vmaf_match.group(1))
        ssimu2_match = re.search(
            r"\bSSIMU2\b.*?\bScore\s*([0-9]+(?:\.[0-9]+)?)", output, re.IGNORECASE
        )
        if ssimu2_match:
            metrics["ssimu2"] = float(ssimu2_match.group(1))
        butter_match = re.search(
            r"\bButteraugli\b.*?normQ:\s*([0-9]+(?:\.[0-9]+)?)", output, re.IGNORECASE
        )
        if butter_match:
            metrics["butteraugli"] = float(butter_match.group(1))
        ssim_match = re.search(
            r"\bSSIM\b.*?\bAll:\s*([0-9]+(?:\.[0-9]+)?)",
            output,
            re.IGNORECASE | re.DOTALL,
        )
        if ssim_match:
            metrics["ssim"] = float(ssim_match.group(1))
        psnr_match = re.search(
            r"\bPSNR\b.*?\bAvg:\s*([0-9]+(?:\.[0-9]+)?)",
            output,
            re.IGNORECASE | re.DOTALL,
        )
        if psnr_match:
            metrics["psnr"] = float(psnr_match.group(1))

        idr_match = re.search(r"frame type IDR\s+(\d+)", output, re.IGNORECASE)
        if idr_match:
            metrics["idr_count"] = float(idr_match.group(1))
        iframe_match = re.search(
            r"frame type I\s+(\d+),\s*avgQP\s*([0-9]+(?:\.[0-9]+)?)"
            r",\s*total size\s*([0-9]+(?:\.[0-9]+)?)\s*MB",
            output,
            re.IGNORECASE,
        )
        if iframe_match:
            metrics["i_count"] = float(iframe_match.group(1))
            metrics["i_avg_qp"] = float(iframe_match.group(2))
            metrics["i_size_mb"] = float(iframe_match.group(3))
        pframe_match = re.search(
            r"frame type P\s+(\d+),\s*avgQP\s*([0-9]+(?:\.[0-9]+)?)"
            r",\s*total size\s*([0-9]+(?:\.[0-9]+)?)\s*MB",
            output,
            re.IGNORECASE,
        )
        if pframe_match:
            metrics["p_count"] = float(pframe_match.group(1))
            metrics["p_avg_qp"] = float(pframe_match.group(2))
            metrics["p_size_mb"] = float(pframe_match.group(3))
        return metrics

    def _get_nvenc_options(
        self,
        params: Dict,
        encoder: str = "av1_nvenc",
        chapter_file: str = "",
        audio_langs: Dict[int, str] = None,
        subtitle_langs: Dict[int, str] = None,
        audio_track_ids: Optional[List[int]] = None,
        output_depth: Optional[int] = None,
        output_csp: Optional[str] = None,
        is_4k: bool = False,
        vmaf_subsample: int = 1,
        copy_subtitles: bool = False,
        input_file: str = "",
    ) -> List[str]:
        codec = "av1"
        if "hevc" in encoder.lower():
            codec = "hevc"
        elif "h264" in encoder.lower():
            codec = "h264"

        nvenc_opts_dict = {"codec": codec}
        nvenc_opts_dict.update(params)

        # HDR / Color handling - Always use auto/copy for maximum preservation
        nvenc_opts_dict.update({
            "colormatrix": "auto",
            "transfer": "auto",
            "colorprim": "auto",
            "chromaloc": "auto",
            "max-cll": "copy",
            "master-display": "copy",
            "dhdr10-info": "copy",
            "dolby-vision-rpu": "copy",
            "video-metadata": "copy",
        })

        # Track preservation (Maximum retention)
        nvenc_opts_dict.update({
            "audio-copy": None,
            "data-copy": None,
            "attachment-copy": None,
        })
        if copy_subtitles:
            nvenc_opts_dict["sub-copy"] = None
        suffix = Path(input_file).suffix.lower() if input_file else ""
        if suffix in {".m2ts", ".ts", ".m2t"}:
            nvenc_opts_dict.setdefault("input-analyze", 60)
        if audio_track_ids:
            nvenc_opts_dict["audio-copy"] = ",".join(str(idx) for idx in audio_track_ids)

        if output_depth in (8, 10):
            nvenc_opts_dict["output-depth"] = output_depth
        if output_csp:
            nvenc_opts_dict["output-csp"] = output_csp

        if chapter_file:
            nvenc_opts_dict["chapter"] = chapter_file
        else:
            nvenc_opts_dict["chapter-copy"] = None

        metadata_opts = []
        if audio_langs:
            for idx in sorted(audio_langs.keys()):
                lang = audio_langs.get(idx)
                if not lang:
                    continue
                track_id = idx + 1
                metadata_opts.extend(["--audio-metadata", f"{track_id}?language={lang}"])
        else:
            metadata_opts.extend(["--audio-metadata", "copy"])

        if copy_subtitles:
            if subtitle_langs:
                for idx in sorted(subtitle_langs.keys()):
                    lang = subtitle_langs.get(idx)
                    if not lang:
                        continue
                    track_id = idx + 1
                    metadata_opts.extend(["--sub-metadata", f"{track_id}?language={lang}"])
            else:
                metadata_opts.extend(["--sub-metadata", "copy"])

        # Quality Evaluation
        if self.enable_quality_eval:
            vmaf_params = []
            if is_4k:
                vmaf_params.append("model=vmaf_4k_v0.6.1neg")
            else:
                vmaf_params.append("model=vmaf_v0.6.1neg")
            if vmaf_subsample > 1:
                vmaf_params.append(f"subsample={vmaf_subsample}")
            nvenc_opts_dict["vmaf"] = ",".join(vmaf_params) if vmaf_params else None
            nvenc_opts_dict["ssim"] = None
            nvenc_opts_dict["psnr"] = None
            nvenc_opts_dict["vship-ssimulacra2"] = None

        nvenc_opts = []
        for k, v in nvenc_opts_dict.items():
            nvenc_opts.append(f"--{k}")
            if v is not None:
                nvenc_opts.append(str(v))
        nvenc_opts.extend(metadata_opts)
        return nvenc_opts

    def _mux_subtitles(
        self,
        encoded_file: str,
        source_file: str,
        output_file: str,
        subtitle_langs: Optional[Dict[int, str]] = None,
    ) -> str:
        temp_output = str(Path(output_file).with_name(Path(output_file).stem + "._subs.mkv"))
        cmd = [
            Utils.find_tool("ffmpeg"),
            "-y",
            "-hide_banner",
            "-i",
            encoded_file,
            "-fflags",
            "+genpts",
            "-analyzeduration",
            "100M",
            "-probesize",
            "100M",
            "-i",
            source_file,
            "-map",
            "0",
            "-map",
            "1:s?",
            "-c",
            "copy",
            "-max_interleave_delta",
            "0",
            "-map_metadata",
            "0",
            "-map_chapters",
            "0",
        ]
        if subtitle_langs:
            for idx in sorted(subtitle_langs.keys()):
                lang = subtitle_langs.get(idx)
                if lang:
                    cmd.extend(["-metadata:s:s:" + str(idx), f"language={lang}"])
        cmd.append(temp_output)
        print("并行转码完成，正在用 ffmpeg 补入字幕...")
        returncode, full_output, aborted = self._run_nvenc_process(cmd, stream=False)
        if aborted:
            Path(temp_output).unlink(missing_ok=True)
            Path(output_file).unlink(missing_ok=True)
            return "aborted"
        if returncode != 0 or not Path(temp_output).exists():
            Path(temp_output).unlink(missing_ok=True)
            err = (full_output or "").strip().splitlines()
            tail = "\n".join(err[-12:])
            print(f"警告: 字幕封装失败，保留无字幕成片\n{tail}")
            return "fail"
        Path(output_file).unlink(missing_ok=True)
        Path(temp_output).replace(output_file)
        print("已补入源片字幕")
        return "ok"

    def _run_nvenc_process(
        self, cmd: List[str], stream: bool = True
    ) -> Tuple[int, str, bool]:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=False,
        )
        output_chunks: List[bytes] = []
        try:
            if stream:
                while True:
                    chunk = process.stdout.read(1024)
                    if chunk == b"":
                        if process.poll() is not None:
                            break
                        continue
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                    output_chunks.append(chunk)
            else:
                stdout, _ = process.communicate()
                if stdout:
                    output_chunks.append(stdout)
        except KeyboardInterrupt:
            stop_process(process)
            return -1, "", True
        process.wait()
        full_output = b"".join(output_chunks).decode("utf-8", errors="ignore")
        return process.returncode, full_output, False

    def _build_nvenc_cmd(self, input_file: str, output_file: str, nvenc_opts: List[str]) -> Tuple[List[str], str]:
        cmd = [self.nvenc_path, "--avhw"] + nvenc_opts + ["-i", input_file, "-o", output_file]
        cmd_print = ' '.join(cmd)
        cmd_print = cmd_print.replace(input_file, f'"{input_file}"')
        cmd_print = cmd_print.replace(output_file, f'"{output_file}"')
        return cmd, cmd_print

    def _calculate_bitrate(
        self,
        bitrate: float,
        size_bytes: float,
        duration_seconds: float,
        file_path: str,
    ) -> int:
        if bitrate and bitrate > 0:
            return int(bitrate)
        if size_bytes <= 0 and file_path:
            try:
                size_bytes = float(Path(file_path).stat().st_size)
            except OSError:
                size_bytes = 0
        if size_bytes > 0 and duration_seconds > 0:
            return int((size_bytes * 8) / duration_seconds)
        return 0

    def _print_bitrate_compression(
        self,
        source_video_info: Dict[str, object],
        input_file: str,
        output_file: str,
        metrics: Dict[str, object],
    ) -> None:
        duration_seconds = float(source_video_info.get("duration_seconds") or 0)
        if duration_seconds <= 0:
            return
        source_bitrate = self._calculate_bitrate(
            float(source_video_info.get("bit_rate") or 0),
            float(source_video_info.get("size_bytes") or 0),
            duration_seconds,
            input_file,
        )
        if source_bitrate <= 0:
            return
        output_bitrate = 0
        encoded_kbps = metrics.get("encoded_kbps") if metrics else None
        if encoded_kbps:
            output_bitrate = int(float(encoded_kbps) * 1000)
        if output_bitrate <= 0:
            output_bitrate = self._calculate_bitrate(0, 0, duration_seconds, output_file)
        if output_bitrate <= 0:
            return
        ratio = output_bitrate / source_bitrate
        print(
            f"码率压缩比: {ratio * 100:.1f}% (输出 {Utils.format_bitrate(output_bitrate)} / "
            f"源 {Utils.format_bitrate(source_bitrate)})"
        )

    def _svt_gop_len(
        self, source_video_info: Dict[str, object], gop_len: Optional[int]
    ) -> int:
        if gop_len is not None and gop_len > 0:
            return int(gop_len)
        fps = source_video_info.get("fps")
        if fps and fps > 0:
            return math.ceil(float(fps) * 4)
        return 96

    def _chapter_xml_to_ffmetadata(self, chapter_file: str, duration_seconds: float) -> str:
        try:
            text = Path(chapter_file).read_text(encoding="utf-8")
        except OSError:
            return ""
        starts = re.findall(r"<ChapterTimeStart>([^<]+)</ChapterTimeStart>", text)
        names = re.findall(r"<ChapterString>([^<]+)</ChapterString>", text)
        if not starts:
            return ""

        def to_seconds(value: str) -> Optional[float]:
            parts = value.strip().split(":")
            if len(parts) != 3:
                return None
            try:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except ValueError:
                return None

        entries = []
        for idx, start_text in enumerate(starts):
            start = to_seconds(start_text)
            if start is None:
                continue
            title = names[idx] if idx < len(names) else f"Chapter {idx + 1}"
            entries.append((start, title))
        if not entries:
            return ""
        if duration_seconds <= 0:
            duration_seconds = entries[-1][0] + 1.0
        lines = [";FFMETADATA1"]
        for idx, (start, title) in enumerate(entries):
            if start >= duration_seconds:
                continue
            end = (
                entries[idx + 1][0] if idx + 1 < len(entries) else duration_seconds
            )
            end = min(end, duration_seconds)
            if end <= start:
                continue
            lines.extend(
                [
                    "[CHAPTER]",
                    "TIMEBASE=1/1000",
                    f"START={int(start * 1000)}",
                    f"END={int(end * 1000)}",
                    f"title={title}",
                ]
            )
        if len(lines) <= 1:
            return ""
        meta_path = Path(chapter_file).with_suffix(".ffmeta")
        meta_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(meta_path)

    def _parse_ffmpeg_video_kbps(self, output: str) -> Optional[float]:
        match = re.search(
            r"video:\s*([0-9]+)\s*KiB.*?time=\s*([0-9]+:[0-9]+:[0-9]+(?:\.[0-9]+)?)",
            output,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            kib = float(match.group(1))
            seconds = self._parse_time_to_seconds(match.group(2))
            if seconds and seconds > 0:
                return kib * 1024 * 8 / seconds / 1000.0
        match = re.search(
            r"\bLsize=.*?bitrate=\s*([0-9]+(?:\.[0-9]+)?)\s*kbits/s",
            output,
            re.IGNORECASE,
        )
        if match:
            return float(match.group(1))
        return None

    def _evaluate_ffmpeg_vmaf(
        self,
        encoded_file: str,
        reference_file: str,
        is_4k: bool,
        vmaf_subsample: int,
    ) -> Optional[float]:
        model = "version=vmaf_4k_v0.6.1neg" if is_4k else "version=vmaf_v0.6.1neg"
        subsample = max(1, int(vmaf_subsample or 1))
        lavfi = (
            "[0:v]setpts=PTS-STARTPTS[main];"
            "[1:v]setpts=PTS-STARTPTS[ref];"
            f"[main][ref]libvmaf=model={model}:n_threads=0:n_subsample={subsample}"
        )
        cmd = [
            Utils.find_tool("ffmpeg"),
            "-hide_banner",
            "-i",
            encoded_file,
            "-i",
            reference_file,
            "-lavfi",
            lavfi,
            "-f",
            "null",
            "-",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        match = re.search(r"VMAF score:\s*([0-9]+(?:\.[0-9]+)?)", log, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None

    def _build_svt_cmd(
        self,
        input_file: str,
        output_file: str,
        crf: int,
        source_video_info: Dict[str, object],
        chapter_file: str,
        audio_langs: Optional[Dict[int, str]],
        subtitle_langs: Optional[Dict[int, str]],
        audio_track_ids: Optional[List[int]],
        gop_len: Optional[int],
    ) -> Tuple[List[str], str, List[str]]:
        params = QualityPreset.get_params("svt_av1")
        preset = int(params.get("preset") or 5)
        tune = int(params.get("tune") if params.get("tune") is not None else 0)
        keyint = self._svt_gop_len(source_video_info, gop_len)
        depth = source_video_info.get("output_depth")
        pix_fmt = "yuv420p10le" if depth != 8 else "yuv420p"
        svt_parts = [
            f"tune={tune}",
            "film-grain=0",
            f"keyint={keyint}",
        ]
        extras_to_delete: List[str] = []
        cmd = [
            Utils.find_tool("ffmpeg"),
            "-y",
            "-hide_banner",
            "-i",
            input_file,
        ]
        ffmeta = ""
        if chapter_file:
            ffmeta = self._chapter_xml_to_ffmetadata(
                chapter_file, float(source_video_info.get("duration_seconds") or 0)
            )
            if ffmeta:
                cmd.extend(["-i", ffmeta])
                extras_to_delete.append(ffmeta)
        cmd.extend(["-map", "0:v:0"])
        if audio_track_ids:
            for track_id in audio_track_ids:
                if track_id and int(track_id) > 0:
                    cmd.extend(["-map", f"0:a:{int(track_id) - 1}"])
        else:
            cmd.extend(["-map", "0:a?"])
        cmd.extend(["-map", "0:s?", "-map", "0:d?", "-map", "0:t?"])
        cmd.extend(
            [
                "-c:v",
                "libsvtav1",
                "-preset",
                str(preset),
                "-crf",
                str(crf),
                "-pix_fmt",
                pix_fmt,
                "-svtav1-params",
                ":".join(svt_parts),
            ]
        )
        color_flags = [
            ("color_primaries", "color_primaries"),
            ("color_trc", "color_transfer"),
            ("colorspace", "color_space"),
            ("color_range", "color_range"),
        ]
        for ffmpeg_key, info_key in color_flags:
            value = source_video_info.get(info_key)
            if value:
                cmd.extend([f"-{ffmpeg_key}", str(value)])
        cmd.extend(["-c:a", "copy", "-c:s", "copy", "-c:d", "copy", "-c:t", "copy"])
        cmd.extend(["-map_metadata", "0"])
        if ffmeta:
            cmd.extend(["-map_chapters", "1"])
        else:
            cmd.extend(["-map_chapters", "0"])
        if audio_langs:
            for idx in sorted(audio_langs.keys()):
                lang = audio_langs.get(idx)
                if lang:
                    cmd.extend(["-metadata:s:a:" + str(idx), f"language={lang}"])
        if subtitle_langs:
            for idx in sorted(subtitle_langs.keys()):
                lang = subtitle_langs.get(idx)
                if lang:
                    cmd.extend(["-metadata:s:s:" + str(idx), f"language={lang}"])
        cmd.append(output_file)
        cmd_print = " ".join(f'"{p}"' if " " in str(p) else str(p) for p in cmd)
        return cmd, cmd_print, extras_to_delete

    def _transcode_svt(
        self,
        input_file: str,
        output_file: str,
        encoder: str,
        chapter_file: str,
        audio_langs: Optional[Dict[int, str]],
        subtitle_langs: Optional[Dict[int, str]],
        source_video_info: Dict[str, object],
        crf: Optional[int],
        audio_track_ids: Optional[List[int]],
        gop_len: Optional[int],
    ) -> Dict[str, object]:
        if crf is None:
            crf = 18 if self.keep_grain else 24
        cmd, cmd_print, extras = self._build_svt_cmd(
            input_file,
            output_file,
            crf,
            source_video_info,
            chapter_file,
            audio_langs,
            subtitle_langs,
            audio_track_ids,
            gop_len,
        )
        print(f"\n命令: {cmd_print}")
        print(f"\n开始转码: {Path(input_file).name} (SVT-AV1 CRF={crf})")
        encode_start_time = time.time()
        try:
            returncode, full_output, aborted = self._run_nvenc_process(cmd)
        finally:
            if chapter_file:
                Path(chapter_file).unlink(missing_ok=True)
            for extra in extras:
                Path(extra).unlink(missing_ok=True)
        encode_end_time = time.time()
        if aborted:
            Path(output_file).unlink(missing_ok=True)
            return {"success": False, "aborted": True}
        success = returncode == 0 and Path(output_file).exists()
        metrics: Dict[str, float] = {}
        encoded_kbps = self._parse_ffmpeg_video_kbps(full_output)
        if encoded_kbps is not None:
            metrics["encoded_kbps"] = encoded_kbps
        if success and encoded_kbps is None:
            duration_seconds = float(source_video_info.get("duration_seconds") or 0)
            if duration_seconds > 0:
                metrics["encoded_kbps"] = self._calculate_bitrate(
                    0, 0, duration_seconds, output_file
                ) / 1000.0
        if success and self.enable_quality_eval:
            print("正在计算 VMAF...")
            vmaf = self._evaluate_ffmpeg_vmaf(
                output_file,
                input_file,
                bool(source_video_info.get("is_4k")),
                int(source_video_info.get("vmaf_subsample") or 1),
            )
            if vmaf is not None:
                metrics["vmaf"] = vmaf
                print(f"VMAF: {vmaf:.4f}")
            else:
                print("警告: 未能解析 VMAF")
        result = {
            "success": success,
            "encoder": encoder,
            "quality": metrics,
            "timing": {
                "encode_time": encode_end_time - encode_start_time,
                "total_time": encode_end_time - encode_start_time,
            },
        }
        if success:
            print(f"转码耗时: {result['timing']['encode_time']:.1f} 秒")
            self._print_bitrate_compression(
                source_video_info, input_file, output_file, metrics
            )
        else:
            print("转码失败")
            if full_output:
                tail = "\n".join(full_output.strip().splitlines()[-20:])
                print(tail)
        return result

    def transcode(
        self,
        input_file: str,
        output_file: str,
        encoder: str = "av1_nvenc",
        chapter_file: str = "",
        audio_langs: Dict[int, str] = None,
        subtitle_langs: Dict[int, str] = None,
        source_video_info: Optional[Dict[str, object]] = None,
        qvbr: Optional[int] = None,
        audio_track_ids: Optional[List[int]] = None,
        gop_len: Optional[int] = None,
    ) -> Dict[str, object]:
        source_video_info = source_video_info or {}
        if Constants.is_svt_encoder(encoder):
            return self._transcode_svt(
                input_file,
                output_file,
                encoder,
                chapter_file,
                audio_langs,
                subtitle_langs,
                source_video_info,
                qvbr,
                audio_track_ids,
                gop_len,
            )

        params = QualityPreset.get_params(encoder)
        if qvbr is not None:
            params["qvbr"] = qvbr
        if self.no_qp_max_limit:
            params.pop("qp-max", None)
        is_4k = bool(source_video_info.get("is_4k"))
        if "max-bitrate" not in params:
            params["max-bitrate"] = 100000 if is_4k else 40000
        if self.keep_grain:
            params["tf-level"] = 0
            params["no-i-adapt"] = None
            params["no-b-adapt"] = None
        if gop_len is not None:
            params["gop-len"] = gop_len
        elif "gop-len" not in params:
            fps = source_video_info.get("fps")
            if fps and fps > 0:
                params["gop-len"] = math.ceil(fps * 4)
            else:
                params["gop-len"] = 96
        is_mpegts = Path(input_file).suffix.lower() in {".m2ts", ".ts", ".m2t"}
        has_subtitles = bool(subtitle_langs) or bool(
            source_video_info.get("subtitle_stream_pids")
        ) or is_mpegts
        nvenc_opts = self._get_nvenc_options(
            params,
            encoder=encoder,
            chapter_file=chapter_file,
            audio_langs=audio_langs,
            subtitle_langs=subtitle_langs,
            audio_track_ids=audio_track_ids,
            output_depth=source_video_info.get("output_depth"),
            output_csp=source_video_info.get("output_csp"),
            is_4k=bool(source_video_info.get("is_4k")),
            vmaf_subsample=source_video_info.get("vmaf_subsample", 1),
            copy_subtitles=False,
            input_file=input_file,
        )

        encode_start_time = time.time()
        cmd, cmd_print = self._build_nvenc_cmd(input_file, output_file, nvenc_opts)
        print(f"\n命令: {cmd_print}")
        print(f"\n开始转码: {Path(input_file).name}")
        returncode, full_output, aborted = self._run_nvenc_process(cmd)
        if aborted:
            if chapter_file:
                Path(chapter_file).unlink(missing_ok=True)
            Path(output_file).unlink(missing_ok=True)
            return {"success": False, "aborted": True}

        success = self._check_nvenc_success(returncode, full_output, output_file)
        if success and has_subtitles:
            mux_status = self._mux_subtitles(
                output_file, input_file, output_file, subtitle_langs
            )
            if mux_status == "aborted":
                if chapter_file:
                    Path(chapter_file).unlink(missing_ok=True)
                return {"success": False, "aborted": True}

        if chapter_file:
            Path(chapter_file).unlink(missing_ok=True)

        encode_end_time = time.time()
        metrics = self._extract_quality_metrics(full_output)

        result = {
            "success": success,
            "encoder": encoder,
            "quality": metrics,
            "timing": {
                "encode_time": encode_end_time - encode_start_time,
                "total_time": encode_end_time - encode_start_time
            }
        }

        if success:
            print(f"转码耗时: {result['timing']['encode_time']:.1f} 秒")
            self._print_bitrate_compression(source_video_info, input_file, output_file, metrics)
        else:
            filtered_out, _ = self._filter_nvenc_output(full_output)
            print(f"转码失败:\n{filtered_out}")

        return result
