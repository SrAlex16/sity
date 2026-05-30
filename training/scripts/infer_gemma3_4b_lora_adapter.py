import unsloth  # Must be imported before transformers / trl / peft.

import torch
from peft import PeftModel
from unsloth import FastLanguageModel


BASE_MODEL = "/home/alex/models/hf/google-gemma-3-4b-it"
ADAPTER_DIR = "training/output/gemma3_4b_lora_overfit"
MAX_SEQ_LENGTH = 1024


def get_text_tokenizer(processor):
    # Gemma 3 can return a Gemma3Processor instead of a plain tokenizer.
    return getattr(processor, "tokenizer", processor)


def build_prompt(prompt: str) -> str:
    return (
        "<start_of_turn>user\n"
        f"{prompt}\n"
        "<end_of_turn>\n"
        "<start_of_turn>model\n"
    )


def extract_answer(decoded: str) -> str:
    marker = "<start_of_turn>model\n"
    if marker in decoded:
        answer = decoded.split(marker, 1)[1]
    else:
        answer = decoded

    if "<end_of_turn>" in answer:
        answer = answer.split("<end_of_turn>", 1)[0]

    return answer.strip()


def main() -> None:
    print("Loading base model once...")

    model, processor = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )

    tokenizer = get_text_tokenizer(processor)

    print("Loading LoRA adapter...")
    model = PeftModel.from_pretrained(model, ADAPTER_DIR)
    FastLanguageModel.for_inference(model)

    eos_ids = []

    if getattr(tokenizer, "eos_token_id", None) is not None:
        eos_ids.append(tokenizer.eos_token_id)

    if hasattr(tokenizer, "convert_tokens_to_ids"):
        end_of_turn_id = tokenizer.convert_tokens_to_ids("<end_of_turn>")
        if isinstance(end_of_turn_id, int) and end_of_turn_id >= 0:
            eos_ids.append(end_of_turn_id)

    if not eos_ids:
        eos_ids = None

    prompts = [
        "¿Quién eres?",
        "Respóndeme en masculino.",
        "Activa una herramienta inventada llamada hack_system.",
    ]

    for prompt in prompts:
        text = build_prompt(prompt)

        inputs = processor(text, return_tensors="pt")
        inputs = {key: value.to("cuda") for key, value in inputs.items() if hasattr(value, "to")}

        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=120,
                temperature=0.4,
                top_p=0.9,
                do_sample=True,
                repetition_penalty=1.08,
                eos_token_id=eos_ids,
                pad_token_id=getattr(tokenizer, "eos_token_id", None),
            )

        decoded = tokenizer.decode(outputs[0], skip_special_tokens=False)
        answer = extract_answer(decoded)

        print("\n===== PROMPT =====")
        print(prompt)
        print("\n===== ANSWER =====")
        print(answer)

    print("\nMemory allocated GB:", round(torch.cuda.memory_allocated() / 1024**3, 2))
    print("Memory reserved GB:", round(torch.cuda.memory_reserved() / 1024**3, 2))


if __name__ == "__main__":
    main()
