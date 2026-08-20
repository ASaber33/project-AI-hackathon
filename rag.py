# Suppress TensorFlow warnings and disable oneDNN for compatibility
import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import re
import hashlib
import uuid

from pathlib import Path

import pdfplumber

from qdrant_client import QdrantClient

from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from dotenv import load_dotenv


# =========================================================
# ENV
# =========================================================

BASE_DIR = Path(
    __file__
).resolve().parent

load_dotenv(
    BASE_DIR / ".env"
)


# =========================================================
# CONFIG
# =========================================================

DATA_DIR = (
    BASE_DIR
    / "data"
)

QDRANT_URL = os.getenv(
    "QDRANT_URL",
    ""
)

QDRANT_API_KEY = os.getenv(
    "QDRANT_API_KEY",
    ""
)

COLLECTION_NAME = os.getenv(
    "QDRANT_COLLECTION",
    "medical_guidelines"
)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2"
)

CHUNK_SIZE = int(
    os.getenv(
        "CHUNK_SIZE",
        "900"
    )
)

CHUNK_OVERLAP = int(
    os.getenv(
        "CHUNK_OVERLAP",
        "150"
    )
)

TOP_K = int(
    os.getenv(
        "TOP_K",
        "6"
    )
)


# =========================================================
# GLOBAL OBJECTS
# =========================================================

_embedder = None
_qdrant = None


# =========================================================
# EMBEDDING MODEL
# =========================================================

def get_embedder():

    global _embedder

    if _embedder is None:

        print(
            "[RAG] Loading embedding model:",
            EMBEDDING_MODEL
        )

        from sentence_transformers import SentenceTransformer
        
        _embedder = SentenceTransformer(
            EMBEDDING_MODEL
        )

    return _embedder


# =========================================================
# QDRANT
# =========================================================

def get_qdrant():

    global _qdrant

    if _qdrant is None:

        if not QDRANT_URL:

            raise RuntimeError(
                "QDRANT_URL is missing from .env"
            )

        _qdrant = QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY
            if QDRANT_API_KEY
            else None,
            timeout=60,
        )

    return _qdrant


# =========================================================
# PDF LIST
# =========================================================

def list_pdfs():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    return sorted(
        DATA_DIR.glob(
            "*.pdf"
        )
    )


# =========================================================
# CLEAN TEXT
# =========================================================

