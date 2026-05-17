#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import argparse
import os
from pathlib import Path
from typing import List
from video_converter.converter import VideoConverter
from video_converter.bluray import BluRayDetector
from video_converter.constants import Constants
from video_converter.utils import Utils


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
        if root_path.name == "BDMV" and root_path.parent.exists():
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
        description="将视频转换为 AV1/HEVC + MKV 容器，并复制音轨/字幕 (使用 NVEncC)"
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
        help="转换时启用 VMAF/SSIM/PSNR 质量评估 (NVEncC 内置)",
    )
    parser.add_argument(
        "-p", "--nvenc-path",
        default=None,
        help="NVEncC64 可执行文件路径(默认: 自动检测)",
    )
    parser.add_argument("-q", "--qvbr", type=int, help="指定 QVBR 值 (默认：自动)")
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

    args = parser.parse_args()

    # Auto-detect tools if not provided
    args.nvenc_path = args.nvenc_path or Utils.find_tool("NVEncC64")
    if args.qvbr is not None and args.qvbr <= 0:
        print("错误: qvbr 必须为正整数")
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
    )

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    if args.test:
        success = converter.test_encode(
            str(Path(args.input[0])),
            args.output,
            args.encoder,
            args.qvbr,
        )
        sys.exit(0 if success else 1)

    total = len(args.input)
    success_count = 0
    fail_count = 0
    failed_files = []
    for idx, input_path in enumerate(args.input, 1):
        if not Path(input_path).exists():
            print(f"错误: 未找到输入: {input_path}")
            fail_count += 1
            failed_files.append(input_path)
            continue

        print(f"\n{'=' * 70}")
        print(f"[{idx}/{total}] 正在转换: {Path(input_path).name}")
        print(f"{'=' * 70}")

        success = converter.convert(
            input_path,
            args.output,
            args.encoder,
            args.qvbr,
        )

        if success:
            print(f"\n{GREEN}转换完成!{RESET}")
            success_count += 1
        else:
            print(f"\n{RED}转换失败!{RESET}")
            fail_count += 1
            failed_files.append(input_path)

    if total > 0:
        skip_count = converter.skip_count
        skipped_files = converter.skipped_files
        if fail_count == 0:
            if skip_count > 0:
                print(
                    f"\n{GREEN}汇总: {success_count}/{total} 成功{RESET}, "
                    f"{YELLOW}{skip_count} 跳过{RESET}"
                )
            else:
                print(f"\n{GREEN}汇总: {success_count}/{total} 成功{RESET}")
        else:
            if skip_count > 0:
                print(
                    f"\n汇总: {success_count}/{total} 成功, "
                    f"{YELLOW}{skip_count} 跳过{RESET}, "
                    f"{YELLOW}{fail_count} 失败{RESET}"
                )
            else:
                print(
                    f"\n汇总: {success_count}/{total} 成功, {YELLOW}{fail_count} 失败{RESET}"
                )
        if skipped_files:
            print(f"\n{YELLOW}跳过列表:{RESET}")
            for item in skipped_files:
                print(f"- {item}")
        if failed_files:
            print(f"\n{RED}失败列表:{RESET}")
            for item in failed_files:
                print(f"- {item}")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
