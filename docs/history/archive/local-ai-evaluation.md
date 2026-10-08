> **[ARCHIVED]** This document describes a feature or design that has been removed or superseded. It is preserved for historical reference only.
> 
> **[ARCHIVADO]** Este documento describe una funcionalidad o diseño eliminado o sustituido. Se conserva solo como referencia histórica.

---

# Local AI Evaluation

**Status**: Conclusions formalized as ADR-0005. See [decisions/0005-local-ai.md](../../decisions/0005-local-ai.md)

This document contains the detailed evaluation of local LLM models (served via Ollama) as a possible conversational backend for Sity. It includes diagnostic results, candidate ranking, risk notes, and the LoRA training plan that emerged from the evaluation.

**Key conclusions**:
- Pi 4B as LLM engine: rejected (too slow, quality insufficient)
- PC (RTX 3060 Ti) as Local AI Worker over LAN: viable
- `gemma3:4b-it-qat`: primary LoRA fine-tuning candidate
- `qwen2.5:7b`: rejected (ideological bias)
- `llama3.1:8b`: rejected (false safety triggers on mild profanity in Spain Spanish)

For the training plan, see: [development/training.md](../../development/training.md)