def clean_text(text):

    text = text.replace(
        "\x00",
        " "
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# =========================================================
# EXTRACT PDF PAGES
# =========================================================

def extract_pages(path):

    pages = []

    with pdfplumber.open(path) as pdf:

        for page_number, page in enumerate(
            pdf.pages,
            start=1
        ):

            text = clean_text(
                page.extract_text()
                or ""
            )

            if text:

                pages.append(
                    {
                        "source": path.name,
                        "page": page_number,
                        "text": text,
                    }
                )

    return pages


# =========================================================
# CHUNK TEXT
# =========================================================

def create_chunks(text):

    words = text.split()

    output = []

    start = 0

    while start < len(words):

        end = min(
            start + CHUNK_SIZE,
            len(words)
        )

        chunk = " ".join(
            words[start:end]
        ).strip()

        if chunk:

            output.append(
                chunk
            )

        if end >= len(words):

            break

        start = max(
            end - CHUNK_OVERLAP,
            start + 1
        )

    return output


# =========================================================
# CREATE DOCUMENTS
# =========================================================

def make_documents():

    pdfs = list_pdfs()

    if not pdfs:

        raise FileNotFoundError(
            f"No PDF files found in {DATA_DIR}"
        )

    documents = []

    for pdf in pdfs:

        print(
            "[RAG] Reading:",
            pdf.name
        )

        pages = extract_pages(
            pdf
        )

        for page in pages:

            page_chunks = create_chunks(
                page["text"]
            )

            for chunk_index, text in enumerate(
                page_chunks
            ):

                documents.append(
                    {
                        "text": text,
                        "source": page["source"],
                        "page": page["page"],
                        "chunk": chunk_index,
                    }
                )

    print(
        f"[RAG] Created {len(documents)} chunks "
        f"from {len(pdfs)} PDFs"
    )

    return documents


# =========================================================
# COLLECTION EXISTS
# =========================================================

def collection_exists(client):

    collections = (
        client
        .get_collections()
        .collections
    )

    return any(
        c.name == COLLECTION_NAME
        for c in collections
    )


# =========================================================
# POINT ID
# =========================================================

def make_point_id(document):

    raw = (
        f"{document['source']}|"
        f"{document['page']}|"
        f"{document['chunk']}|"
        f"{document['text']}"
    ).encode(
        "utf-8"
    )

    digest = hashlib.sha256(raw).hexdigest()
    return str(uuid.UUID(digest[:32]))


# =========================================================
# BUILD INDEX
# =========================================================

def build_index(
    force=False
):

    client = get_qdrant()

    embedder = get_embedder()

    # -----------------------------------------------------
    # EXISTING COLLECTION
    # -----------------------------------------------------

    if collection_exists(
        client
    ):

        if not force:

            info = client.get_collection(
                COLLECTION_NAME
            )

            return int(
                info.points_count
                or 0
            )

        print(
            "[RAG] Deleting existing collection..."
        )

        client.delete_collection(
            COLLECTION_NAME
        )

    # -----------------------------------------------------
    # DOCUMENTS
    # -----------------------------------------------------

    documents = make_documents()

    if not documents:

        raise RuntimeError(
            "No readable PDF content found."
        )

    # -----------------------------------------------------
    # VECTOR SIZE
    # -----------------------------------------------------

    dimension = (
        embedder
        .get_sentence_embedding_dimension()
    )

    print(
        "[RAG] Vector dimension:",
        dimension
    )

    # -----------------------------------------------------
    # CREATE COLLECTION
    # -----------------------------------------------------

    client.create_collection(

        collection_name=COLLECTION_NAME,

        vectors_config=VectorParams(
            size=dimension,
            distance=Distance.COSINE,
        ),
    )

    # -----------------------------------------------------
    # EMBEDDINGS
    # -----------------------------------------------------

    texts = [
        d["text"]
        for d in documents
    ]

    vectors = embedder.encode(

        texts,

        batch_size=32,

        show_progress_bar=True,

        normalize_embeddings=True,
    )

    # -----------------------------------------------------
    # POINTS
    # -----------------------------------------------------

    points = []

    for document, vector in zip(
        documents,
        vectors
    ):

        points.append(

            PointStruct(

                id=make_point_id(
                    document
                ),

                vector=vector.tolist(),

                payload=document,
            )
        )

    # -----------------------------------------------------
    # UPLOAD
    # -----------------------------------------------------

    batch_size = 32

    for i in range(
        0,
        len(points),
        batch_size
    ):

        batch = points[
            i:i + batch_size
        ]

        client.upsert(

            collection_name=COLLECTION_NAME,

            points=batch,
        )

        print(
            f"[RAG] Uploaded "
            f"{min(i + batch_size, len(points))}"
            f"/{len(points)}"
        )

    print(
        "[RAG] Index completed."
    )

    return len(points)


# =========================================================
# SEARCH
# =========================================================

def search_guidelines(
    query,
    top_k=TOP_K
):

    client = get_qdrant()

    embedder = get_embedder()

    vector = embedder.encode(
        [query],
        normalize_embeddings=True
    )[0].tolist()

    response = client.query_points(

        collection_name=COLLECTION_NAME,

        query=vector,

        limit=top_k,

        with_payload=True,
    )

    hits = response.points

    results = []

    for hit in hits:

        payload = (
            hit.payload
            or {}
        )

        results.append(
            {
                "score": float(
                    hit.score
                ),
                "text": payload.get(
                    "text",
                    ""
                ),
                "source": payload.get(
                    "source",
                    ""
                ),
                "page": payload.get(
                    "page",
                    ""
                ),
            }
        )

    return results


# =========================================================
# CONTEXT
# =========================================================

def build_context(
    results
):

    if not results:

        return (
            "No relevant guideline passages "
            "were retrieved."
        )

    blocks = []

    for i, result in enumerate(
        results,
        start=1
    ):

        blocks.append(

            f"""
[SOURCE {i}]

Document:
{result["source"]}

Page:
{result["page"]}

Relevance:
{result["score"]:.4f}

Content:
{result["text"]}
"""
        )

    return "\n".join(
        blocks
    )


# =========================================================
# HEALTH
# =========================================================

def health():

    pdfs = list_pdfs()

    result = {
        "pdf_count": len(pdfs),
        "pdfs": [
            p.name
            for p in pdfs
        ],
        "collection": COLLECTION_NAME,
        "qdrant": False,
        "points": 0,
    }

    try:

        client = get_qdrant()

        exists = collection_exists(
            client
        )

        result["qdrant"] = exists

        if exists:

            info = client.get_collection(
                COLLECTION_NAME
            )

            result["points"] = int(
                info.points_count
                or 0
            )

    except Exception as e:

        result["error"] = str(e)

    return result