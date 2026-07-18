# Third-Party Notices

## XiaoZhi ESP32 Server

`xiaozhi_server/` is a complete import of `main/xiaozhi-server` from the pinned XiaoZhi ESP32 Server commit recorded in `third_party/xiaozhi-esp32-server/UPSTREAM.json`. The governing upstream repository license is the copied [MIT license](third_party/xiaozhi-esp32-server/LICENSE).

The import review found no more-specific included license or notice file for the retained `music/*.mp3` files, bundled ONNX model files, or configuration assets. They are retained as upstream-distributed assets under the repository-level MIT notice; this record makes no separate ownership or licensing claim beyond the notices included in the pinned source.

`xiaozhi_server/config.yaml` has one security-only change: the upstream shared weather API key is blanked. The reviewed reason and exact hashes are recorded in the patch reason and patch manifest files.
