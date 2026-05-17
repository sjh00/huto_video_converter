import subprocess
import re
import sys
import time
import math
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from .utils import Utils
from .presets import QualityPreset


class NVEncTranscoder:
    def __init__(
        self,
        nvenc_path: str = None,
        enable_quality_eval: bool = False,
        no_qp_max_limit: bool = False,
    ):
        self.nvenc_path = nvenc_path or Utils.find_tool("NVEncC64")
        self.enable_quality_eval = enable_quality_eval
        self.no_qp_max_limit = no_qp_max_limit

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
    ) -> List[str]:
        format = "av1"
        if "hevc" in encoder.lower():
            format = "hevc"
        elif "h264" in encoder.lower():
            format = "h264"

        # Basic codec settings
        nvenc_opts_dict = {"codec": format}
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
            "sub-copy": None,
            "data-copy": None,
            "attachment-copy": None,
        })
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
                vmaf_params.append("model=vmaf_4k_v0.6.1")
            if vmaf_subsample > 1:
                vmaf_params.append(f"subsample={vmaf_subsample}")
            nvenc_opts_dict["vmaf"] = ",".join(vmaf_params) if vmaf_params else None
            nvenc_opts_dict["ssim"] = None
            nvenc_opts_dict["psnr"] = None

        nvenc_opts = []
        for k, v in nvenc_opts_dict.items():
            nvenc_opts.append(f"--{k}")
            if v is not None:
                nvenc_opts.append(str(v))
        nvenc_opts.extend(metadata_opts)
        return nvenc_opts

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
    ) -> Dict[str, any]:

        params = QualityPreset.get_params(encoder)
        if qvbr is not None:
            params["qvbr"] = qvbr
        if self.no_qp_max_limit:
            params.pop("qp-max", None)
        if "gop-len" not in params:
            fps = source_video_info.get("fps")
            if fps and fps > 0:
                params["gop-len"] = int(math.ceil(fps * 4))
            else:
                params["gop-len"] = 96

        source_video_info = source_video_info or {}
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
        )

        cmd, cmd_print = self._build_nvenc_cmd(input_file, output_file, nvenc_opts)
        print(f"\n命令: {cmd_print}")
        print(f"\n开始转码: {Path(input_file).name}")

        encode_start_time = time.time()

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=False,
        )

        output_chunks: List[bytes] = []

        try:
            while True:
                chunk = process.stdout.read(1024)
                if chunk == b"":
                    if process.poll() is not None:
                        break
                    continue
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                output_chunks.append(chunk)
        except KeyboardInterrupt:
            try:
                process.terminate()
            except Exception:
                pass
            return {"success": False, "aborted": True}
        finally:
            if chapter_file:
                Path(chapter_file).unlink(missing_ok=True)

        process.wait()
        encode_end_time = time.time()

        full_output = b"".join(output_chunks).decode("utf-8", errors="ignore")
        success = self._check_nvenc_success(process.returncode, full_output, output_file)
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
