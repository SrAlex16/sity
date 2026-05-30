from unsloth import FastLanguageModel
import torch

model_name = "/home/alex/models/hf/google-gemma-3-4b-it"

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=model_name,
    max_seq_length=2048,
    dtype=None,
    load_in_4bit=True,
)

print("Loaded OK")
print("CUDA:", torch.cuda.is_available())
print("GPU:", torch.cuda.get_device_name(0))
print("Memory allocated GB:", round(torch.cuda.memory_allocated() / 1024**3, 2))
print("Memory reserved GB:", round(torch.cuda.memory_reserved() / 1024**3, 2))
