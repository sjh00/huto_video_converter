import argparse
import math
import time
from pathlib import Path
from typing import Dict, List, Tuple

from video_converter.converter import VideoConverter
from video_converter.presets import QualityPreset
from video_converter.utils import Utils


def _parse_fps(converter: VideoConverter, input_file: str) -> float:
    data = converter.media_info._run_ffprobe(input_file)
    if not data:
        return 0.0
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    value = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate", "")
    return converter.media_info._parse_frame_rate(value)


def _parse_duration_seconds(converter: VideoConverter, input_file: str) -> float:
    data = converter.media_info._run_ffprobe(input_file)
    if not data:
        return 0.0
    format_info = data.get("format", {})
    try:
        return float(format_info.get("duration") or 0.0)
    except ValueError:
        return 0.0


def _build_metadata(
    converter: VideoConverter, input_file: str, source_video_info: Dict[str, object]
) -> Tuple[str, Dict[int, str], Dict[int, str]]:
    chapter_file, audio_langs, subtitle_langs, audio_pids, subtitle_pids = (
        converter._extract_bluray_metadata(Path(input_file))
    )
    if audio_langs and audio_pids:
        mapped_langs = converter.media_info.map_audio_languages_by_pid(
            audio_langs,
            audio_pids,
            source_video_info.get("audio_stream_pids"),
        )
        if mapped_langs:
            audio_langs = mapped_langs
    if subtitle_langs and subtitle_pids:
        mapped_langs = converter.media_info.map_subtitle_languages_by_pid(
            subtitle_langs,
            subtitle_pids,
            source_video_info.get("subtitle_stream_pids"),
        )
        if mapped_langs:
            subtitle_langs = mapped_langs
    return chapter_file, audio_langs, subtitle_langs


def _ensure_output_root(output_dir: str, input_file: str, encoder: str) -> Path:
    base = Utils.get_output_dir(output_dir)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return base / "gop_len_experiment" / Path(input_file).stem / encoder / timestamp


