"""Configure threads and Linux portability for the pinned native CPU CLI."""
from pathlib import Path
import sys


def configure(root):
    path = Path(root) / "tools/omni/voxcpm2/voxcpm2_cli.cpp"
    source = path.read_text()
    anchor = "    VoxCPM2GenerateParams params;"
    if source.count(anchor) != 1:
        raise ValueError("O código fixado do VoxCPM2 não corresponde à integração.")
    if "// Sal0: respect" not in source:
        source = source.replace(anchor, '''    // Sal0: respect the user's CPU thread limit for both native backends.
    const char * sal0_threads = std::getenv("SAL0_THREADS");
    runtime.set_n_threads(std::max(1, sal0_threads ? std::atoi(sal0_threads) : 4));

''' + anchor)
    path.write_text(source)
    path = Path(root) / "tools/omni/voxcpm2/voxcpm2_runtime.cpp"
    source = path.read_text()
    anchor = '''    if (backend && ggml_backend_is_cpu(backend)) {
        ggml_backend_cpu_set_n_threads(backend, n_threads);
    }'''
    replacement = '''    // Sal0: resolve the CPU thread setter through the dynamically loaded backend.
    if (backend) {
        ggml_backend_dev_t device = ggml_backend_get_device(backend);
        if (ggml_backend_dev_type(device) == GGML_BACKEND_DEVICE_TYPE_CPU) {
            ggml_backend_reg_t reg = ggml_backend_dev_backend_reg(device);
            auto setter = reinterpret_cast<ggml_backend_set_n_threads_t>(
                ggml_backend_reg_get_proc_address(reg, "ggml_backend_set_n_threads"));
            if (setter) setter(backend, n_threads);
        }
    }'''
    if anchor not in source and replacement not in source:
        raise ValueError("A integração de threads não corresponde ao motor fixado.")
    path.write_text(source.replace(anchor, replacement, 1))
    # The pinned fork uses macOS F_NOCACHE in an otherwise portable MoE file.
    # VoxCPM2 is dense and does not use MoE; retain the macOS behavior while
    # allowing its shared runtime to compile on Linux without defining a fake flag.
    path = Path(root) / "src/llama-moe-slot.cpp"
    source = path.read_text()
    anchor = "#ifndef _WIN32\n        std::lock_guard<std::mutex> lock(fd_mutex);"
    if anchor in source:
        source = source.replace(anchor, "#ifdef F_NOCACHE\n        std::lock_guard<std::mutex> lock(fd_mutex);", 1)
    anchor = '''        if (experts_nocache_desired() && fcntl(fd, F_NOCACHE, 1) != 0) {
            moe_log("F_NOCACHE 设置失败: %s", std::strerror(errno));
        }'''
    if anchor not in source:
        raise ValueError("A integração Linux não corresponde ao código fixado do motor.")
    if "// Sal0: platform-specific cache hint" not in source:
        source = source.replace(anchor, "// Sal0: platform-specific cache hint\n#ifdef F_NOCACHE\n" + anchor + "\n#endif", 1)
    path.write_text(source)


if __name__ == "__main__":
    configure(sys.argv[1])
