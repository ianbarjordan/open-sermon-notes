"""Tests for app/llm.py — GPU detection and LLM wrapper."""
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.llm as llm_module


# ---------------------------------------------------------------------------
# detect_n_gpu_layers
# ---------------------------------------------------------------------------

def test_config_override_takes_precedence():
    """If N_GPU_LAYERS is set non-zero in config, return it immediately."""
    with mock.patch.object(llm_module, 'N_GPU_LAYERS', 16):
        result = llm_module.detect_n_gpu_layers()
    assert result == 16


def test_llama_cpp_gpu_offload_supported():
    """llama_cpp.llama_supports_gpu_offload() returning True → _GPU_LAYERS_DEFAULT."""
    mock_llama_cpp = mock.MagicMock()
    mock_llama_cpp.llama_supports_gpu_offload.return_value = True
    with mock.patch.object(llm_module, 'N_GPU_LAYERS', 0), \
         mock.patch.dict(sys.modules, {'llama_cpp': mock_llama_cpp}):
        result = llm_module.detect_n_gpu_layers()
    assert result == llm_module._GPU_LAYERS_DEFAULT


def test_llama_cpp_gpu_offload_not_supported():
    """llama_cpp.llama_supports_gpu_offload() returning False → 0."""
    mock_llama_cpp = mock.MagicMock()
    mock_llama_cpp.llama_supports_gpu_offload.return_value = False
    with mock.patch.object(llm_module, 'N_GPU_LAYERS', 0), \
         mock.patch.dict(sys.modules, {'llama_cpp': mock_llama_cpp}):
        result = llm_module.detect_n_gpu_layers()
    assert result == 0


def test_llama_cpp_no_offload_attr_falls_through_to_torch():
    """llama_cpp installed but no llama_supports_gpu_offload attr → try torch."""
    mock_llama_cpp = mock.MagicMock(spec=[])  # no attributes
    mock_torch = mock.MagicMock()
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.get_device_name.return_value = "NVIDIA RTX 3080"
    with mock.patch.object(llm_module, 'N_GPU_LAYERS', 0), \
         mock.patch.dict(sys.modules, {'llama_cpp': mock_llama_cpp, 'torch': mock_torch}):
        result = llm_module.detect_n_gpu_layers()
    assert result == llm_module._GPU_LAYERS_DEFAULT


def test_torch_cuda_available():
    """torch.cuda.is_available() True when llama_cpp not importable → GPU layers."""
    mock_torch = mock.MagicMock()
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.get_device_name.return_value = "NVIDIA GTX 1080"
    with mock.patch.object(llm_module, 'N_GPU_LAYERS', 0), \
         mock.patch.dict(sys.modules, {'llama_cpp': None, 'torch': mock_torch}):
        result = llm_module.detect_n_gpu_layers()
    assert result == llm_module._GPU_LAYERS_DEFAULT


def test_torch_cuda_not_available():
    """torch installed but no CUDA device → 0."""
    mock_torch = mock.MagicMock()
    mock_torch.cuda.is_available.return_value = False
    with mock.patch.object(llm_module, 'N_GPU_LAYERS', 0), \
         mock.patch.dict(sys.modules, {'llama_cpp': None, 'torch': mock_torch}):
        result = llm_module.detect_n_gpu_layers()
    assert result == 0


def test_neither_llama_cpp_nor_torch_returns_zero():
    """No GPU detection possible → 0."""
    with mock.patch.object(llm_module, 'N_GPU_LAYERS', 0), \
         mock.patch.dict(sys.modules, {'llama_cpp': None, 'torch': None}):
        result = llm_module.detect_n_gpu_layers()
    assert result == 0


def test_gpu_layers_default_is_32():
    """Safety check: the default GPU layer count should be 32 (all of Phi-3.5-mini)."""
    assert llm_module._GPU_LAYERS_DEFAULT == 32


# ---------------------------------------------------------------------------
# _format_chunk / _build_user_message (prompt injection defence)
# ---------------------------------------------------------------------------

def test_format_chunk_wraps_in_delimiters():
    chunk = {'title': 'Grace', 'scripture_ref': 'John 3:16', 'date': '2020',
             'source_file': 'sermons/grace.docx', 'text': 'God so loved the world.'}
    result = llm_module._format_chunk(1, chunk)
    assert '### EXCERPT START ###' in result
    assert '### EXCERPT END ###' in result
    assert 'Grace' in result
    assert 'God so loved the world.' in result


def test_format_chunk_truncates_long_text():
    long_text = 'x' * 2000
    chunk = {'title': 'T', 'text': long_text}
    result = llm_module._format_chunk(1, chunk, max_text_chars=100)
    assert len(result) < 500  # well under 2000 chars


def test_build_user_message_limits_chunks():
    chunks = [
        {'title': f'Sermon {i}', 'text': 'Content ' * 20, 'score': 0.9 - i * 0.1}
        for i in range(10)
    ]
    msg = llm_module._build_user_message("grace", chunks)
    # Should contain at most _LLM_MAX_CHUNKS excerpts
    assert msg.count('### EXCERPT START ###') <= llm_module._LLM_MAX_CHUNKS
