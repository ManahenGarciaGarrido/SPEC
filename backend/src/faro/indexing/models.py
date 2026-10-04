"""Embedding models Faro can use, pinned by repository revision, size and SHA-256.

Models are only fetched by the explicit "download model" action
(``faro models download``); loading never touches the network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from faro.datadir import DataDir
from faro.net import download

_HF = "https://huggingface.co"


@dataclass(frozen=True)
class ModelFile:
    remote_path: str
    local_path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelSpec:
    key: str
    fastembed_name: str
    description: str
    dim: int
    repository: str
    revision: str
    files: tuple[ModelFile, ...]
    license: str
    query_prefix: str = ""

    @property
    def size_bytes(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def model_id(self) -> str:
        """Identity stored with the index: changing it forces a full re-index."""
        return f"{self.key}@{self.revision[:12]}"


def _tokenizer_files(repo_files: dict[str, tuple[int, str]]) -> tuple[ModelFile, ...]:
    return tuple(ModelFile(name, name, size, sha) for name, (size, sha) in repo_files.items())


_JINA_REVISION = "516f4baf13dec4ddddda8631e019b5737c8bc250"
_JINA_TOKENIZER = _tokenizer_files(
    {
        "config.json": (1216, "e426aa684c7f9a95c5f020aa855faf93a24f065f5fad0c9e17b124670cabdea6"),
        "special_tokens_map.json": (
            280,
            "06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f",
        ),
        "tokenizer.json": (
            2561316,
            "b01c78a902aa4facb2f47f95449f48e2f7bbfea5d2472ee2f6ce92323c6f86e5",
        ),
        "tokenizer_config.json": (
            493,
            "f477aeb15ff9f78d3c1ddf2361d2b0b8b20cf55220f839f29a37f3a18efddd89",
        ),
    }
)

_QWEN_REVISION = "af95f2c416ffe9379369ad64f9113e865db6112c"
_QWEN_TOKENIZER = _tokenizer_files(
    {
        "config.json": (747, "da2b52e46d1469b9f6ff3a45e2bec36b2bb667de5ea9dd5a076e8bfe3b30cc05"),
        "special_tokens_map.json": (
            613,
            "76862e765266b85aa9459767e33cbaf13970f327a0e88d1c65846c2ddd3a1ecd",
        ),
        "tokenizer.json": (
            11423705,
            "def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a",
        ),
        "tokenizer_config.json": (
            5402,
            "1c45aaa97b2bec1d2e1ab0df53e1b2ed2f9568b871b25ca56095c0b83a5d4e93",
        ),
    }
)

_JINA_ES_REVISION = "8e2d780d8fd38f81ca9123ee28e4c5a968aaf21e"
_JINA_ES_TOKENIZER = _tokenizer_files(
    {
        "config.json": (1503, "1b01dc4ac97fcc8d2fa9ee5d7661a4a70394ac7b8f355f1f0871bbc0f23af009"),
        "special_tokens_map.json": (
            958,
            "f23c8e6099631c233c16d9bf8dab198f610826cdd1b358f270f6d55c1863e857",
        ),
        "tokenizer.json": (
            2637974,
            "5cd8fa360a99a895a4afce83d98131bb74ec2e957ed238f6cdd6107358ca25dc",
        ),
        "tokenizer_config.json": (
            1211,
            "99c5e1cf31def1533447759dca2f1c22853d499c0c73e13d9667ae2b5ff1fa0b",
        ),
    }
)

# Qwen3-Embedding expects an instruction before each query (none for documents).
_QWEN_QUERY_PREFIX = (
    "Instruct: Given a question about a software project, retrieve the source code "
    "or documentation passages that answer it\nQuery:"
)

REGISTRY: dict[str, ModelSpec] = {
    spec.key: spec
    for spec in (
        ModelSpec(
            key="jina-code",
            fastembed_name="jinaai/jina-embeddings-v2-base-code",
            description="Jina v2 base code (fp32): English + 30 programming languages",
            dim=768,
            repository="jinaai/jina-embeddings-v2-base-code",
            revision=_JINA_REVISION,
            files=(
                ModelFile(
                    "onnx/model.onnx",
                    "onnx/model.onnx",
                    641517466,
                    "63363fc178428b74620c6f3780cbc7191883fa5c7f84c0945c45eb5c4256733b",
                ),
                *_JINA_TOKENIZER,
            ),
            license="Apache-2.0",
        ),
        ModelSpec(
            key="jina-code-int8",
            fastembed_name="jinaai/jina-embeddings-v2-base-code",
            description="Jina v2 base code (int8 quantized): English + 30 programming languages",
            dim=768,
            repository="jinaai/jina-embeddings-v2-base-code",
            revision=_JINA_REVISION,
            files=(
                # fastembed looks for onnx/model.onnx for this model name.
                ModelFile(
                    "onnx/model_quantized.onnx",
                    "onnx/model.onnx",
                    161895621,
                    "ed45870251c9f0cf656e78aab0d37a23489066df8a222bb1c8caf8a45f2cb16d",
                ),
                *_JINA_TOKENIZER,
            ),
            license="Apache-2.0",
        ),
        ModelSpec(
            key="jina-es-int8",
            fastembed_name="jinaai/jina-embeddings-v2-base-es",
            description="Jina v2 base es (int8 quantized): bilingual Spanish-English",
            dim=768,
            repository="jinaai/jina-embeddings-v2-base-es",
            revision=_JINA_ES_REVISION,
            files=(
                # fastembed looks for onnx/model.onnx for this model name.
                ModelFile(
                    "onnx/model_quantized.onnx",
                    "onnx/model.onnx",
                    161789773,
                    "5af68309317d5a7a5b63bf1c4e336dc8bd9a9104e8d16eebeb12499f33cb463c",
                ),
                *_JINA_ES_TOKENIZER,
            ),
            license="Apache-2.0",
        ),
        ModelSpec(
            key="qwen3-0.6b-int8",
            fastembed_name="Qwen/Qwen3-Embedding-0.6B-Q",
            description="Qwen3 Embedding 0.6B (int8 quantized): multilingual, code retrieval",
            dim=1024,
            repository="Qdrant/Qwen3-Embedding-0.6B-onnx",
            revision=_QWEN_REVISION,
            files=(
                ModelFile(
                    "onnx/model_quantized.onnx",
                    "onnx/model_quantized.onnx",
                    1120604114,
                    "b39d0623bfc7d2dfc2dcc0d32152c5c5b8d61e9e74679e8222dcce5cf32486b9",
                ),
                *_QWEN_TOKENIZER,
            ),
            license="Apache-2.0",
            query_prefix=_QWEN_QUERY_PREFIX,
        ),
    )
}


class UnknownModelError(KeyError):
    pass


def get(key: str) -> ModelSpec:
    try:
        return REGISTRY[key]
    except KeyError as exc:
        raise UnknownModelError(key) from exc


def _parts(spec: ModelSpec, local_path: str = "") -> tuple[str, ...]:
    base = ("models", "embeddings", spec.key, spec.revision[:12])
    return (*base, *[p for p in local_path.split("/") if p])


def model_parts(spec: ModelSpec) -> tuple[str, ...]:
    """Location of the model below the data directory."""
    return _parts(spec)


def is_installed(datadir: DataDir, spec: ModelSpec) -> bool:
    """All files present with the pinned size (hashes are checked at download time)."""
    return all(datadir.file_size(*_parts(spec, f.local_path)) == f.size for f in spec.files)


def install(
    datadir: DataDir,
    spec: ModelSpec,
    progress: Callable[[download.DownloadProgress], None] | None = None,
    client: download.HttpClient | None = None,
) -> None:
    """Download the model's missing files (explicit, user-started network action)."""
    missing = [f for f in spec.files if datadir.file_size(*_parts(spec, f.local_path)) != f.size]
    download.download_files(
        datadir,
        [
            download.RemoteFile(
                url=f"{_HF}/{spec.repository}/resolve/{spec.revision}/{f.remote_path}",
                sha256=f.sha256,
                size=f.size,
                destination=_parts(spec, f.local_path),
            )
            for f in missing
        ],
        reason=f"download embedding model {spec.key}",
        progress=progress,
        client=client,
    )
