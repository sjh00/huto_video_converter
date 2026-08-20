# Huto Video Converter

基于 NVEncC 的高性能视频转码工具，专为 NVIDIA 显卡优化。支持将视频转换为 AV1/HEVC 编码 + MKV 容器，同时完整保留原始音轨、字幕和章节信息。

## 功能特性

- **硬件加速**：完全基于 NVEncC，利用 NVIDIA 显卡进行高速转码
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
  - 内容基于输出文件的真实流信息自动生成
- **质量控制**：
  - 支持 AV1 (默认) 和 HEVC 编码
  - 使用 QVBR 码率控制模式
  - 默认 GOP 长度为 4 秒 (gop-len = ceil(fps * 4))
  - **内置质量评估**：支持 VMAF、SSIM、PSNR 质量评估 (由 NVEncC 直接计算)
  - **QVBR 自动取值**：未指定时先测中间约 20 秒片段 (短片直接全片)，先用 0，再从 25 到 32 递增，目标 VMAF 97.0 以上 且码率低于原码率；若仍不满足则提示无需转码
- **易用性**：
  - 自动跳过已处理文件
  - 简洁的命令行接口

## 环境要求

- **硬件**：NVIDIA 显卡 (支持 NVENC)
- **软件**：
  - Python 3.7+
  - [NVEncC](https://github.com/rigaya/NVEnc) (必须添加到系统 PATH 或指定路径)
  - FFmpeg 的 `ffprobe` (用于生成 NFO 所需的媒体信息)
  - 显卡驱动需更新到最新版本

## 安装

1. 下载并解压 [NVEncC](https://github.com/rigaya/NVEnc/releases)，将 `NVEncC64.exe` 所在目录添加到系统 PATH 环境变量。
   - 或者在运行时通过 `--nvenc-path` 指定路径。

2. 克隆本项目：
   ```bash
   git clone https://github.com/sjh00/huto_video_converter.git
   cd huto_video_converter
   ```

3. 安装开发依赖 (可选，仅用于代码格式化)：
   ```bash
   pip install -r requirements.txt
   ```

## 使用方法

### 基本用法

```bash
python video_converter.py <输入文件或目录>
```

未提供参数时，程序会检测项目根目录下的 `input` 目录是否包含视频或蓝光目录，并询问是否批量转码。

### 常用参数

- `-o, --output`: 指定输出文件或目录
- `-e, --encoder`: 视频编码器 (默认 `av1_nvenc`，可选 `hevc_nvenc`)
- `-v, --enable-quality-eval`: 启用转换后的质量评估 (VMAF/SSIM/PSNR)
- `-p, --nvenc-path`: 指定 NVEncC64.exe 的路径 (如果未在 PATH 中)
- `--qvbr`: 指定 QVBR 值 (默认：自动，未指定将走自动取值逻辑)

### 使用示例

1. **转换单个视频文件 (AV1)**：
   ```bash
   python video_converter.py movie.mkv
   ```

2. **使用 HEVC 编码**：
   ```bash
   python video_converter.py movie.mkv --encoder hevc_nvenc
   ```

3. **转换蓝光目录**：
   支持传入蓝光根目录或 BDMV 目录，自动扫描 BDMV/STREAM 下的 M2TS 文件，智能筛选并转换。
   ```bash
   python video_converter.py "D:\Movies\Avatar BluRay"
   ```
   或
   ```bash
   python video_converter.py "D:\Movies\Avatar BluRay\BDMV"
   ```

4. **启用质量评估**：
   转码完成后输出 VMAF, SSIM, PSNR 分数。
   ```bash
   python video_converter.py movie.mkv --enable-quality-eval
   ```

5. **指定输出目录**：
   ```bash
   python video_converter.py movie.mkv -o "E:\Converted"
   ```

6. **无参数批量处理 input**：
   ```bash
   python video_converter.py
   ```

## 质量评估说明

开启 `--enable-quality-eval` 后，NVEncC 会在转码过程中计算视频质量指标：

- **VMAF**: Netflix 开发的感知视频质量指标 (0-100)，推荐 93+ 为高质量。
- **SSIM**: 结构相似性 (0-1)，越高越好。
- **PSNR**: 峰值信噪比 (dB)，越高越好。

## 许可证

本项目采用 [MIT License](LICENSE)。
