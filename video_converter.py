#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import argparse
import os
from pathlib import Path
from typing import List
from video_converter.converter import ConversionAborted, VideoConverter
from video_converter.bluray import BluRayDetector
from video_converter.constants import Constants
from video_converter.utils import Utils
from video_converter.tools import ExternalToolError, SIGINT_EXIT_CODE, require_tools


def _collect_batch_inputs(input_dir: Path) -> List[str]:
    detector = BluRayDetector()
    inputs = []
    seen = set()

    def add_path(path: Path) -> None:
        path_str = str(path)
        if path_str not in seen:
            seen.add(path_str)
            inputs.append(path_str)

    for root, dirs, files in os.walk(input_dir):
        root_path = Path(root)
        if detector.is_bluray_directory(str(root_path)):
            add_path(root_path)
            dirs[:] = []
            continue
        if root_path.name.upper() == "BDMV" and root_path.parent.exists():
            if detector.is_bluray_directory(str(root_path.parent)):
                add_path(root_path.parent)
                dirs[:] = []
                continue
        if detector.is_tv_series(str(root_path)):
            add_path(root_path)
            dirs[:] = []
            continue
        for file in files:
            if Path(file).suffix.lower() in Constants.VIDEO_EXTENSIONS:
                add_path(root_path / file)
    return inputs


