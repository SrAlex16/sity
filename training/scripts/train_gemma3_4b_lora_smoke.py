import unsloth  # Must be imported before transformers / trl / peft.

from pathlib import Path

import torch
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer
from unsloth import FastLanguageModel


MODEL_NAME = "/home/alex/models/hf/google-gemma-3-4b-it"
DATA_PATH = "training/data/sity_smoke.jsonl"
OUTPUT_DIR = "training/output/gemma3_4b_lora_smoke"

MAX_SEQ_LENGTH = 1024


def main() -> None:
    print("Loading base model...")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )

    print("Adding LoRA adapters...")

    model = FastLanguageModel.get_peft_model(
        model,
        r=8,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    print("Loading dataset...")

    dataset = load_dataset(
        "json",
        data_files=DATA_PATH,
        split="train",
    )

    print(dataset)

    args = SFTConfig(
        output_dir=OUTPUT_DIR,
        dataset_text_field="text",
        max_length=MAX_SEQ_LENGTH,
        packing=False,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_steps=1,
        max_steps=8,
        learning_rate=2e-4,
        logging_steps=1,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=3407,
        bf16=torch.cuda.is_bf16_supported(),
        fp16=not torch.cuda.is_bf16_supported(),
        save_strategy="no",
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        args=args,
        train_dataset=dataset,
        processing_class=tokenizer,
    )

    print("Starting smoke training...")
    trainer.train()

    print("Saving LoRA adapter...")
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print("Smoke LoRA training OK")
    print("Output:", OUTPUT_DIR)
    print("Memory allocated GB:", round(torch.cuda.memory_allocated() / 1024**3, 2))
    print("Memory reserved GB:", round(torch.cuda.memory_reserved() / 1024**3, 2))


if __name__ == "__main__":
    main()