def _format_stats(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    avg = sum(values) / len(values)
    var = sum((v - avg) ** 2 for v in values) / len(values)
    return avg, math.sqrt(var)


def _build_svg_line_chart(
    title: str,
    x_values: List[int],
    y_values: List[float],
    x_label: str,
    y_label: str,
) -> str:
    width = 900
    height = 300
    padding = 50
    if not x_values or not y_values:
        return ""
    y_min = min(y_values)
    y_max = max(y_values)
    if y_min == y_max:
        y_min -= 1
        y_max += 1

    def x_pos(x_val: int) -> float:
        idx = x_values.index(x_val)
        if len(x_values) == 1:
            return padding + (width - 2 * padding) / 2
        return padding + (width - 2 * padding) * (idx / (len(x_values) - 1))

    def y_pos(y_val: float) -> float:
        return padding + (height - 2 * padding) * (1 - (y_val - y_min) / (y_max - y_min))

    points = " ".join(f"{x_pos(x):.2f},{y_pos(y):.2f}" for x, y in zip(x_values, y_values))
    y_ticks = 5
    y_tick_values = [y_min + (y_max - y_min) * i / y_ticks for i in range(y_ticks + 1)]
    y_tick_lines = "\n".join(
        f'<line x1="{padding}" y1="{y_pos(v):.2f}" x2="{width - padding}" y2="{y_pos(v):.2f}" '
        f'stroke="#e6e6e6" stroke-width="1" />'
        for v in y_tick_values
    )
    y_tick_labels = "\n".join(
        f'<text x="{padding - 10}" y="{y_pos(v) + 4:.2f}" text-anchor="end" font-size="12" fill="#555">{v:.2f}</text>'
        for v in y_tick_values
    )
    x_tick_labels = "\n".join(
        f'<text x="{x_pos(x):.2f}" y="{height - padding + 18}" text-anchor="middle" font-size="12" fill="#555">{x}</text>'
        for x in x_values
    )

    return f"""
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>
  <text x="{width / 2}" y="24" text-anchor="middle" font-size="16" fill="#222">{title}</text>
  {y_tick_lines}
  <line x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}" stroke="#333" stroke-width="1.5"/>
  <line x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}" stroke="#333" stroke-width="1.5"/>
  {y_tick_labels}
  {x_tick_labels}
  <polyline fill="none" stroke="#2f6fed" stroke-width="2.5" points="{points}" />
  {"".join(f'<circle cx="{x_pos(x):.2f}" cy="{y_pos(y):.2f}" r="3" fill="#2f6fed"/>' for x, y in zip(x_values, y_values))}
  <text x="{width / 2}" y="{height - 8}" text-anchor="middle" font-size="12" fill="#222">{x_label}</text>
  <text x="16" y="{height / 2}" text-anchor="middle" font-size="12" fill="#222" transform="rotate(-90 16 {height / 2})">{y_label}</text>
</svg>
"""


def _write_html_report(
    output_root: Path,
    input_name: str,
    encoder: str,
    fps: float,
    gop_values: List[int],
    results: Dict[int, Dict[str, List[float]]],
):
    time_avgs = []
    size_avgs = []
    bitrate_avgs = []
    vmaf_avgs = []
    ssim_avgs = []
    psnr_avgs = []
    i_count_avgs = []
    i_avg_qp_avgs = []
    i_size_avgs = []
    p_count_avgs = []
    p_avg_qp_avgs = []
    p_size_avgs = []
    idr_count_avgs = []
    rows = []
    for gop_len in gop_values:
        time_avg, time_std = _format_stats(results[gop_len]["time"])
        size_avg, size_std = _format_stats(results[gop_len]["size"])
        br_avg, br_std = _format_stats(results[gop_len]["bitrate"])
        vmaf_avg, vmaf_std = _format_stats(results[gop_len]["vmaf"])
        ssim_avg, ssim_std = _format_stats(results[gop_len]["ssim"])
        psnr_avg, psnr_std = _format_stats(results[gop_len]["psnr"])
        i_count_avg, i_count_std = _format_stats(results[gop_len]["i_count"])
        i_avg_qp_avg, i_avg_qp_std = _format_stats(results[gop_len]["i_avg_qp"])
        i_size_avg, i_size_std = _format_stats(results[gop_len]["i_size_mb"])
        p_count_avg, p_count_std = _format_stats(results[gop_len]["p_count"])
        p_avg_qp_avg, p_avg_qp_std = _format_stats(results[gop_len]["p_avg_qp"])
        p_size_avg, p_size_std = _format_stats(results[gop_len]["p_size_mb"])
        idr_count_avg, idr_count_std = _format_stats(results[gop_len]["idr_count"])
        time_avgs.append(time_avg)
        size_avgs.append(size_avg)
        bitrate_avgs.append(br_avg)
        vmaf_avgs.append(vmaf_avg)
        ssim_avgs.append(ssim_avg)
        psnr_avgs.append(psnr_avg)
        i_count_avgs.append(i_count_avg)
        i_avg_qp_avgs.append(i_avg_qp_avg)
        i_size_avgs.append(i_size_avg)
        p_count_avgs.append(p_count_avg)
        p_avg_qp_avgs.append(p_avg_qp_avg)
        p_size_avgs.append(p_size_avg)
        idr_count_avgs.append(idr_count_avg)
        rows.append(
            f"<tr><td>{gop_len}</td><td>{time_avg:.2f} ± {time_std:.2f}</td>"
            f"<td>{size_avg:.2f} ± {size_std:.2f}</td><td>{br_avg:.2f} ± {br_std:.2f}</td>"
            f"<td>{vmaf_avg:.2f} ± {vmaf_std:.2f}</td><td>{ssim_avg:.4f} ± {ssim_std:.4f}</td>"
            f"<td>{psnr_avg:.2f} ± {psnr_std:.2f}</td>"
            f"<td>{i_count_avg:.1f} ± {i_count_std:.1f}</td>"
            f"<td>{i_avg_qp_avg:.2f} ± {i_avg_qp_std:.2f}</td>"
            f"<td>{i_size_avg:.2f} ± {i_size_std:.2f}</td>"
            f"<td>{p_count_avg:.1f} ± {p_count_std:.1f}</td>"
            f"<td>{p_avg_qp_avg:.2f} ± {p_avg_qp_std:.2f}</td>"
            f"<td>{p_size_avg:.2f} ± {p_size_std:.2f}</td>"
            f"<td>{idr_count_avg:.1f} ± {idr_count_std:.1f}</td></tr>"
        )

    time_svg = _build_svg_line_chart(
        "Encoding Time", gop_values, time_avgs, "GOP Length", "Seconds"
    )
    size_svg = _build_svg_line_chart(
        "Output Size", gop_values, size_avgs, "GOP Length", "MB"
    )
    bitrate_svg = _build_svg_line_chart(
        "Bitrate", gop_values, bitrate_avgs, "GOP Length", "Mbps"
    )
    vmaf_svg = _build_svg_line_chart(
        "VMAF", gop_values, vmaf_avgs, "GOP Length", "VMAF Score"
    )
    ssim_svg = _build_svg_line_chart(
        "SSIM", gop_values, ssim_avgs, "GOP Length", "SSIM"
    )
    psnr_svg = _build_svg_line_chart(
        "PSNR", gop_values, psnr_avgs, "GOP Length", "PSNR (dB)"
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>GOP Length Experiment Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
    h1 {{ margin-bottom: 4px; }}
    .meta {{ color: #555; margin-bottom: 16px; }}
    .chart {{ margin: 18px 0; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
    th {{ background: #f5f5f5; }}
  </style>
</head>
<body>
  <h1>GOP Length Experiment Report</h1>
  <div class="meta">Input: {input_name} | Encoder: {encoder} | FPS: {fps:.3f}</div>
  <div class="chart">{time_svg}</div>
  <div class="chart">{size_svg}</div>
  <div class="chart">{bitrate_svg}</div>
  <div class="chart">{vmaf_svg}</div>
  <div class="chart">{ssim_svg}</div>
  <div class="chart">{psnr_svg}</div>
  <h2>Summary (Mean ± Std)</h2>
  <table>
    <thead>
      <tr>
        <th>GOP Length</th>
        <th>Time (s)</th>
        <th>Size (MB)</th>
        <th>Bitrate (Mbps)</th>
        <th>VMAF</th>
        <th>SSIM</th>
        <th>PSNR (dB)</th>
        <th>I Frames</th>
        <th>I AvgQP</th>
        <th>I Size (MB)</th>
        <th>P Frames</th>
        <th>P AvgQP</th>
        <th>P Size (MB)</th>
        <th>IDR Frames</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    report_path = output_root / "gop_len_report.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"\nReport saved: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="gop_len 五折实验脚本")
    parser.add_argument("input", help="输入视频文件")
    parser.add_argument("-o", "--output", help="输出目录")
    parser.add_argument(
        "-e",
        "--encoder",
        default="av1_nvenc",
        choices=list(QualityPreset.encoders),
        help="编码器",
    )
    parser.add_argument("-p", "--nvenc-path", default=None, help="NVEncC64 路径")
    parser.add_argument("--disable-quality-eval", action="store_true", default=False)
    parser.add_argument("--min-mult", type=int, default=1, help="gop_len = fps * min_mult")
    parser.add_argument("--max-mult", type=int, default=10, help="gop_len = fps * max_mult")
    parser.add_argument("--folds", type=int, default=5, help="每个 gop_len 运行次数")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists() or not input_path.is_file():
        print(f"错误: 输入文件不存在: {args.input}")
        raise SystemExit(1)

    enable_quality_eval = not args.disable_quality_eval
    converter = VideoConverter(args.nvenc_path, enable_quality_eval)
    fps = _parse_fps(converter, args.input)
    if fps <= 0:
        print("错误: 无法解析帧率")
        raise SystemExit(1)

    duration_seconds = _parse_duration_seconds(converter, args.input)
    if duration_seconds <= 0:
        print("错误: 无法解析时长")
        raise SystemExit(1)

    gop_values = []
    for mult in range(args.min_mult, args.max_mult + 1):
        gop_values.append(max(1, int(round(fps * mult))))
    gop_values = list(dict.fromkeys(gop_values))

    output_root = _ensure_output_root(args.output, args.input, args.encoder)
    output_root.mkdir(parents=True, exist_ok=True)

    results: Dict[int, Dict[str, List[float]]] = {}

    source_video_info = converter.media_info.extract_source_video_info(args.input)

    for gop_len in gop_values:
        QualityPreset.encoder_params[args.encoder]["gop-len"] = gop_len
        results[gop_len] = {
            "time": [],
            "size": [],
            "bitrate": [],
            "vmaf": [],
            "ssim": [],
            "psnr": [],
            "i_count": [],
            "i_avg_qp": [],
            "i_size_mb": [],
            "p_count": [],
            "p_avg_qp": [],
            "p_size_mb": [],
            "idr_count": [],
        }
        print(f"\n{'=' * 70}")
        print(f"gop_len = {gop_len} (fps={fps:.3f})")
        print(f"{'=' * 70}")

        for run_idx in range(1, args.folds + 1):
            try:
                chapter_file, audio_langs, subtitle_langs = _build_metadata(
                    converter, args.input, source_video_info
                )
                output_file = output_root / f"{input_path.stem}_gop{gop_len}_run{run_idx}.mkv"
                result = converter.transcoder.transcode(
                    args.input,
                    str(output_file),
                    args.encoder,
                    chapter_file,
                    audio_langs,
                    subtitle_langs,
                    source_video_info,
                )
            except KeyboardInterrupt:
                print("\n用户中断任务")
                raise SystemExit(1)
            if result.get("aborted"):
                print("\n用户中断任务")
                raise SystemExit(1)
            if not result.get("success"):
                print(f"运行失败: gop_len={gop_len}, run={run_idx}")
                continue

            encode_time = float(result.get("timing", {}).get("encode_time", 0.0))
            size_mb = output_file.stat().st_size / (1024 * 1024)
            bitrate_mbps = (output_file.stat().st_size * 8) / duration_seconds / 1_000_000
            quality = result.get("quality", {})
            vmaf = float(quality.get("vmaf", 0.0) or 0.0)
            ssim = float(quality.get("ssim", 0.0) or 0.0)
            psnr = float(quality.get("psnr", 0.0) or 0.0)
            i_count = float(quality.get("i_count", 0.0) or 0.0)
            i_avg_qp = float(quality.get("i_avg_qp", 0.0) or 0.0)
            i_size_mb = float(quality.get("i_size_mb", 0.0) or 0.0)
            p_count = float(quality.get("p_count", 0.0) or 0.0)
            p_avg_qp = float(quality.get("p_avg_qp", 0.0) or 0.0)
            p_size_mb = float(quality.get("p_size_mb", 0.0) or 0.0)
            idr_count = float(quality.get("idr_count", 0.0) or 0.0)

            results[gop_len]["time"].append(encode_time)
            results[gop_len]["size"].append(size_mb)
            results[gop_len]["bitrate"].append(bitrate_mbps)
            results[gop_len]["vmaf"].append(vmaf)
            results[gop_len]["ssim"].append(ssim)
            results[gop_len]["psnr"].append(psnr)
            results[gop_len]["i_count"].append(i_count)
            results[gop_len]["i_avg_qp"].append(i_avg_qp)
            results[gop_len]["i_size_mb"].append(i_size_mb)
            results[gop_len]["p_count"].append(p_count)
            results[gop_len]["p_avg_qp"].append(p_avg_qp)
            results[gop_len]["p_size_mb"].append(p_size_mb)
            results[gop_len]["idr_count"].append(idr_count)

            print(
                f"Run {run_idx}: time={encode_time:.1f}s, size={size_mb:.2f}MB, "
                f"bitrate={bitrate_mbps:.2f}Mbps, vmaf={vmaf:.2f}, ssim={ssim:.4f}, psnr={psnr:.2f}, "
                f"I={i_count:.0f}@{i_avg_qp:.2f}qp/{i_size_mb:.2f}MB, "
                f"P={p_count:.0f}@{p_avg_qp:.2f}qp/{p_size_mb:.2f}MB, IDR={idr_count:.0f}"
            )

    print(f"\n{'=' * 70}")
    print("汇总(均值 ± 标准差)")
    print(f"{'=' * 70}")
    for gop_len in gop_values:
        time_avg, time_std = _format_stats(results[gop_len]["time"])
        size_avg, size_std = _format_stats(results[gop_len]["size"])
        br_avg, br_std = _format_stats(results[gop_len]["bitrate"])
        vmaf_avg, vmaf_std = _format_stats(results[gop_len]["vmaf"])
        ssim_avg, ssim_std = _format_stats(results[gop_len]["ssim"])
        psnr_avg, psnr_std = _format_stats(results[gop_len]["psnr"])
        i_count_avg, i_count_std = _format_stats(results[gop_len]["i_count"])
        i_avg_qp_avg, i_avg_qp_std = _format_stats(results[gop_len]["i_avg_qp"])
        i_size_avg, i_size_std = _format_stats(results[gop_len]["i_size_mb"])
        p_count_avg, p_count_std = _format_stats(results[gop_len]["p_count"])
        p_avg_qp_avg, p_avg_qp_std = _format_stats(results[gop_len]["p_avg_qp"])
        p_size_avg, p_size_std = _format_stats(results[gop_len]["p_size_mb"])
        idr_count_avg, idr_count_std = _format_stats(results[gop_len]["idr_count"])
        print(
            f"gop_len={gop_len:4d} | time={time_avg:.1f}±{time_std:.1f}s | "
            f"size={size_avg:.2f}±{size_std:.2f}MB | bitrate={br_avg:.2f}±{br_std:.2f}Mbps | "
            f"vmaf={vmaf_avg:.2f}±{vmaf_std:.2f} | ssim={ssim_avg:.4f}±{ssim_std:.4f} | "
            f"psnr={psnr_avg:.2f}±{psnr_std:.2f} | "
            f"I={i_count_avg:.1f}±{i_count_std:.1f}, "
            f"IQP={i_avg_qp_avg:.2f}±{i_avg_qp_std:.2f}, "
            f"ISize={i_size_avg:.2f}±{i_size_std:.2f}MB | "
            f"P={p_count_avg:.1f}±{p_count_std:.1f}, "
            f"PQP={p_avg_qp_avg:.2f}±{p_avg_qp_std:.2f}, "
            f"PSize={p_size_avg:.2f}±{p_size_std:.2f}MB | "
            f"IDR={idr_count_avg:.1f}±{idr_count_std:.1f}"
        )

    _write_html_report(
        output_root,
        input_path.name,
        args.encoder,
        fps,
        gop_values,
        results,
    )


if __name__ == "__main__":
    main()
