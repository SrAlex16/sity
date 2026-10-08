> **[ARCHIVED]** This document describes a feature or design that has been removed or superseded. It is preserved for historical reference only.
> 
> **[ARCHIVADO]** Este documento describe una funcionalidad o diseño eliminado o sustituido. Se conserva solo como referencia histórica.

---

# LoRA Training Plan v0

**Status**: Superseded by the current training documentation. See [development/training.md](../../development/training.md)

This document captured the initial LoRA training plan for Gemma 3 4B-IT (v0 — smoke test phase). It was written during early exploration and predates the v1 dataset capture pipeline.

**Original plan summary**:
- Dataset v0: 71 training examples, 30 eval, 50 manual seeds
- Target: style adaptation only (Sity's voice and grammatical gender), not knowledge
- Base model: Gemma 3 4B-IT from Hugging Face (not the Ollama GGUF)
- Tooling: Unsloth preferred, Transformers + PEFT as fallback
- Hyperparameters: LoRA rank 16, LR 2e-4, 1–3 epochs, checkpoint every 25 steps
- VRAM constraint: 8GB on RTX 3060 Ti

The current training workflow, including the v1 continuous dataset capture and synthetic generation pipeline, is documented in `development/training.md`.
