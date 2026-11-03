# Models

| File | What | Trained by | Size | Data |
|---|---|---|---|---|
| `hoi_tcn.pt` | **Small model (trigger)**: per 4-s window, "is the wearer doing something with their hands?" | us (`mnemo/model/train.py`) | 1 MB | EPIC-KITCHENS-100 (research licence) |
| Qwen3-VL-4B-Instruct | **Big model**: writes the diary lines | Alibaba (pre-trained, used as is) | 8.9 GB | downloaded from Hugging Face by the big model service on the GPU machine; not stored here |

`hoi_tcn.pt`: 240k parameters, causal temporal convolutions over hands + object + camera motion.
Test F1 0.529 on EPIC people it never saw (pick-up 0.555, put-down 0.505); threshold 0.6 chosen on validation
people. Copied from `mnemo/models/hoi_tcn.pt` (commit 5bfcdf2). Replace it with any checkpoint of the same
architecture; the trigger service loads whatever `ENGRAM_TRIGGER_MODEL` points to.
