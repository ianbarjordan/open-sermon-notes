# Models Directory

This directory stores the quantized LLM used by the sermon-notes app.

## Required Model

**Phi-3.5-mini-instruct-Q4_K_M.gguf**

### Download Instructions

1. Install `huggingface-hub` if not already available:
   ```bash
   .venv/bin/pip install huggingface-hub
   ```

2. Download the model (requires ~2.4 GB disk space):
   ```bash
   .venv/bin/python -c "
   from huggingface_hub import hf_hub_download
   hf_hub_download(
       repo_id='bartowski/Phi-3.5-mini-instruct-GGUF',
       filename='Phi-3.5-mini-instruct-Q4_K_M.gguf',
       local_dir='models/'
   )
   "
   ```

   Or via `huggingface-cli`:
   ```bash
   .venv/bin/huggingface-cli download bartowski/Phi-3.5-mini-instruct-GGUF \
       Phi-3.5-mini-instruct-Q4_K_M.gguf \
       --local-dir models/
   ```

3. Verify the file exists:
   ```bash
   ls -lh models/Phi-3.5-mini-instruct-Q4_K_M.gguf
   ```

## Notes

- `*.gguf` files are gitignored — do not commit them.
- Model path is configured in `app/config.py` → `MODEL_PATH`.
- The app uses `llama-cpp-python` to load the model; see `app/requirements_app.txt`.
- For GPU acceleration, set `N_GPU_LAYERS > 0` in `app/config.py` and rebuild
  `llama-cpp-python` with CUDA support.