def main():
    parser = argparse.ArgumentParser(
        description="将视频转换为 AV1/HEVC + MKV 容器，并复制音轨/字幕（默认 NVEncC，可选 SVT-AV1）"
    )
    parser.add_argument(
        "input",
        nargs="*",
        help="输入视频文件/目录",
    )
    parser.add_argument("-o", "--output", help="输出文件或目录")
    parser.add_argument(
        "-e", "--encoder",
        default=Constants.DEFAULT_ENCODER,
        choices=list(Constants.ENCODER_NAMES.keys()),
        help=f"视频编码器(默认: {Constants.DEFAULT_ENCODER}，可选: {', '.join(Constants.ENCODER_NAMES.keys())})",
    )
    parser.add_argument(
        "-v", "--enable-quality-eval",
        action="store_true",
        default=False,
        help="转换时启用质量评估（VMAF / SSIMU2 / SSIM / PSNR）",
    )
    parser.add_argument(
        "-p", "--nvenc-path",
        default=None,
        help="NVEncC64 可执行文件路径(默认: 自动检测)",
    )
    parser.add_argument(
        "-q",
        "--qvbr",
        type=int,
        help="指定质量值（NVENC: QVBR；svt_av1: CRF。默认自动）",
    )
    parser.add_argument(
        "-n", "--no-qp-max-limit",
        action="store_true",
        default=False,
        help="不设置 qp-max 限制，允许 QVBR 进一步降低码率",
    )
    parser.add_argument(
        "-t", "--test",
        action="store_true",
        default=False,
        help="抽取视频中间 20 秒进行测试，仅支持单个视频",
    )
    parser.add_argument(
        "-z", "--keep-default-zh-audio",
        action="store_true",
        default=False,
        help="仅复制默认音轨和国语音轨",
    )
    parser.add_argument(
        "--keep-grain",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="保留胶片颗粒与纹理（NVENC 关闭 UHQ 时域滤波；svt_av1 使用 VQ 且关闭颗粒合成。默认开启）",
    )
    parser.add_argument(
        "--min-bluray-size",
        type=float,
        default=Constants.MIN_BLURAY_FILE_SIZE_MB,
        metavar="MB",
        help=(
            "蓝光 STREAM 片段小于该体积（MB）则跳过不处理，"
            f"默认 {Constants.MIN_BLURAY_FILE_SIZE_MB}。"
            "等于该体积的片段仍会处理。设为 0 则不按体积跳过。"
        ),
    )
    parser.add_argument(
        "--force-nfo",
        action="store_true",
        default=False,
        help=(
            "强制生成 NFO 文件。默认仅当片源有同名 NFO 时复用并更新 fileinfo；"
            "开启后，若片源没有 NFO 则基于成片信息生成一个新的 NFO。"
        ),
    )

    args = parser.parse_args()

    try:
        args.nvenc_path = require_tools(args.nvenc_path, args.encoder)
    except ExternalToolError as exc:
        print(f"错误: {exc}")
        sys.exit(exc.exit_code)
    if args.qvbr is not None and args.qvbr <= 0:
        print("错误: qvbr 必须为正整数")
        sys.exit(1)
    if args.min_bluray_size < 0:
        print("错误: --min-bluray-size 不能为负数")
        sys.exit(1)

    if not args.input or args.input == ["input"]:
        input_dir = Path(__file__).parent / "input"
        batch_inputs = _collect_batch_inputs(input_dir) if input_dir.exists() else []
        if batch_inputs:
            if args.input != ["input"]:
                choice = input("检测到 input 目录存在视频，是否批量转码? (Y/n): ").strip().lower()
                if choice in ("n", "no", "否", "不", "0"):
                    sys.exit(0)
                else:
                    args.input = batch_inputs
            else:
                args.input = batch_inputs
        else:
            print("错误: 未指定输入")
            parser.print_help()
            sys.exit(1)

    if args.test:
        if len(args.input) != 1:
            print("错误: --test 仅支持单个视频")
            sys.exit(1)
        input_path = Path(args.input[0])
        if not input_path.exists() or not input_path.is_file():
            print("错误: --test 仅支持视频文件")
            sys.exit(1)
    if len(args.input) > 1 and args.output and not args.test:
        output_path = Path(args.output)
        if output_path.suffix:
            print("错误: 多输入时输出必须为目录")
            sys.exit(1)

    converter = VideoConverter(
        args.nvenc_path,
        args.enable_quality_eval,
        args.no_qp_max_limit,
        args.keep_default_zh_audio,
        args.keep_grain,
        args.min_bluray_size,
        args.force_nfo,
    )

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    def result_dir() -> Path:
        if args.output:
            output_path = Path(args.output)
            if output_path.suffix and (len(args.input) == 1 or args.test):
                parent = output_path.parent
                return parent if str(parent) else Path(".")
            return output_path
        return Utils.get_output_dir()

    def write_result() -> None:
        if args.test:
            return
        converter.write_convert_result(str(result_dir()), args.encoder)

    if args.test:
        try:
            success = converter.test_encode(
                str(Path(args.input[0])),
                args.output,
                args.encoder,
                args.qvbr,
            )
        except (ConversionAborted, KeyboardInterrupt):
            sys.exit(SIGINT_EXIT_CODE)
        sys.exit(0 if success else 1)

    total = len(args.input)
    specified_inputs = list(args.input)

    def rel(path: str) -> str:
        return Utils.display_path(path, specified_inputs)

    def format_success(item: dict) -> str:
        line = f"- {rel(str(item['path']))}"
        ratio = item.get("ratio")
        if ratio is not None:
            line += f"  压缩比 {float(ratio) * 100:.1f}%"
        vmaf = item.get("vmaf")
        if vmaf is not None:
            line += f"  VMAF={float(vmaf):.2f}"
        ssimu2 = item.get("ssimu2")
        if ssimu2 is not None:
            line += f"  SSIMU2={float(ssimu2):.2f}"
        return line

    aborted = False
    try:
        for idx, input_path in enumerate(args.input, 1):
            if not Path(input_path).exists():
                print(f"错误: 未找到输入: {input_path}")
                converter._record_fail(input_path)
                continue

            print(f"\n{'=' * 70}")
            print(f"[{idx}/{total}] 正在转换: {Path(input_path).name}")
            print(f"{'=' * 70}")

            fail_before = len(converter.failed_files)
            converter.convert(
                input_path,
                args.output,
                args.encoder,
                args.qvbr,
            )
            new_fails = len(converter.failed_files) - fail_before
            if new_fails == 0:
                print(f"\n{GREEN}转换完成!{RESET}")
            else:
                print(f"\n{RED}有文件转换失败{RESET}")
    except (ConversionAborted, KeyboardInterrupt):
        aborted = True

    if total > 0:
        success_items = converter.succeeded_files
        skip_count = converter.skip_count
        skipped_files = converter.skipped_files
        filtered_small = converter.filtered_small_files
        failed_files = converter.failed_files
        success_count = len(success_items)
        fail_count = len(failed_files)
        copied = set(converter.copied_on_skip)
        parts = [f"{GREEN}{success_count} 成功{RESET}"]
        if skip_count > 0:
            parts.append(f"{YELLOW}{skip_count} 跳过{RESET}")
        if filtered_small:
            parts.append(f"{YELLOW}{len(filtered_small)} 过滤{RESET}")
        if fail_count > 0:
            parts.append(f"{RED}{fail_count} 失败{RESET}")
        print(f"\n汇总: {', '.join(parts)}")
        if success_items:
            print(f"\n{GREEN}成功列表:{RESET}")
            for item in success_items:
                print(format_success(item))
        if skipped_files:
            print(f"\n{YELLOW}跳过列表:{RESET}")
            for item in skipped_files:
                extra = "  (已复制)" if item in copied else ""
                print(f"- {rel(item)}{extra}")
        if filtered_small:
            threshold = converter.min_bluray_size_mb
            print(f"\n{YELLOW}过滤列表（小于 {threshold:g} MB）:{RESET}")
            for item in filtered_small:
                size_text = VideoConverter._format_mb(int(item.get("size") or 0))
                print(f"- {rel(str(item['path']))}  {size_text}")
        if failed_files:
            print(f"\n{RED}失败列表:{RESET}")
            for item in failed_files:
                print(f"- {rel(item)}")

    write_result()
    if aborted:
        sys.exit(SIGINT_EXIT_CODE)
    if converter.failed_files:
        sys.exit(1)


if __name__ == "__main__":
    main()
