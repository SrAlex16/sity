#!/usr/bin/env python3
"""
check_cuda_env.py
─────────────────
Preflight de entorno para entrenamiento LoRA Sity v0.
Verifica Python, torch, CUDA, VRAM y dependencias de training.

Uso:
  python training/check_cuda_env.py
"""
import importlib
import sys


def _ver(pkg: str) -> str:
    """Devuelve versión del paquete o 'NOT INSTALLED'."""
    try:
        m = importlib.import_module(pkg.replace("-", "_"))
        return getattr(m, "__version__", "installed (no __version__)")
    except ImportError:
        return "NOT INSTALLED"


def section(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def main() -> None:
    print("Sity LoRA v0 — CUDA / training env preflight")

    # ── Python ────────────────────────────────────────
    section("Python")
    print(f"  version : {sys.version}")
    print(f"  prefix  : {sys.prefix}")

    # ── PyTorch ───────────────────────────────────────
    section("PyTorch")
    torch_ver = _ver("torch")
    print(f"  torch   : {torch_ver}")

    if torch_ver == "NOT INSTALLED":
        print("  CUDA    : N/A (torch no instalado)")
        print("  GPU     : N/A")
        print("  VRAM    : N/A")
    else:
        import torch
        print(f"  CUDA available : {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"  CUDA version   : {torch.version.cuda}")
            n = torch.cuda.device_count()
            print(f"  GPU count      : {n}")
            for i in range(n):
                name = torch.cuda.get_device_name(i)
                props = torch.cuda.get_device_properties(i)
                vram_gb = props.total_memory / (1024 ** 3)
                print(f"  GPU [{i}]        : {name}")
                print(f"  VRAM [{i}]       : {vram_gb:.1f} GB")
        else:
            print("  WARNING: CUDA no disponible — revisar driver/WSL2 config")
            if hasattr(torch.version, "cuda"):
                print(f"  torch compiled with CUDA : {torch.version.cuda}")

    # ── Dependencias de training ──────────────────────
    section("Training dependencies")
    deps = [
        ("transformers",   "transformers"),
        ("peft",           "peft"),
        ("bitsandbytes",   "bitsandbytes"),
        ("trl",            "trl"),
        ("datasets",       "datasets"),
        ("accelerate",     "accelerate"),
        ("unsloth",        "unsloth"),
        ("axolotl",        "axolotl"),
    ]
    max_len = max(len(label) for label, _ in deps)
    for label, pkg in deps:
        ver = _ver(pkg)
        status = ver if ver != "NOT INSTALLED" else "— NOT INSTALLED"
        print(f"  {label:<{max_len}} : {status}")

    # ── Resumen ───────────────────────────────────────
    section("Resumen")
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
    except ImportError:
        cuda_ok = False

    has_torch       = _ver("torch") != "NOT INSTALLED"
    has_transformers= _ver("transformers") != "NOT INSTALLED"
    has_peft        = _ver("peft") != "NOT INSTALLED"
    has_bnb         = _ver("bitsandbytes") != "NOT INSTALLED"
    has_trl         = _ver("trl") != "NOT INSTALLED"
    has_unsloth     = _ver("unsloth") != "NOT INSTALLED"

    stack_peft_ok    = has_torch and has_transformers and has_peft and has_bnb and has_trl
    stack_unsloth_ok = has_torch and has_unsloth

    print(f"  CUDA listo            : {'YES' if cuda_ok else 'NO — ver arriba'}")
    print(f"  Stack PEFT listo      : {'YES' if stack_peft_ok else 'NO — faltan paquetes'}")
    print(f"  Stack Unsloth listo   : {'YES' if stack_unsloth_ok else 'NO — unsloth no instalado'}")

    if not cuda_ok:
        print("\n  ACCIÓN REQUERIDA: torch no ve CUDA.")
        print("  En WSL2: verificar que nvidia-smi funciona en el host Windows")
        print("  y que el driver WSL2 está instalado (>=470.x).")
    if not has_torch:
        print("\n  ACCIÓN REQUERIDA: instalar torch con soporte CUDA:")
        print("  pip install torch --index-url https://download.pytorch.org/whl/cu121")
    if cuda_ok and not stack_peft_ok:
        print("\n  Para stack PEFT:")
        print("  pip install transformers peft bitsandbytes trl accelerate datasets")
    if cuda_ok and not stack_unsloth_ok:
        print("\n  Para Unsloth (recomendado si soporta Gemma 3 4B):")
        print("  pip install unsloth")


if __name__ == "__main__":
    main()
