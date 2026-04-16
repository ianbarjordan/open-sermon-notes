import os

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------
EMBED_MODEL         = "BAAI/bge-small-en-v1.5"
# BGE models require this prefix on query strings (not on corpus chunks)
EMBED_QUERY_PREFIX  = "Represent this sentence for searching relevant passages: "
EMBEDDING_DIM       = 384

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
MODEL_PATH          = "models/Phi-3.5-mini-instruct-Q4_K_M.gguf"
CTX_WINDOW          = 4096
N_THREADS           = max(1, (os.cpu_count() or 2) // 2)
N_GPU_LAYERS        = 0        # Set >0 if CUDA is available at runtime
USE_MMAP            = True

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
TOP_K               = 5        # Default number of chunks returned to the LLM
MAX_TOP_K           = 15       # Maximum allowed result count (slider upper bound)
RRF_K               = 60       # Reciprocal Rank Fusion constant
NPROBE              = 64       # FAISS IVF probe count (higher = slower but more accurate)
CONFIDENCE_THRESHOLD = 0.005   # Minimum RRF score to include a result (RRF max ~0.033 with K=60)
LOW_CONFIDENCE_THRESHOLD = 0.018  # Below this, warn user results may not be relevant
                                   # 0.018 ≈ requires presence in both dense+sparse lists

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
MIN_CHUNK_WORDS          = 50   # Discard chunks shorter than this
COMMENTARY_CHUNK_WORDS   = 150  # Target size for commentary/exposition chunks

# ---------------------------------------------------------------------------
# Paths  (all relative to project root — never hardcode absolute paths)
# ---------------------------------------------------------------------------
DB_PATH             = "data/sermons.db"
FAISS_PATH          = "data/sermons.faiss"
ID_MAP_PATH         = "data/id_map.json"
DOCUMENTS_DIR       = "data/documents"
SETTINGS_PATH       = "data/settings.json"
