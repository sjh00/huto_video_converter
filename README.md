# Huto Video Converter

基于 NVEncC 的高性能视频转码工具，专为 NVIDIA 显卡优化。支持将视频转换为 AV1/HEVC 编码 + MKV 容器，同时完整保留原始音轨、字幕和章节信息。胶片颗粒片可选用 SVT-AV1 软件编码器。

## 功能特性

- **硬件加速**：默认基于 NVEncC，利用 NVIDIA 显卡进行高速转码
- **可选软件编码**：`--encoder svt_av1` 使用 SVT-AV1（`tune=0`，默认关闭颗粒合成），适合还想再压胶片颗粒片时使用
- **多格式支持**：支持蓝光文件夹 (BDMV)、MKV、MP4、TS、M2TS 等多种格式
- **智能蓝光处理**：
  - 自动识别蓝光目录结构
  - 自动提取章节信息 (MPLS)
  - 自动识别音轨和字幕语言
  - 筛选主电影、彩蛋、花絮、采访、记录等文件 (智能筛选或>=指定大小的文件)
- **无损保留**：
  - 完整复制所有音轨 (Audio Copy)
  - 完整复制所有字幕 (Subtitle Copy)
  - 完整复制章节信息 (Chapter Copy)
  - 保留 HDR/Dolby Vision 元数据
- **NFO 生成**：
  - 转码完成后为输出视频生成同名 `.nfo`
  - 若待转换视频同目录存在同名 `.nfo`，则复用其中的影片信息，仅将 `fileinfo` 替换为输出文件的真实流信息
  - 否则根据输出文件的真实流信息自动生成
- **质量控制**：
  - 支持 NVENC AV1 (默认)、NVENC HEVC，以及可选 SVT-AV1
  - NVENC 使用 UHQ 调优与 QVBR 码率控制；SVT-AV1 使用 CRF
  - 默认 GOP 长度为 4 秒 (gop-len / keyint = ceil(fps * 4))
  - **内置质量评估**：NVENC 由 NVEncC 计算 VMAF/SSIM/PSNR；SVT-AV1 在转码后用 FFmpeg 计算 VMAF
  - **质量自动取值**：未指定时先测中间约 20 秒片段 (短片直接全片) 并二分搜索。保颗粒时 NVENC 搜 QVBR 18–36、SVT-AV1 搜 CRF 12–22；否则 NVENC 25–45、SVT-AV1 18–32。优先达到目标画质且输出视频码率低于片源（保颗粒 85%，否则 80%），否则可降至最低画质门槛；仍无法明显缩小则提示无需转码
- **易用性**：
  - 自动跳过已处理文件
  - 简洁的命令行接口

## 环境要求

- **硬件**：NVENC 路径需要 NVIDIA 显卡（AV1 编码需 Ada 或更新架构）；`--encoder svt_av1` 走 CPU，不依赖 NVENC
- **软件**：
  - [uv](https://docs.astral.sh/uv/)（用于创建 Python 3.12 环境并启动本项目）
  - [NVEncC](https://github.com/rigaya/NVEnc) **9.33 或更高**（NVENC 路径需加入系统 PATH，或用 `--nvenc-path` 指定）
  - FFmpeg（需要 `ffmpeg` 与 `ffprobe`；`svt_av1` 需要带 `libsvtav1` 的构建）
  - NVIDIA 显卡驱动需支持 NVENC API 13.1（建议使用当前最新驱动；仅软件编码时可忽略）

## 安装

1. 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。

2. 下载并解压 [NVEncC](https://github.com/rigaya/NVEnc/releases)，将 `NVEncC64.exe` 所在目录添加到系统 PATH 环境变量。
   - 或者在运行时通过 `--nvenc-path` 指定路径。

3. 克隆本项目：
   ```bash
   git clone https://github.com/sjh00/huto_video_converter.git
   cd huto_video_converter
   ```

`uv run` 会自动准备 Python 3.12 环境。

## 使用方法

### 基本用法

```bash
uv run video_converter.py <输入文件或目录>
```

未提供参数时，程序会检测项目根目录下的 `input` 目录是否包含视频或蓝光目录，并询问是否批量转码。

### 常用参数

- `-o, --output`: 指定输出文件或目录
- `-e, --encoder`: 视频编码器 (默认 `av1_nvenc`，可选 `hevc_nvenc`、`svt_av1`)
- `-v, --enable-quality-eval`: 启用转换后的质量评估 (VMAF/SSIM/PSNR)
- `-p, --nvenc-path`: 指定 NVEncC64.exe 的路径 (如果未在 PATH 中)
- `--qvbr`: 指定质量值 (NVENC 为 QVBR，`svt_av1` 为 CRF；默认自动)
- `--keep-grain` / `--no-keep-grain`: 是否保留胶片颗粒与纹理（默认保留；SVT-AV1 下关闭颗粒合成）

### 使用示例

1. **转换单个视频文件 (AV1)**：
   ```bash
   uv run video_converter.py movie.mkv
   ```

2. **使用 HEVC 编码**：
   ```bash
   uv run video_converter.py movie.mkv --encoder hevc_nvenc
   ```

3. **使用 SVT-AV1（软件，可选）**：
   ```bash
   uv run video_converter.py movie.mkv --encoder svt_av1
   ```
   自动 CRF 与跳过规则与 NVENC 相同：画质不达标或无法明显缩小则不转。可用 `--qvbr` 指定 CRF，例如 `--qvbr 16`。SVT-AV1 会保留 HDR10 色度信息；杜比视界 RPU 不能像 NVENC 那样原样复制。

4. **转换蓝光目录**：
   支持传入蓝光根目录或 BDMV 目录，自动扫描 BDMV/STREAM 下的 M2TS 文件，智能筛选并转换。
   ```bash
   uv run video_converter.py "D:\Movies\Avatar BluRay"
   ```
   或
   ```bash
   uv run video_converter.py "D:\Movies\Avatar BluRay\BDMV"
   ```

5. **启用质量评估**：
   转码完成后输出 VMAF, SSIM, PSNR 分数。
   ```bash
   uv run video_converter.py movie.mkv --enable-quality-eval
   ```

6. **指定输出目录**：
   ```bash
   uv run video_converter.py movie.mkv -o "E:\Converted"
   ```

7. **无参数批量处理 input**：
   ```bash
   uv run video_converter.py
   ```

## 质量评估说明

开启 `--enable-quality-eval` 后，NVEncC 会在转码过程中计算视频质量指标：

- **VMAF**: Netflix 开发的感知视频质量指标 (0-100)，推荐 93+ 为高质量。
- **SSIM**: 结构相似性 (0-1)，越高越好。
- **PSNR**: 峰值信噪比 (dB)，越高越好。

## 许可证

本项目采用 [MIT License](LICENSE)。
