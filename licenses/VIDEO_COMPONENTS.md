# Video components in the Windows package

PyAV 16.0.1 uses the PyAV-FFmpeg **8.0-2** Windows AMD64 build. DLLs are
distributed unmodified, apart from upstream wheel relocation. This application
does not restrict replacement of those dynamic libraries or reverse engineering
for debugging modifications to LGPL-covered components.

- PyAV source and BSD license: https://github.com/PyAV-Org/PyAV/tree/v16.0.1
- Exact vendor recipe, dependency source URLs, hashes and patches:
  https://github.com/PyAV-Org/pyav-ffmpeg/tree/8.0-2
- FFmpeg 8.0 source: https://ffmpeg.org/releases/ffmpeg-8.0.tar.xz
  SHA256 `b2751fccb6cc4c77708113cd78b561059b6fa904b24162fa0be2d60273d27b8e`.
- Upstream distribution guidance: https://ffmpeg.org/legal.html

The portable archive includes FFmpeg's source archive, its LGPL/GPL license texts,
and the vendor recipe/patch archive in `licenses/FFmpeg`. The recipe lists
corresponding source URLs and hashes for the codec dependencies, including x264
and x265. Their licenses are separate from PyAV's BSD license. A commercial-use
permission is not an exemption from copyleft, attribution or patent obligations.
This notice is not a comprehensive legal clearance of the full stack.

No original bank videos, personal frames, API keys or credentials are distributed
as part of these component sources.
