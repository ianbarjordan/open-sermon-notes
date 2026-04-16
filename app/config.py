import os

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
BUILD_VERSION       = "pre-production-v1.0.1"

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
TOP_K               = 5        # Default (minimum) number of chunks shown
MAX_TOP_K           = 50       # Slider ceiling — user can request up to this many results
RRF_K               = 60       # Reciprocal Rank Fusion constant
NPROBE              = 64       # FAISS IVF probe count (higher = slower but more accurate)
CONFIDENCE_THRESHOLD = 0.005   # Minimum RRF score to include a result (RRF max ~0.033 with K=60)
LOW_CONFIDENCE_THRESHOLD = 0.018  # Below this, warn user results may not be relevant
                                   # 0.018 ≈ requires presence in both dense+sparse lists
AUTO_EXPAND_THRESHOLD = 0.023  # Results above this are added even if beyond the slider value
                                # 0.023 ≈ 70% of RRF max — requires strong presence in
                                # both dense and sparse lists

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
MIN_CHUNK_WORDS          = 50   # Discard chunks shorter than this
COMMENTARY_CHUNK_WORDS   = 150  # Target size for commentary/exposition chunks

# ---------------------------------------------------------------------------
# Paths  (all relative to project root — never hardcode absolute paths)
# ---------------------------------------------------------------------------
# SERMON_ROOT is the base directory for the user's raw sermon files (.doc, .docx).
# Empty string at startup — resolved at runtime from data/settings.json.
# NEVER hardcode a path here; that breaks portability to the pastor's machine.
SERMON_ROOT         = ""

DB_PATH             = "data/sermons.db"
FAISS_PATH          = "data/sermons.faiss"
ID_MAP_PATH         = "data/id_map.json"
DOCUMENTS_DIR       = "data/documents"
SETTINGS_PATH       = "data/settings.json"
QUARANTINE_ROOT     = "raw/quarantine"

# Human-readable labels for each quarantine reason bucket
QUARANTINE_LABELS: dict[str, str] = {
    'manual_review':    'Blocked by Word security (.doc files)',
    'duplicates':       'Duplicate files',
    'non_faith':        'Not faith-related content',
    'too_short':        'Too short to index',
    'worship_slides':   'Worship / song slides',
    'sparse_pptx':      'Sparse PowerPoint',
    'filename_flagged': 'Flagged filename',
    'format_pub':       'Publisher format (.pub)',
}
