import subprocess
import re
import sys
import time
import math
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional

from .utils import Utils
from .presets import QualityPreset


class NVEncTranscoder:
    def __init__(self, nvenc_path: str = None, enable_quality_eval: bool = False):
        self.nvenc_path = nvenc_path or Utils.find_tool("NVEncC64")
        self.enable_quality_eval = enable_quality_eval

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

    def _extract_quality_metrics(self, output: str) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
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
    ) -> Dict[str, any]:

        handle_choice = self._handle_existing_output(output_file)
        if handle_choice == "abort":
            return {"success": False, "aborted": True}
        elif handle_choice == "skip":
            return {"success": False, "skipped": True}

        params = QualityPreset.get_params(encoder)
        if qvbr is not None:
            params["qvbr"] = qvbr
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
        else:
            filtered_out, _ = self._filter_nvenc_output(full_output)
            print(f"转码失败:\n{filtered_out}")

        return result
